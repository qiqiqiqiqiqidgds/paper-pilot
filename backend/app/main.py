"""
FastAPI 应用入口
"""
import asyncio
import importlib
import sys
from pathlib import Path

# 把 backend 目录加到 sys.path（让 uvicorn app.main:app 能找到包）
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.config import settings
from app.utils.logger import logger
from app.utils.auth import APIKeyAuthMiddleware
from app.utils.ratelimit import RateLimitMiddleware
from app.utils.error_handler import register_exception_handlers
from app.middleware.request_id import RequestIDMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    # 启动：先加载网页端设置覆盖值（data/settings.json），后续日志用生效配置
    from app.services.runtime_settings import runtime_settings

    llm_cfg = runtime_settings.effective_llm()
    search_cfg = runtime_settings.effective_search()

    logger.info("=" * 60)
    logger.info("PaperPilot Backend 启动中...")
    logger.info(f"  数据目录: {settings.data_dir}")
    logger.info(f"  LLM 模型: {llm_cfg.model} @ {llm_cfg.base_url}")
    logger.info(f"  搜索供应商: {search_cfg.provider}")
    logger.info(f"  日志级别: {settings.log_level}")
    logger.info("=" * 60)

    # 确保数据目录存在
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.papers_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.uploads_dir).mkdir(parents=True, exist_ok=True)

    # 检查 API Key
    if not llm_cfg.api_key:
        logger.warning("⚠️  LLM API Key 未配置（可在网页「设置」界面或 backend/.env 填写），分析接口将失败")
    else:
        logger.info("✓ LLM API Key 已配置")

    if not settings.tavily_api_key:
        logger.info("ℹ  Tavily API Key 未配置（W4 联网搜索需要）")

    # 检查访问鉴权
    if settings.auth_enabled:
        logger.info("🔒 API Key 鉴权已启用（请求需带 X-API-Key header）")
    else:
        logger.warning(
            "⚠️  APP_API_KEY 未配置，鉴权关闭（仅适合本地开发）"
            "——部署前务必设置 APP_API_KEY，并将 APP_ENV 设为 prod"
        )
        if settings.app_host == "0.0.0.0":
            logger.warning(
                "⚠️  当前监听 0.0.0.0 且未启用鉴权：局域网内任何设备都可访问本服务"
                "（含消耗 LLM token 的分析接口）。仅供本机开发时请改用 APP_HOST=127.0.0.1"
            )

    # 多 worker 限流警告（P0-2）
    if settings.app_workers > 1:
        logger.warning(
            f"⚠️  APP_WORKERS={settings.app_workers}：当前内存限流为进程内字典，"
            f"实际限流上限会放大 {settings.app_workers} 倍。"
            "生产请使用单 worker（--workers 1）或反代层限流。"
        )

    # P1-15: prod 环境必须配置 APP_API_KEY（鉴权）
    if settings.is_production and not settings.auth_enabled:
        raise RuntimeError(
            "❌ APP_ENV=prod 但 APP_API_KEY 未配置！\n"
            "  生产环境必须启用 API Key 鉴权，否则任何人可直接调用消耗 LLM token。\n"
            "  请设置 APP_API_KEY=<强随机串> 后重启。\n"
            "  生成本地强随机串：python -c \"import secrets; print(secrets.token_urlsafe(32))\""
        )

    # P1-18: 启动时清理一次孤儿 PPT（论文已删除的 PPT 文件；不按时间删用户的 PPT）
    # P3-8: rmtree/unlink 级同步磁盘扫描包 to_thread，不阻塞事件循环（对齐 B5 纪律）
    try:
        from app.utils.storage import cleanup_orphan_ppts
        removed = await asyncio.to_thread(cleanup_orphan_ppts)
        if removed:
            logger.info(f"启动清理: 移除 {removed} 个孤儿 PPT")
    except Exception as e:
        logger.warning(f"启动清理 PPT 失败: {e}")

    # P1-18: 启动后台定期清理任务（每 6 小时一次）
    async def periodic_cleanup():
        from app.utils.storage import cleanup_orphan_ppts
        while True:
            try:
                await asyncio.sleep(6 * 3600)  # 6 小时
                # 同步磁盘扫描放线程里，避免阻塞事件循环（B5）
                removed = await asyncio.to_thread(cleanup_orphan_ppts)
                if removed:
                    logger.info(f"定期清理: 移除 {removed} 个孤儿 PPT")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"定期清理任务异常: {e}")

    cleanup_task = asyncio.create_task(periodic_cleanup())

    yield

    # 关闭：取消清理任务
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass

    # 关闭：清理搜索客户端连接池（Tavily / Arxiv，P1-7）
    # P3-8: 仅在单例已创建时关闭 —— 旧实现无条件 get_search_client()，
    # 进程内从未用过联网搜索时会"先实例化再关闭"一个没人用过的客户端
    try:
        from app.services.search_client import get_created_search_client
        client = get_created_search_client()
        if client is not None:
            await client.aclose()
    except Exception as e:
        logger.warning(f"关闭搜索客户端连接池失败: {e}")

    # 关闭
    logger.info("PaperPilot Backend 关闭")


