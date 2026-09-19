"""
上传接口（支持 PDF / DOCX）
"""
import asyncio
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from fastapi import APIRouter, UploadFile, File, HTTPException, Request

from app.config import settings
from app.models.schemas import ApiResponse, UploadResponse
# 注意：PDFParser / DOCXParser 不在顶层 import —— 它们分别依赖 pymupdf / python-docx。
# 这里改成在 upload_pdf() 内部按文件后缀按需 import，
# 这样即使 pymupdf 或 python-docx 没装，upload router 仍能加载（其他 endpoint 不受影响）。
from app.utils.storage import (
    generate_paper_id,
    save_upload_file,
    save_text_json,
    get_paper_path,
    delete_paper,
    load_text_json_async,
    file_exists,
)
from app.utils.logger import logger
from app.utils.validators import (
    ALLOWED_FILE_EXTENSIONS,
    check_file_magic,
    sanitize_filename_for_display,
)

router = APIRouter(prefix="/api", tags=["upload"])

# 文件类型 → Media-Type 映射
MEDIA_TYPE_MAP = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _get_file_type(suffix: str) -> str:
    """统一文件类型字符串（去掉点号）"""
    return suffix.lstrip(".").lower()


async def _read_with_size_limit(file: UploadFile, max_size: int) -> bytes:
    """
    流式读取上传文件，超大立即拒绝（P1-1）
    比 file.read() 全量读取后再校验更安全：避免攻击者发 1GB 文件占用内存。

    :return: 文件 bytes
    :raises: HTTPException 413 文件过大
    """
    chunks = []
    total = 0
    chunk_size = 1024 * 1024  # 1MB 每块
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_size:
            # 显式抛 413（FastAPI 默认会包成 500）
            raise HTTPException(
                status_code=413,
                detail=f"文件过大（>{max_size / 1024 / 1024:.0f}MB）",
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/upload", response_model=ApiResponse)
async def upload_pdf(request: Request, file: UploadFile = File(...)):
    """
    上传 PDF / DOCX 文件

    返回 paper_id，后续分析都用这个 ID
    """
    # 0. 早期 Content-Length 预检（P1-1）
    # 即使客户端声称文件很大，在真正读之前先拒；省内存
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            cl = int(content_length)
            if cl > settings.max_upload_size_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"文件过大（{cl / 1024 / 1024:.1f}MB），限制 {settings.max_upload_size_bytes // (1024 * 1024)}MB",
                )
        except ValueError:
            pass  # 非数字就忽略，继续流式读

    # 1. 校验文件类型
    filename = file.filename or "unnamed.docx"
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_FILE_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"仅支持 PDF / DOCX 文件，收到: {suffix or '(无后缀)'}"
        )

    # 2. 流式读取 + 大小限制（P1-1）
    content = await _read_with_size_limit(file, settings.max_upload_size_bytes)
    size = len(content)

    if size < 100:
        raise HTTPException(
            status_code=400,
            detail="文件过小，可能不是有效文件"
        )

    # 3. Magic Number 校验（P1-2）：防止扩展名伪装
    if not check_file_magic(content, suffix):
        raise HTTPException(
            status_code=400,
            detail=f"文件内容与扩展名 {suffix} 不匹配，可能是损坏文件或伪装文件",
        )

    # 4. 生成 paper_id 并保存（写盘是同步 IO，放线程里避免阻塞事件循环 B5）
    paper_id = generate_paper_id()
    try:
        save_path = await asyncio.to_thread(save_upload_file, content, paper_id, filename)
    except Exception as e:
        logger.error(f"保存文件失败: {e}")
        # 清理 get_paper_dir 已 mkdir 出的空目录（否则残留不可见垃圾目录）
        await asyncio.to_thread(delete_paper, paper_id)
        raise HTTPException(status_code=500, detail="保存文件失败")

    # 5. 选 parser 解析（按后缀按需 import —— PDF/DOCX 二选一，从不同时需要）
    if suffix == ".pdf":
        from app.services.pdf_parser import PDFParser  # noqa: WPS433  延迟 import
        parser_cls = PDFParser
    elif suffix == ".docx":
        from app.services.docx_parser import DOCXParser  # noqa: WPS433  延迟 import
        parser_cls = DOCXParser
    else:
        await asyncio.to_thread(delete_paper, paper_id)
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {suffix}")

    # 解析是 CPU/IO 密集的同步任务，放线程里避免阻塞事件循环（P1-修复）
    def _parse():
        with parser_cls(save_path) as parser:
            return parser.parse()

    try:
        parsed = await asyncio.to_thread(_parse)
    except Exception as e:
        # 详细错误写 log，不返回给前端（避免泄露内部路径/堆栈）
        logger.error(f"文件解析失败 [{suffix}]: {type(e).__name__}: {e}")
        await asyncio.to_thread(delete_paper, paper_id)
        raise HTTPException(
            status_code=400,
            detail=f"文件解析失败：不是有效的 {suffix.upper()[1:]} 文件（或已损坏/加密）"
        )

    # 6. 保存解析结果（带原始文件名，方便下载时还原）
    # B18: meta 里同时记录原始文件名/上传时间，供 list_papers 列表展示
    # （旧 text.json 无这两个键，list_papers 读取侧有回退逻辑）
    # 本地时间 + 时区偏移：naive 本地时间在跨时区/DST 部署下排序会错乱，
    # 纯 UTC 又会让 UTC+8 的"今天凌晨上传"在前端显示成昨天
    now_iso = datetime.now().astimezone().isoformat()
    parsed.setdefault("meta", {})
    parsed["meta"]["original_filename"] = filename
    parsed["meta"]["uploaded_at"] = now_iso
    parsed_with_filename = {**parsed, "original_filename": filename}
    # dumps + 写盘是同步 IO，放线程里避免阻塞事件循环（B5）
    try:
        await asyncio.to_thread(save_text_json, paper_id, parsed_with_filename)
    except Exception as e:
        # 解析成功但落盘失败（磁盘满/权限）必须清理目录，否则会留下只有 raw.* 的
        # "幽灵目录"：file_exists 为 True 但 load_text_json 为 None，且不出现在论文列表里
        logger.error(f"保存解析结果失败: {e}")
        await asyncio.to_thread(delete_paper, paper_id)
        raise HTTPException(status_code=500, detail="保存解析结果失败")

    # 7. 构造响应
    meta = parsed["meta"]
    response = UploadResponse(
        paper_id=paper_id,
        filename=filename,
        size=size,
        pages=parsed["page_count"],
        file_type=_get_file_type(suffix),
        title=meta["title"],
        authors=meta["authors"],
        abstract=meta["abstract"],
        uploaded_at=now_iso,
    )

    # 日志：清洗 title 防止日志注入
    safe_title = sanitize_filename_for_display(meta['title'])
    logger.info(
        "上传成功: %s - %s (%s 页, %s)",
        paper_id, safe_title, parsed['page_count'], suffix,
    )

    return ApiResponse(
        code=0,
        message="上传成功",
        data=response.model_dump()
    )


