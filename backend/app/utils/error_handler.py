"""
全局异常处理：统一响应格式 + 错误脱敏

策略：
- HTTPException：透传 status_code + detail
- RequestValidationError（Pydantic）：返回 422 + 友好错误
- 所有未捕获异常：记录详细日志 + 返回 500 通用消息（不泄露堆栈/路径）
- JSONDecodeError：返回 400
"""
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
import json as json_lib

from app.utils.logger import logger


def _safe_detail(detail, status_code: int) -> str:
    """对外返回的 detail 必须是 string，不能包含堆栈/路径"""
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        # Pydantic 422 detail 可能是 list
        return "; ".join(str(d) for d in detail)
    return str(detail)


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理"""

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        """FastAPI HTTPException → 统一 ApiResponse 格式"""
        # 429 Retry-After 透传
        headers = getattr(exc, "headers", None) or {}
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.status_code,
                "message": _safe_detail(exc.detail, exc.status_code),
                "data": None,
            },
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """Pydantic 校验失败 → 422 + 友好错误"""
        # 提取第一个错误的可读消息（不泄露内部路径）
        errors = exc.errors()
        first = errors[0] if errors else {}
        loc = ".".join(str(x) for x in first.get("loc", []))
        msg = first.get("msg", "请求参数校验失败")
        user_msg = f"{loc}: {msg}" if loc else msg
        if len(errors) > 1:
            user_msg += f"（还有 {len(errors) - 1} 个错误）"

        logger.warning(f"参数校验失败: path={request.url.path}, errors={len(errors)}")
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "code": 422,
                "message": user_msg,
                "data": None,
            },
        )

    @app.exception_handler(json_lib.JSONDecodeError)
    async def json_decode_handler(request: Request, exc: json_lib.JSONDecodeError):
        return JSONResponse(
            status_code=400,
            content={
                "code": 400,
                "message": f"JSON 解析失败（行 {exc.lineno} 列 {exc.colno}）",
                "data": None,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        """兜底：未捕获异常 → 详细 log + 通用 500"""
        logger.exception(
            f"未捕获异常: path={request.url.path}, method={request.method}, "
            f"type={type(exc).__name__}: {exc}"
        )
        # 内部异常详情只在显式开启 APP_DEBUG 时回显（便于本地排障）。
        # 不再绑 APP_ENV=dev —— dev 是默认值，"忘了设 APP_ENV" 的部署不该因此
        # 向任意客户端泄露内部路径 / 上游报错（B15 精化）
        from app.config import settings
        msg = (
            f"{type(exc).__name__}: {exc}"
            if settings.app_debug
            else "服务器内部错误"
        )
        return JSONResponse(
            status_code=500,
            content={
                "code": 500,
                "message": msg,
                "data": None,
            },
        )