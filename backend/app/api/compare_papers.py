"""
多篇论文对比接口（W5）
对比的是用户已上传的多篇论文
"""
import asyncio
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.models.schemas import ApiResponse, CompareResult
from app.services.llm_client import get_llm_client, LLMConfigError
from app.utils.storage import (
    load_text_json_async,
    file_exists,
    save_analysis_result_async,
)
from app.utils.logger import logger
from app.utils.validators import validate_paper_id
from app.agent.prompts.compare import build_compare_messages

router = APIRouter(prefix="/api", tags=["compare"])


class ComparePapersRequest(BaseModel):
    paper_ids: list[str] = Field(
        ..., min_length=2, max_length=5,
        description="论文 ID 列表（每项须匹配 ^[A-Za-z0-9_-]{1,64}$）",
    )
    main_id: str = Field(..., pattern=r"^[A-Za-z0-9_\-]{1,64}$", description="主论文 ID")
    paper_language: Literal["中文", "English", "日本語"] = Field(default="中文")


@router.post("/compare-papers", response_model=ApiResponse)
async def compare_papers(request: ComparePapersRequest):
    """
    对比多篇已上传的论文（区别于联网搜的对比）
    """
    # 1. 校验（去重 + paper_id 格式）
    if len(set(request.paper_ids)) != len(request.paper_ids):
        raise HTTPException(status_code=400, detail="paper_ids 含重复 ID")
    validate_paper_id(request.main_id)
    for pid in request.paper_ids:
        validate_paper_id(pid)
    if request.main_id not in request.paper_ids:
        raise HTTPException(status_code=400, detail="main_id 必须在 paper_ids 中")

    # 2. 加载所有论文的元数据（读 + 解析 text.json 是重 IO，放线程池避免阻塞事件循环 B5）
    papers_data = []
    for pid in request.paper_ids:
        if not file_exists(pid):
            raise HTTPException(status_code=404, detail=f"论文不存在: {pid}")
        data = await load_text_json_async(pid)
        if not data:
            raise HTTPException(status_code=404, detail=f"论文数据缺失: {pid}")
        # 防御：text.json 缺 meta 键时不抛 KeyError（参照 search.py 的写法）；
        # 用 `or` 兜底显式 null（损坏/旧数据里 abstract 可能是 null，
        # get 的默认值只对"键缺失"生效，对 null 不生效）
        meta = (data or {}).get("meta") or {}
        papers_data.append({
            "paper_id": pid,
            "title": meta.get("title") or "",
            "authors": meta.get("authors") or [],
            "year": meta.get("year"),
            "abstract": meta.get("abstract") or "",
            "is_main": pid == request.main_id,
        })

    # 3. 主论文
    main_paper = next(p for p in papers_data if p["is_main"])

    # 4. 其他论文作为"相关工作"（截断摘要防 token 超限）
    related = [
        {
            "title": p["title"],
            "url": "",
            "content": f"作者：{', '.join(p['authors'])}\n摘要：{p['abstract'][:1000]}",
            "score": 1.0,
            "paper_id": p["paper_id"],
        }
        for p in papers_data if not p["is_main"]
    ]

    # 截断主论文摘要，避免多论文加起来超 token
    main_paper_safe = {**main_paper, "abstract": main_paper.get("abstract", "")[:2000]}

    # 5. LLM 生成对比（带整体超时，与 analyze 的 legacy 路径同等待遇）
    try:
        llm = get_llm_client()
        messages = build_compare_messages(main_paper_safe, related, request.paper_language)
        async with asyncio.timeout(settings.llm_timeout_seconds):
            result = await llm.chat_json(messages=messages, response_model=CompareResult)
    except LLMConfigError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except TimeoutError:
        logger.error(f"多篇对比整体超时（{settings.llm_timeout_seconds:.0f}s）")
        raise HTTPException(status_code=502, detail="对比分析超时，请重试")
    except Exception as e:
        logger.error(f"多篇对比失败: {e}")
        raise HTTPException(status_code=502, detail="对比失败")

    # 6. 回填 paper_id：LLM 输出不带 paper_id。
    #    优先按标题精确匹配（LLM 可能少输出/重排 related_papers，纯位置回填会错位）；
    #    未匹配的条目再按输入顺序位置兜底。
    _backfill_related_paper_ids(result.get("related_papers", []), related)

    # 保存供 PPT 使用（B2: 返回 False 表示论文已被删除，跳过落盘即可）
    try:
        saved = await save_analysis_result_async(request.main_id, "compare", result)
        if saved is False:
            logger.warning(f"论文已被删除，跳过保存对比结果: {request.main_id}")
    except Exception as e:
        logger.warning(f"保存对比结果失败: {e}")

    return ApiResponse(code=0, data=result)


def _backfill_related_paper_ids(related_papers: list, related_sources: list) -> None:
    """把真实论文 ID 回填到 LLM 输出的 related_papers（就地修改）

    策略：
    1. 标题精确匹配（忽略大小写/首尾空白），一篇论文只匹配一次；
    2. 未匹配的论文按输入顺序位置兜底。
    """
    source_by_title: dict = {}
    for p in related_sources:
        title = (p.get("title") or "").strip().lower()
        if title:
            source_by_title.setdefault(title, p["paper_id"])

    for rp in related_papers:
        if rp.get("paper_id"):
            continue
        title = (rp.get("title") or "").strip().lower()
        if title and title in source_by_title:
            rp["paper_id"] = source_by_title.pop(title)

    # 位置兜底：剩余未匹配的（LLM 编造了输入之外的标题 / 少输出）
    matched_ids = {rp.get("paper_id") for rp in related_papers}
    remaining = [p["paper_id"] for p in related_sources if p["paper_id"] not in matched_ids]
    idx = 0
    for rp in related_papers:
        if rp.get("paper_id"):
            continue
        if idx >= len(remaining):
            break
        rp["paper_id"] = remaining[idx]
        idx += 1