def _list_papers_sync() -> list:
    """遍历论文目录读 text.json 并组装列表（同步磁盘 IO，B5: 由调用方包 to_thread）"""
    papers = []
    papers_dir = Path(settings.papers_dir)
    if papers_dir.exists():
        for paper_dir in papers_dir.iterdir():
            if not paper_dir.is_dir():
                continue
            text_json = paper_dir / "text.json"
            if not text_json.exists():
                continue
            import json
            try:
                data = json.loads(text_json.read_text(encoding="utf-8"))
                meta = data.get("meta", {})
                # 找文件
                files = list(paper_dir.glob("raw.*"))
                if not files:
                    continue
                file_path = files[0]
                stat = file_path.stat()
                file_type = _get_file_type(file_path.suffix)

                paper_id = paper_dir.name
                has_breakdown = (paper_dir / "analysis_breakdown.json").exists()
                has_innovation = (paper_dir / "analysis_innovation.json").exists()
                has_compare = (paper_dir / "analysis_compare.json").exists()
                has_flaws = (paper_dir / "analysis_flaws.json").exists()

                papers.append({
                    "paper_id": paper_id,
                    # B18: 优先用上传时记录的原始文件名/上传时间（旧 text.json 无这两个键时回退）
                    "filename": meta.get("original_filename") or file_path.name,
                    "size": stat.st_size,
                    "file_type": file_type,
                    "title": meta.get("title", ""),
                    "authors": meta.get("authors", []),
                    "pages": data.get("page_count", 0),
                    "uploaded_at": meta.get("uploaded_at")
                                   or datetime.fromtimestamp(stat.st_ctime).astimezone().isoformat(),
                    "has_breakdown": has_breakdown,
                    "has_innovation": has_innovation,
                    "has_compare": has_compare,
                    "has_flaws": has_flaws,
                })
            except Exception as e:
                logger.warning(f"读取论文失败 {paper_dir.name}: {e}")
    return papers