def _schema_urls() -> dict:
    """API schema 页面的注册开关。

    生产环境关闭 /docs /redoc /openapi.json（不对外暴露端点清单与参数模型）。
    注意：仅靠中间件拦截不够 —— auth/ratelimit 对非 /api/* 路径直接放行，
    必须从路由注册层面关闭才能真正收敛。
    """
    if settings.is_production:
        return {"docs_url": None, "redoc_url": None, "openapi_url": None}
    return {"docs_url": "/docs", "redoc_url": "/redoc", "openapi_url": "/openapi.json"}


# 创建 FastAPI 应用
app = FastAPI(
    title="PaperPilot API",
    description="AI 论文/文献伴读 Agent - 后端服务",
    version="0.1.0",
    lifespan=lifespan,
    **_schema_urls(),
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 中间件顺序：后注册的在外层（先执行）
# Request ID 放最外层：本请求所有日志（auth/ratelimit 拒绝日志也算）都带 request_id
# 鉴权放外层：先做鉴权，避免无效请求消耗限流配额
# 限流放内层：通过鉴权后才计数
app.add_middleware(RateLimitMiddleware)   # 内层：限流
app.add_middleware(APIKeyAuthMiddleware)  # 中层：鉴权
app.add_middleware(RequestIDMiddleware)   # 外层：request_id（Sprint 2 / I1）

# P1-3: 全局异常处理
register_exception_handlers(app)

# ====== 路由 lazy 加载 ======
# 不用 `from app.api import health, upload, ...` 这种 eager import，
# 否则任何一个 router 的依赖（openai/pymupdf/python-pptx）缺失都会让整个 app 起不来。
# 改为 try/except + importlib，缺哪个 router 就降级（该功能不可用），其他照常工作。

def _include_router_safely(module_path: str, label: str) -> bool:
    """动态导入 router 模块并注册；缺包时降级（仅记录 warning，不影响 app 启动）

    注意：只有 ImportError（缺依赖）才降级。其他异常（NameError / 路由注册错误等
    代码 bug）直接向上抛出终止启动 —— 静默吞掉会让功能"无声消失"，比启动失败更难排障。
    """
    try:
        mod = importlib.import_module(module_path)
        app.include_router(mod.router)
        logger.info(f"  [OK]  {label:18s}  -> {module_path}")
        return True
    except ImportError as e:
        logger.warning(f"  [--]  {label:18s}  -> 缺失依赖: {e}（该功能不可用）")
        return False
    except Exception:
        logger.exception(f"  [ERR] {label:18s}  -> 加载失败（非缺依赖，属代码错误，终止启动）")
        raise


# health 是核心，必须加载（前面已删掉无用 import，现在它没有任何重依赖）
_include_router_safely("app.api.health", "health")

# 其他路由按需尝试加载
_include_router_safely("app.api.upload", "upload")           # 依赖 pymupdf / python-docx
_include_router_safely("app.api.analyze", "analyze")         # 依赖 openai
_include_router_safely("app.api.search", "search")           # 依赖 openai / httpx
_include_router_safely("app.api.compare_papers", "compare")  # 依赖 openai
_include_router_safely("app.api.ppt", "ppt")                 # 依赖 python-pptx
_include_router_safely("app.api.settings", "settings")       # 网页端供应商配置（仅依赖 pydantic）


@app.get("/")
async def root():
    """根路径"""
    return {
        "name": "PaperPilot API",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/api/health",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_debug,
        workers=settings.app_workers if not settings.app_debug else 1,
        log_level=settings.log_level.lower(),
    )
