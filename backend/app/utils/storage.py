"""
文件存储工具
"""
import asyncio
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import HTTPException

from app.config import settings
from app.utils.logger import logger
from app.utils.validators import validate_paper_id


# PPT 文件名前缀：{paper_id}_{safe_filename}.pptx（见 ppt_generator.save_ppt）
# paper_id 为 p_YYYY_MM_DD_<8位hex>（见 generate_paper_id），
# 冲突兜底时为 12 位 hex（B7），故 hex 段按 {8,12} 匹配；
# safe_filename 经清洗后可能含下划线，故只能从头部用正则提取，不能按 "_" 分段
PAPER_ID_PREFIX_RE = re.compile(r"^p_\d{4}_\d{2}_\d{2}_[0-9a-f]{8,12}")


def generate_paper_id() -> str:
    """生成论文 ID（B7：目录已存在时重试，避免 8 位 hex 碰撞覆盖已有论文）"""
    date_part = datetime.now().strftime("%Y_%m_%d")
    papers_dir = Path(settings.papers_dir)
    # 最多重试 5 次；仍冲突（概率极低）则加长为 12 位 hex
    for _ in range(5):
        unique_part = uuid.uuid4().hex[:8]
        paper_id = f"p_{date_part}_{unique_part}"
        if not (papers_dir / paper_id).exists():
            return paper_id
    return f"p_{date_part}_{uuid.uuid4().hex[:12]}"


def get_paper_dir(paper_id: str, create: bool = True) -> Path:
    """获取论文存储目录

    B2: create=False 时只定位不创建 —— 供"落盘已生成结果"的调用方使用，
    避免论文被删除后因写分析结果而"复活"空目录。
    """
    paper_dir = Path(settings.papers_dir) / paper_id
    if create:
        paper_dir.mkdir(parents=True, exist_ok=True)
    return paper_dir


