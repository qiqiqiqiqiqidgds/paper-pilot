"""
请求上下文（Sprint 2 / I1）

用 contextvars 存当前请求的 request_id，让同一请求链路上的所有
`logger.info(...)` 自动带上 request_id 字段（通过 logging.Filter 注入）。

设计要点：
- 默认值 "-"：未走中间件时（如启动期日志、后台任务）不报错
- 用 contextvars 而非 threading.local：FastAPI 是 async 框架，
  contextvars 在 await 链上自动透传，threading.local 会丢
- 每次请求 set / 配对 reset，避免跨请求串味
"""
from __future__ import annotations

import contextvars
import uuid


# 默认 "-" 让非请求场景（启动期 / 后台任务 / 测试）也能正常打日志
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


def new_request_id() -> str:
    """生成一个新的 request_id（16 字节 hex，32 字符）"""
    return uuid.uuid4().hex


def get_request_id() -> str:
    """获取当前请求的 request_id；非请求场景返回 '-'"""
    return request_id_var.get()


def set_request_id(rid: str) -> contextvars.Token:
    """设置当前请求的 request_id，返回 token 用于后续 reset"""
    return request_id_var.set(rid)


def reset_request_id(token: contextvars.Token) -> None:
    """请求结束时 reset（与 set_request_id 配对）"""
    request_id_var.reset(token)
