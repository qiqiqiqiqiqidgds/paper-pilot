"""
API Key 鉴权中间件

策略：
- 设置 APP_API_KEY 后启用鉴权
- 所有 /api/* 路径需要带 X-API-Key header
- 公开路径（/api/health 等，见 utils/proxy.public_paths）放行；生产环境不放行 /docs 等 schema 页
- 鉴权失败返回 401，结构与项目 ApiResponse 一致

P1-14: 仅信任来自 trusted_hosts 配置的 X-Forwarded-For 头；
       来自其他源的 XFF 一律忽略，防止客户端伪造 IP 绕过限流。
       （XFF 信任逻辑与 ratelimit 共用 utils/proxy.py，改动需同步的地方只有一处）

注意：本地开发留空 APP_API_KEY 即可，不影响现有功能。
"""
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.utils.logger import logger
from app.utils.proxy import client_ip, public_paths


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    """X-API-Key 鉴权"""

    async def dispatch(self, request: Request, call_next):
        # 鉴权未启用 → 直接放行（开发模式）
        if not settings.auth_enabled:
            return await call_next(request)

        path = request.url.path

        # 公开路径放行
        if path in public_paths():
            return await call_next(request)

        # 只保护 /api/* 业务路径
        if not path.startswith("/api/"):
            return await call_next(request)

        # 取 header（大小写不敏感，HTTP/1.1 不区分但客户端可能大小写混用）
        api_key = (
            request.headers.get("X-API-Key")
            or request.headers.get("x-api-key")
        )

        # 用 secrets.compare_digest 防时序攻击
        # B8: 两侧先编码为 utf-8 bytes 再比较 —— str 版 compare_digest 遇非 ASCII 抛 TypeError，
        # bytes 版支持任意 bytes；expected 为空时保持 401 行为
        import secrets
        expected = settings.app_api_key
        if (
            not api_key
            or not expected
            or not secrets.compare_digest(
                api_key.encode("utf-8"), expected.encode("utf-8")
            )
        ):
            client_ip_ = client_ip(request)
            logger.warning(
                f"鉴权失败: ip={client_ip_}, path={path}, "
                f"key={'<missing>' if not api_key else '<invalid>'}"
            )
            return JSONResponse(
                status_code=401,
                content={
                    "code": 401,
                    "message": "未授权：缺少或无效的 API Key（需在请求头加 X-API-Key）",
                    "data": None,
                },
            )

        return await call_next(request)
