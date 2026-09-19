"""
健康检查
"""
import os
from fastapi import APIRouter
from app.config import settings
from app.models.schemas import ApiResponse
from app.services.runtime_settings import runtime_settings

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=ApiResponse)
async def health_check():
    """健康检查（公开端点，不返回任何内部路径或敏感信息）"""
    # P3-3: prod 只返回最小状态 —— 组件 key 配置状态（llm/search/tavily）、
    # data_dir_ok、版本号都属部署细节，不应从公开端点暴露；非 prod 保留细节便于联调
    if settings.is_production:
        return ApiResponse(code=0, message="ok", data={"status": "ok"})

    # 检查 LLM 客户端（.env + 网页端设置合并后的生效配置）
    llm_cfg = runtime_settings.effective_llm()
    llm_status = "configured" if llm_cfg.api_key else "missing_key"

    # 联网搜索供应商状态（arxiv 免费无需 key；tavily 需要 key）
    search_cfg = runtime_settings.effective_search()
    if search_cfg.provider == "tavily":
        search_status = "configured" if search_cfg.tavily_api_key else "missing_key"
    else:
        search_status = "arxiv"

    # 仅返回数据目录是否可访问（bool），不暴露绝对路径
    # settings.papers_dir 是 str（os.path.join），用 os.path.exists 检测
    data_dir_ok = bool(settings.papers_dir and os.path.isdir(settings.papers_dir))

    return ApiResponse(
        code=0,
        message="ok",
        data={
            "status": "ok",
            "version": "0.1.0",
            "llm": llm_status,
            "search": search_status,
            "tavily": "configured" if search_cfg.tavily_api_key else "missing_key",
            "data_dir_ok": data_dir_ok,
        }
    )