def _atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """P2-3: 原子写文本文件 —— 先写同目录临时文件，成功后再 replace 覆盖目标。

    直接 write_text 在进程崩溃 / 磁盘满时可能留下半截 JSON：text.json 损坏
    等于论文丢失，analysis_*.json 损坏需重跑完整分析（重新耗 token）。
    与 save_ppt 的 tmp+replace 模式一致（Path.replace 即 os.replace，同目录
    内原子生效）：写失败时删除临时文件，目标文件保持原内容不受影响。
    注意 text 须在调用前已完全生成（json.dumps 先行），序列化异常不会触碰原文件。
    所有 JSON 落盘点（save_text_json / save_analysis_result）统一走本 helper。
    """
    tmp_path = path.with_suffix(path.suffix + f".{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp_path.write_text(text, encoding=encoding)
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def save_upload_file(file_content: bytes, paper_id: str, filename: str) -> Path:
    """保存上传的文件"""
    paper_dir = get_paper_dir(paper_id)
    # 用 paper_id 重命名，避免路径问题
    suffix = Path(filename).suffix.lower() or ".pdf"
    save_path = paper_dir / f"raw{suffix}"
    save_path.write_bytes(file_content)
    logger.info(f"已保存文件: {save_path} ({len(file_content)} bytes)")
    return save_path


def save_text_json(paper_id: str, data: dict) -> Path:
    """保存解析后的文本 JSON"""
    import json
    paper_dir = get_paper_dir(paper_id)
    json_path = paper_dir / "text.json"
    # P2-3: 原子写（tmp+replace），崩溃/磁盘满不留半截 JSON
    _atomic_write_text(json_path, json.dumps(data, ensure_ascii=False, indent=2))
    return json_path


def load_text_json(paper_id: str) -> Optional[dict]:
    """加载解析后的文本 JSON"""
    import json
    json_path = Path(settings.papers_dir) / paper_id / "text.json"
    if not json_path.exists():
        return None
    return json.loads(json_path.read_text(encoding="utf-8"))


async def load_text_json_async(paper_id: str) -> Optional[dict]:
    """load_text_json 的异步版。

    text.json 含全文 + 分页文本，可达数 MB；read_text + json.loads 是全项目
    最重的读操作，且处在 analyze / search / compare / ppt 等最热路径上。
    async 路由请一律用本函数（放线程池执行），避免阻塞事件循环拖慢所有并发请求。
    """
    return await asyncio.to_thread(load_text_json, paper_id)


def file_exists(paper_id: str) -> bool:
    """检查论文是否存在"""
    paper_dir = Path(settings.papers_dir) / paper_id
    return paper_dir.exists() and any(paper_dir.iterdir())


def delete_paper(paper_id: str) -> bool:
    """删除论文（包括对应的 PPT 文件）"""
    paper_dir = Path(settings.papers_dir) / paper_id
    deleted = False
    if paper_dir.exists():
        shutil.rmtree(paper_dir)
        deleted = True
        logger.info(f"已删除论文目录: {paper_id}")

    # 联动删除该论文相关的 PPT
    ppts_dir = Path(settings.data_dir) / "ppts"
    if ppts_dir.exists():
        for ppt in ppts_dir.glob(f"{paper_id}_*.pptx"):
            ppt.unlink()
            logger.info(f"已删除关联 PPT: {ppt.name}")
            deleted = True

    return deleted


def save_analysis_result(paper_id: str, analysis_type: str, result: dict):
    """保存分析结果到 JSON（统一入口，避免各接口重复实现）

    B2: 不再创建目录。论文可能在分析期间被用户删除 —— 此时返回 False
    （不写文件、不抛异常），由调用方记 warning 跳过落盘，
    避免"复活"已删除的论文目录（变成只剩 analysis_*.json 的僵尸目录）。
    """
    import json
    paper_dir = get_paper_dir(paper_id, create=False)
    if not paper_dir.exists() or not (paper_dir / "text.json").exists():
        logger.warning(
            f"论文目录已不存在（可能已被删除），跳过保存分析结果: "
            f"{paper_id} / {analysis_type}"
        )
        return False
    analysis_file = paper_dir / f"analysis_{analysis_type}.json"
    # 不缩进，节省磁盘；P2-3: 原子写（tmp+replace），崩溃不留半截 JSON
    # （损坏即丢失本次分析，需重新跑完整分析耗 token）
    _atomic_write_text(
        analysis_file,
        json.dumps(result, ensure_ascii=False, separators=(",", ":")),
    )
    logger.debug(f"已保存分析结果: {analysis_file}")
    return analysis_file


async def save_analysis_result_async(paper_id: str, analysis_type: str, result: dict):
    """save_analysis_result 的异步版（写盘放线程池，避免阻塞事件循环）"""
    return await asyncio.to_thread(save_analysis_result, paper_id, analysis_type, result)


def has_analysis(paper_id: str, analysis_type: str) -> bool:
    """检查某论文是否已有某类型分析结果"""
    paper_dir = Path(settings.papers_dir) / paper_id
    return (paper_dir / f"analysis_{analysis_type}.json").exists()


def get_paper_path(paper_id: str) -> Optional[Path]:
    """获取论文 PDF 路径"""
    paper_dir = Path(settings.papers_dir) / paper_id
    for f in paper_dir.glob("raw.*"):
        return f
    return None


def cleanup_orphan_ppts() -> int:
    """
    清理孤儿 PPT（P1-18）：仅删除「关联论文已被删除」的 PPT。

    注意：不再按文件 mtime 做「超 N 天即删」的无差别清理——论文还在时，
    用户生成的 PPT 是正常资产，按时间静默删除会造成数据丢失
    （且启动/定时任务触发时用户无感知，前端保存的 download_url 会 404）。
    论文被删除时的 PPT 联动清理由 delete_paper() 负责。

    :return: 清理数量
    """
    ppts_dir = Path(settings.data_dir) / "ppts"
    if not ppts_dir.exists():
        return 0

    papers_dir = Path(settings.papers_dir)
    removed = 0

    for ppt in ppts_dir.glob("*.pptx"):
        try:
            # 文件名格式：{paper_id}_{safe_filename}.pptx
            # safe_filename 经 re.sub 清洗后可能含下划线，所以不能用 split("_") 提取 paper_id
            # （之前用 split 首段，paper_id 含下划线导致首段恒为 "p" → 误判所有 PPT 为孤儿）
            stem = ppt.stem  # 不含后缀
            match = PAPER_ID_PREFIX_RE.match(stem)
            if not match:
                # 不认识的命名 → 保留文件，仅打 warning，绝不要删
                logger.warning(f"跳过不认识的 PPT 文件（无法提取 paper_id）: {ppt.name}")
                continue
            paper_id = match.group(0)
            # 二次校验：与上传接口同一规则（防止伪造/非法的 paper_id 前缀）
            try:
                validate_paper_id(paper_id)
            except HTTPException:
                logger.warning(f"跳过非法 paper_id 的 PPT 文件: {ppt.name}")
                continue
            # 论文目录不存在 → 孤儿
            if not (papers_dir / paper_id).exists():
                ppt.unlink()
                removed += 1
                logger.info(f"清理孤儿 PPT（论文已删除）: {ppt.name}")
        except Exception as e:
            logger.warning(f"清理 PPT 失败 {ppt.name}: {e}")

    if removed:
        logger.info(f"PPT 清理完成: 移除 {removed} 个文件")
    return removed


def get_disk_usage() -> dict:
    """
    获取当前磁盘使用情况（用于健康检查 / 监控）
    """
    import shutil
    data_dir = Path(settings.data_dir)
    if not data_dir.exists():
        return {"total_mb": 0, "used_mb": 0, "free_mb": 0, "percent": 0}

    usage = shutil.disk_usage(data_dir)
    return {
        "total_mb": round(usage.total / 1024 / 1024, 1),
        "used_mb": round(usage.used / 1024 / 1024, 1),
        "free_mb": round(usage.free / 1024 / 1024, 1),
        "percent": round(usage.used / usage.total * 100, 1) if usage.total > 0 else 0,
    }
