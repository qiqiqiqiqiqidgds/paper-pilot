"""
HTTP 请求公共工具：公开路径集合、可信代理判定、客户端 IP 提取

auth.py（鉴权中间件）与 ratelimit.py（限流中间件）此前各持有一份
几乎相同的实现（连注释都一样），改动 XFF 信任逻辑必须双改、极易漂移。
抽到这里统一维护，两个中间件共用。
"""
from fastapi import Request

from app.config import settings
from app.utils.logger import logger


def public_paths() -> set:
    """无需鉴权/限流的路径（精确匹配）。

    /docs /redoc /openapi.json 会暴露完整 API schema，仅在非生产环境放行；
    /api/health 供探活，始终公开。
    """
    paths = {"/", "/api/health"}
    if not settings.is_production:
        paths |= {"/docs", "/redoc", "/openapi.json"}
    return paths


def is_trusted_proxy(host: str) -> bool:
    """判断对端 host 是否在 trusted_hosts 白名单中（P1-14）"""
    if not host:
        return False
    trusted_list = settings.trusted_hosts_list
    if host in trusted_list:
        return True
    if host == "localhost":
        return "localhost" in trusted_list
    return False


def client_ip(request: Request) -> str:
    """取客户端 IP：仅在 trusted proxy 下才信任 X-Forwarded-For（P1-14）

    来自非信任对端的 XFF 一律忽略 —— 防止客户端伪造 IP 绕过按 IP 限流。

    信任 XFF 时从右往左取第一个"非可信主机"的 IP：
    XFF 的语义是每经过一层代理向右侧追加一段，最左端是客户端可任意伪造的值。
    旧实现取最左段，等于信任客户端自报 IP——反代为追加模式
    （nginx 默认 proxy_add_x_forwarded_for）时，攻击者每次带不同伪造头
    即可绕过按 IP 限流。从右往左跳过链上的可信代理，第一个非可信 IP
    才是可信代理亲眼所见的真实客户端。
    """
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        peer_host = request.client.host if request.client else ""
        if is_trusted_proxy(peer_host):
            parts = [p.strip() for p in xff.split(",") if p.strip()]
            for part in reversed(parts):
                if not is_trusted_proxy(part):
                    return part
            # 整条链都在可信列表（极端配置）→ 退回最左段，至少不误伤正常请求
            if parts:
                return parts[0]
        else:
            logger.debug(f"忽略未信任的 XFF（peer={peer_host}, xff={xff[:80]}）")
    return request.client.host if request.client else "unknown"
