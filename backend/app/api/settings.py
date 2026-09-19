"""
设置接口：网页端查看 / 修改 LLM 与搜索供应商配置。

- GET  /api/settings       —— 脱敏回显当前生效配置（Key 只显示掩码，绝不出完整值）
- PUT  /api/settings       —— 保存覆盖值到 data/settings.json（立即生效，无需重启）
- POST /api/settings/test  —— 用表单值做一次轻量连通性探测（不落盘、不动单例）

配置合并优先级：网页端保存的覆盖值 > backend/.env（兜底默认值）。
"""
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from app.models.schemas import ApiResponse
from app.services.runtime_settings import (
    LLMOverrides,
    SearchOverrides,
    runtime_settings,
)
from app.utils.logger import logger

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsUpdateRequest(BaseModel):
    """PUT 请求体：字段级覆盖，未提交的组/字段保持不变；reset_* 整组清除回到 .env"""
    model_config = ConfigDict(extra="forbid")

    llm: Optional[LLMOverrides] = None
    search: Optional[SearchOverrides] = None
    reset_llm: bool = False
    reset_search: bool = False


class LLMTestPayload(BaseModel):
    """连接测试的 LLM 表单值。空串/缺省 = 沿用当前已保存配置（便于只测改过的字段）"""
    model_config = ConfigDict(extra="forbid")

    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None


class SettingsTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm: Optional[LLMTestPayload] = None
    search: bool = False


def _validate_base_url(url: str) -> None:
    if url and not url.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=422,
            detail="base_url 必须以 http:// 或 https:// 开头",
        )


@router.get("", response_model=ApiResponse)
async def get_settings():
    """脱敏回显当前生效配置（含每个字段的来源：web / env）"""
    return ApiResponse(code=0, message="ok", data=runtime_settings.masked_view())


@router.put("", response_model=ApiResponse)
async def update_settings(req: SettingsUpdateRequest):
    """保存网页端覆盖值（落盘 data/settings.json，后续请求即时用新配置）"""
    if req.llm is not None:
        _validate_base_url(req.llm.base_url or "")
    if req.search is not None:
        _validate_base_url(req.search.tavily_base_url or "")

    try:
        runtime_settings.update(
            llm=req.llm,
            search=req.search,
            reset_llm=req.reset_llm,
            reset_search=req.reset_search,
        )
    except OSError as e:
        logger.error("settings.json 写入失败: %s", e)
        raise HTTPException(status_code=500, detail=f"设置保存失败：{e}") from e

    return ApiResponse(
        code=0, message="已保存（即时生效）", data=runtime_settings.masked_view()
    )


@router.post("/test", response_model=ApiResponse)
async def test_settings(req: SettingsTestRequest):
    """用表单值做轻量连通性探测（LLM 发一次 1-token chat；搜索查 1 条结果）"""
    result = {}

    if req.llm is not None:
        # 临时构造客户端，不影响进程内单例；llm_config_with 已把超时压到 30s 内。
        # key 未配置时由 LLMClient.test_connection() 统一返回 ok=False
        from app.services.llm_client import LLMClient

        _validate_base_url(req.llm.base_url or "")
        config = runtime_settings.llm_config_with(
            LLMOverrides(
                api_key=req.llm.api_key,
                base_url=req.llm.base_url,
                model=req.llm.model,
            )
        )
        result["llm"] = await LLMClient(config).test_connection()

    if req.search:
        from app.services.search_client import ArxivClient, TavilyClient

        config = runtime_settings.effective_search()
        if config.provider == "tavily":
            if not config.tavily_api_key:
                result["search"] = {"ok": False, "message": "Tavily API Key 未配置"}
            else:
                client = TavilyClient(config)
                try:
                    await client.search("deep learning", max_results=1, search_depth="basic")
                    result["search"] = {"ok": True, "message": "Tavily 连接成功"}
                except Exception as e:
                    result["search"] = {"ok": False, "message": f"{type(e).__name__}: {e}"}
                finally:
                    await client.aclose()
        else:
            client = ArxivClient()
            try:
                await client.search_related_papers(
                    "attention is all you need",
                    "transformer",
                    max_results=1,
                )
                result["search"] = {"ok": True, "message": "arXiv 连接成功"}
            except Exception as e:
                result["search"] = {"ok": False, "message": f"{type(e).__name__}: {e}"}

    if not result:
        raise HTTPException(status_code=422, detail="请求体为空：没有可测试的项")

    return ApiResponse(code=0, message="ok", data=result)
