"""
联网搜索 + 对比分析接口（W4）
"""
import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.models.schemas import ApiResponse
from app.utils.storage import (
    load_text_json_async,
    file_exists,
    save_analysis_result_async,
)
from app.utils.logger import logger
from app.utils.validators import validate_paper_id
# 注意：以下三个依赖（httpx / openai / prompts 模块）不在顶层 import。
# /api/search-related 只用 get_tavily_client；/api/compare 三个全用。
# 放到 endpoint 函数体里按需 import，router 加载时不再为这些重依赖付出代价。
# from app.services.llm_client import get_llm_client
# from app.services.search_client import get_tavily_client
# from app.agent.prompts.compare import build_compare_messages

router = APIRouter(prefix="/api", tags=["search"])


class SearchRequest(BaseModel):
    paper_id: str = Field(..., pattern=r"^[A-Za-z0-9_\-]{1,64}$")
    max_results: int = Field(default=5, ge=1, le=10)


class CompareRequest(BaseModel):
    paper_id: str = Field(..., pattern=r"^[A-Za-z0-9_\-]{1,64}$")  # 主论文
    max_results: int = Field(default=5, ge=1, le=10)
    paper_language: Literal["中文", "English", "日本語"] = Field(default="中文")


@router.post("/search-related", response_model=ApiResponse)
async def search_related(request: SearchRequest):
    """
    联网搜索与论文相关的工作
    """
    validate_paper_id(request.paper_id)
    if not file_exists(request.paper_id):
        raise HTTPException(status_code=404, detail="论文不存在")

    # 读 + 解析 text.json 是重 IO，放线程池避免阻塞事件循环（B5）
    data = await load_text_json_async(request.paper_id)
    if not data:
        raise HTTPException(status_code=404, detail="论文数据未找到")

    meta = data.get("meta") or {}
    title = meta.get("title") or ""
    abstract = meta.get("abstract") or ""

    if not title:
        raise HTTPException(status_code=400, detail="论文标题缺失")

    # 延迟 import：search_related 只用搜索客户端，不该让 llm_client / prompts 模块拖慢 router 加载
    from app.services.search_client import get_search_client  # noqa: WPS433

    client = get_search_client()
    if not client.is_configured:
        return ApiResponse(
            code=4001,
            message="搜索供应商未配置（tavily 需要 TAVILY_API_KEY；建议 SEARCH_PROVIDER=arxiv 免费方案），无法联网搜索",
            data={"related": []},
        )

    try:
        related = await client.search_related_papers(
            title=title,
            abstract=abstract,
            max_results=request.max_results,
        )
        return ApiResponse(
            code=0,
            data={"related": related},
        )
    except Exception as e:
        logger.error(f"搜索失败: {e}")
        raise HTTPException(status_code=502, detail="搜索失败")


@router.post("/compare", response_model=ApiResponse)
async def compare_with_related(request: CompareRequest):
    """
    对比主论文和联网搜到的相关工作
    """
    validate_paper_id(request.paper_id)
    if not file_exists(request.paper_id):
        raise HTTPException(status_code=404, detail="论文不存在")

    # 读 + 解析 text.json 是重 IO，放线程池避免阻塞事件循环（B5）
    data = await load_text_json_async(request.paper_id)
    if not data:
        raise HTTPException(status_code=404, detail="论文数据未找到")
    meta = data.get("meta") or {}
    main_title = meta.get("title") or ""

    if not main_title:
        raise HTTPException(status_code=400, detail="论文标题缺失")

    # 1. 联网搜（延迟 import：仅在 compare endpoint 内需要）
    from app.services.search_client import get_search_client  # noqa: WPS433

    client = get_search_client()
    related = []
    if client.is_configured:
        try:
            related = await client.search_related_papers(
                title=main_title,
                abstract=meta.get("abstract") or "",
                max_results=request.max_results,
            )
        except Exception as e:
            # 搜索供应商故障要透出 502，不能吞掉后落到下方 code=4001 的"未搜到"
            # ——否则用户会把"arXiv/Tavily 挂了"误判成"这篇论文没有相关工作"
            logger.error(f"联网搜索失败: {e}")
            raise HTTPException(status_code=502, detail="联网搜索失败，请稍后重试")

    if not related:
        return ApiResponse(
            code=4001,
            message="未搜到相关工作（可能搜索供应商未配置或无结果）",
            # 契约约定 main_paper 为 {title, year?, method_summary?}，
            # 不能把完整 PaperMeta dict 整个塞进去
            data={
                "main_paper": {
                    "title": meta.get("title"),
                    "year": meta.get("year"),
                    "method_summary": "",
                },
                "related_papers": [],
                "compare_table": [],
                "summary": "",
            },
        )

    # 2. 用 LLM 生成对比（延迟 import：只在 compare 里用到 LLM + prompts）
    from app.services.llm_client import get_llm_client, LLMConfigError  # noqa: WPS433
    from app.agent.prompts.compare import build_compare_messages  # noqa: WPS433
    from app.models.schemas import CompareResult  # noqa: WPS433

    try:
        llm = get_llm_client()
        messages = build_compare_messages(meta, related, request.paper_language)
        async with asyncio.timeout(settings.llm_timeout_seconds):
            result = await llm.chat_json(messages=messages, response_model=CompareResult)
    except LLMConfigError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except TimeoutError:
        logger.error(f"对比分析整体超时（{settings.llm_timeout_seconds:.0f}s）")
        raise HTTPException(status_code=502, detail="对比分析超时，请重试")
    except Exception as e:
        logger.error(f"对比分析失败: {e}")
        raise HTTPException(status_code=502, detail="对比分析失败")

    # 保存结果供 PPT 使用（B2: 返回 False 表示论文已被删除，跳过落盘即可）
    try:
        saved = await save_analysis_result_async(request.paper_id, "compare", result)
        if saved is False:
            logger.warning(f"论文已被删除，跳过保存对比结果: {request.paper_id}")
    except Exception as e:
        logger.warning(f"保存对比结果失败: {e}")

    return ApiResponse(
        code=0,
        data=result,
    )