def _uploaded_at_sort_key(entry: dict) -> float:
    """P3-7: 论文列表按上传时间排序的键（真实时间戳，替代旧字符串排序）

    旧实现按字符串排序 uploaded_at：ISO 带 T、带空格、跨时区偏移（+08:00 vs
    +00:00）混合时会乱序。这里解析为可比的数值时间戳：
    - 兼容 datetime.fromisoformat 认识的多种格式（带 T / 带空格分隔），
      并额外兜底 UTC 的 "Z" 后缀；
    - tz-aware 时间按真实时刻比较；naive 时间按本地时区解释（与上传时
      datetime.now().astimezone() 的写入口径一致）；
    - 解析失败/为空（旧数据、脏数据）返回 -inf，倒序排序时稳定排在最后，不崩溃。
    """
    raw = (entry.get("uploaded_at") or "").strip()
    if raw:
        if raw.endswith(("Z", "z")):
            raw = raw[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(raw).timestamp()
        except ValueError:
            pass
    return float("-inf")


@router.get("/papers", response_model=ApiResponse)
async def list_papers():
    """获取论文库列表"""
    # 遍历目录 + 读 text.json 是同步磁盘 IO，放线程里避免阻塞事件循环（B5）
    papers = await asyncio.to_thread(_list_papers_sync)

    # 按时间倒序（P3-7: 按时间戳排序，解析失败的条目稳定排最后）
    papers.sort(key=_uploaded_at_sort_key, reverse=True)

    return ApiResponse(
        code=0,
        data={
            "total": len(papers),
            "items": papers
        }
    )


@router.get("/papers/{paper_id}", response_model=ApiResponse)
async def get_paper(paper_id: str):
    """获取论文详情"""
    from app.utils.validators import validate_paper_id
    paper_id = validate_paper_id(paper_id)

    # 读 + 解析 text.json 是重 IO，放线程池避免阻塞事件循环（B5）
    data = await load_text_json_async(paper_id)
    if not data:
        raise HTTPException(status_code=404, detail="论文不存在")

    file_path = get_paper_path(paper_id)
    if not file_path:
        raise HTTPException(status_code=404, detail="文件不存在")

    return ApiResponse(
        code=0,
        data={
            "paper_id": paper_id,
            # 与列表接口同口径：优先原始文件名（raw.pdf 是内部命名，对用户无意义）
            "filename": (data.get("meta") or {}).get("original_filename") or file_path.name,
            "size": (await asyncio.to_thread(file_path.stat)).st_size,
            "file_type": _get_file_type(file_path.suffix),
            "meta": data.get("meta") or {},
            "page_count": data.get("page_count", 0),
            "full_text_length": len(data.get("full_text") or ""),
        }
    )


@router.delete("/papers/{paper_id}", response_model=ApiResponse)
async def delete_paper_endpoint(paper_id: str):
    """删除论文"""
    from app.utils.validators import validate_paper_id
    paper_id = validate_paper_id(paper_id)
    if not file_exists(paper_id):
        raise HTTPException(status_code=404, detail="论文不存在")
    # rmtree 整目录（raw 文件最大 50MB）是同步 IO，放线程池避免阻塞事件循环（B5）
    await asyncio.to_thread(delete_paper, paper_id)
    return ApiResponse(code=0, message="已删除")


@router.get("/papers/{paper_id}/file")
async def get_paper_file(paper_id: str):
    """下载论文文件（PDF / DOCX，根据后缀返回正确 media_type）"""
    from fastapi.responses import FileResponse
    from app.utils.validators import validate_paper_id
    import json

    paper_id = validate_paper_id(paper_id)
    file_path = get_paper_path(paper_id)
    if not file_path or not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    suffix = file_path.suffix.lower()
    # P2-26: 未知后缀立即报警（理论上不会发生，后端写入有白名单）
    media_type = MEDIA_TYPE_MAP.get(suffix)
    if media_type is None:
        logger.error(
            f"未知文件后缀: paper_id={paper_id}, suffix={suffix}, "
            f"path={file_path}"
        )
        raise HTTPException(status_code=500, detail="文件后缀异常，请联系管理员")

    # 从 text.json 读原始文件名（避免下载时变成 raw.docx）
    download_name = file_path.name  # 兜底
    text_json = file_path.parent / "text.json"
    if text_json.exists():
        try:
            raw = await asyncio.to_thread(text_json.read_text, encoding="utf-8")
            data = json.loads(raw)
            original = data.get("original_filename")
            if original:
                download_name = original
        except Exception:
            pass

    # 对非 ASCII 文件名做 RFC 5987 编码（避免 latin-1 报错）
    quoted = quote(download_name, safe="")
    ascii_fallback = quote(download_name, safe="").replace("%", "_")
    disposition = (
        f"attachment; "
        f'filename="{ascii_fallback}"; '
        f"filename*=UTF-8''{quoted}"
    )
    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=download_name,
        headers={"Content-Disposition": disposition},
    )
