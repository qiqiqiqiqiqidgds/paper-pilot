"""
PPT 生成接口（W6）
"""
import asyncio
import json
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.models.schemas import ApiResponse
from app.services.ppt_generator import PPTGenerator, save_ppt
from app.utils.storage import load_text_json_async, file_exists
from app.utils.logger import logger
from app.utils.validators import validate_paper_id, validate_filename

router = APIRouter(prefix="/api", tags=["ppt"])


class GeneratePPTRequest(BaseModel):
    paper_id: str = Field(..., pattern=r"^[A-Za-z0-9_\-]{1,64}$")
    include_flaws: bool = False
    include_compare: bool = False
    template: Literal["default"] = Field(default="default")  # 当前仅支持 default


@router.post("/generate-ppt", response_model=ApiResponse)
async def generate_ppt(request: GeneratePPTRequest):
    """
    基于论文分析结果生成 PPT

    会自动加载 breakdown / innovation / flaws / compare 的已保存结果
    """
    validate_paper_id(request.paper_id)
    if not file_exists(request.paper_id):
        raise HTTPException(status_code=404, detail="论文不存在")

    # 1. 加载论文元数据（读 + 解析 text.json 是重 IO，放线程池避免阻塞事件循环 B5）
    data = await load_text_json_async(request.paper_id)
    if not data:
        raise HTTPException(status_code=404, detail="论文数据缺失")
    paper_meta = data.get("meta") or {}

    # 2. 加载各项分析结果（读 JSON 是同步磁盘 IO，放线程里避免阻塞事件循环 B5）
    # B14: 用户勾选了但数据缺失（文件不存在 / 解析失败）时，透出 warnings 而不是静默降级
    warnings: list = []

    async def load_analysis(name: str):
        path = Path(settings.papers_dir) / request.paper_id / f"analysis_{name}.json"
        if not path.exists():
            return None

        # 读 + 解析都在线程池执行（B5）
        def _load():
            return json.loads(path.read_text(encoding="utf-8"))

        try:
            return await asyncio.to_thread(_load)
        except Exception:
            return None

    breakdown = await load_analysis("breakdown")
    innovation = await load_analysis("innovation")
    flaws = await load_analysis("flaws") if request.include_flaws else None

    # 对比结果可以从前端传或从缓存读
    compare = await load_analysis("compare") if request.include_compare else None

    if request.include_flaws and flaws is None:
        warnings.append("flaws 分析结果缺失（可能未运行漏洞分析或解析失败），已跳过漏洞页")
    if request.include_compare and compare is None:
        warnings.append("compare 分析结果缺失（可能未运行联网对比或解析失败），已跳过对比页")

    if not breakdown and not innovation:
        raise HTTPException(
            status_code=400,
            detail="没有可用的分析结果，请先运行「五段拆解」或「创新点」分析"
        )

    # 3. 生成 PPT（python-pptx 是 CPU/IO 密集同步任务，放线程里避免阻塞事件循环）
    def _generate_ppt():
        gen = PPTGenerator(template=request.template)
        ppt_bytes = gen.generate_from_analysis(
            paper_meta=paper_meta,
            breakdown=breakdown,
            innovation=innovation,
            flaws=flaws,
            compare=compare,
            include_flaws=request.include_flaws,
            include_compare=request.include_compare,
        )
        return gen, ppt_bytes

    try:
        gen, ppt_bytes = await asyncio.to_thread(_generate_ppt)
    except Exception as e:
        logger.error(f"PPT 生成失败: {e}")
        raise HTTPException(status_code=500, detail="PPT 生成失败")

    # 4. 保存（save_ppt 落盘 + stat 是同步 IO，放线程池避免阻塞事件循环 B5）
    # `or 'paper'` 兜底：解析失败时 PDF 元数据 title 为空串（得到 "_汇报"），
    # 旧数据里也可能是 null（get 的默认值只对键缺失生效，None[:30] 会 TypeError）
    filename = f"{(paper_meta.get('title') or 'paper')[:30]}_汇报"
    save_path = await asyncio.to_thread(save_ppt, ppt_bytes, request.paper_id, filename)
    ppt_size = (await asyncio.to_thread(save_path.stat)).st_size

    # 5. 返回下载链接
    return ApiResponse(
        code=0,
        data={
            "download_url": f"/api/download-ppt/{save_path.name}",
            "filename": save_path.name,
            "size": ppt_size,
            "pages": len(gen.prs.slides),
            "warnings": warnings,
        }
    )


@router.get("/download-ppt/{filename}")
async def download_ppt(filename: str):
    """下载 PPT 文件"""
    # P1-4: 集中校验
    filename = validate_filename(filename)

    file_path = Path(settings.data_dir) / "ppts" / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="PPT 文件不存在")

    return FileResponse(
        path=str(file_path),
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename=filename,
    )
