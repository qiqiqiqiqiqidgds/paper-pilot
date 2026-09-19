"""
Request ID 中间件（Sprint 2 / I1）

每个 HTTP 请求：
1. 优先用客户端传入的 X-Request-ID（便于跨服务追踪），但必须是
   8-64 位字母数字/短横线/下划线 —— 否则重新生成。不校验的话，
   任意长度任意内容的字符串会进日志与响应头（日志膨胀 + request_id 伪造）
2. 缺则生成新的 uuid4 hex
3. 写入 contextvars，让本请求所有 logger 自动带上 request_id
4. 响应头回带 X-Request-ID（前端/反代可记录）

用 BaseHTTPMiddleware（FastAPI/Starlette 0.21+ 已修 contextvars 透传 bug）。
"""
import re

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.utils.request_context import (
    new_request_id,
    reset_request_id,
    set_request_id,
)

_REQUEST_ID_HEADER = "x-request-id"

# 客户端传入的 request_id 合法格式（与 new_request_id 的 uuid4 hex 输出兼容）
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9\-_]{8,64}$")


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 客户端可能传大写 X-Request-ID，starlette headers 是小写
        rid = request.headers.get(_REQUEST_ID_HEADER) or ""
        if not _REQUEST_ID_RE.fullmatch(rid):
            rid = new_request_id()
        token = set_request_id(rid)
        try:
            response: Response = await call_next(request)
        finally:
            reset_request_id(token)
        # 响应头回带，便于客户端排障时贴日志
        response.headers["X-Request-ID"] = rid
        return response
