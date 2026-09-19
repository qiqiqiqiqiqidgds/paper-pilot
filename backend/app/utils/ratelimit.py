"""
限流中间件

策略：
- 按 (IP, bucket) 区分时间戳队列
- 通用接口（如 /api/papers）：60/min
- 昂贵接口（/api/analyze, /api/generate-ppt, /api/compare*, /api/search-related, /api/upload）：10/min
- 滑动窗口（保留最近 60s 内的请求时间戳），内存存储，time.monotonic 计时（不受系统改时间影响）
- 超限返回 429 + Retry-After header

⚠️  重要部署约束：
   本限流基于进程内内存字典实现。
   - 多 worker 部署（gunicorn -w N / uvicorn --workers N）时，**每个 worker 独立计数**，
     实际限流上限 = 配置值 × N。例如 -w 4 时，60/min 实际可达 240/min。
   - 生产部署必须满足以下任一条件：
     (a) 单 worker 部署（uvicorn --workers 1 / gunicorn -w 1），推荐并发用 --worker-class gevent；
     (b) 在 Nginx / 反代层做限流；
     (c) 改造为 Redis 后端（后续 Sprint 计划）。
   - 单进程开发（uvicorn 启动）下行为正确。

P1-14: XFF 仅在 trusted_hosts 中配置的反代 IP 下才信任（避免客户端伪造）
P1-16: 定期清理空桶（无新请求 5 分钟以上的桶直接删除，防止内存增长）
P3-4: IPv6 地址按 /64 前缀归一化为桶键（IPv6 客户端可在同一 /64 内
      无限换后缀地址绕过按完整 IP 限额；IPv4-mapped IPv6 还原为 IPv4）
"""
import ipaddress
import time
from collections import defaultdict, deque
from threading import Lock
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.utils.logger import logger
from app.utils.proxy import client_ip, public_paths


# 桶清理间隔（秒）：每隔该时间扫描一次过期桶
CLEANUP_INTERVAL_SECONDS = 300  # 5 分钟
# 桶空闲阈值（秒）：该时间无新请求就视为空
BUCKET_IDLE_SECONDS = 300  # 5 分钟


def _is_expensive(path: str) -> bool:
    """判断是否为昂贵接口（消耗 LLM / 外部 API / 大文件上传解析）"""
    expensive_prefixes = (
        "/api/analyze",
        "/api/generate-ppt",
        "/api/compare",
        "/api/search-related",
        "/api/upload",   # B17: 上传涉及解析（PDF/DOCX）+ 落盘，同样昂贵
        "/api/settings/test",  # 连接测试会打真实 LLM / 搜索 API
    )
    return any(path.startswith(p) for p in expensive_prefixes)


def _bucket_ip(ip: str) -> str:
    """P3-4: 归一化限流桶键中的 IP（只影响计费键，日志仍记录原始 ip）

    - IPv4-mapped IPv6（::ffff:a.b.c.d）→ 还原为 IPv4 字符串，
      使 mapped 与非 mapped 形式共享同一个桶；
    - 其余 IPv6 → /64 网络前缀（同一子网内所有地址共享一个桶，
      防止在 /64 内换后缀地址绕过按 IP 限额；运营商也按 /64 分配终端子网）；
    - IPv4 / 解析失败的输入（主机名、"unknown" 等）→ 原样返回，行为不变。
    """
    try:
        addr = ipaddress.ip_address(ip.strip())
    except ValueError:
        return ip
    if addr.version != 6:
        return ip
    mapped = addr.ipv4_mapped
    if mapped is not None:
        return str(mapped)
    return str(ipaddress.ip_network(f"{addr}/64", strict=False).network_address)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """滑动窗口限流（按 IP + bucket，保留最近 60s 的请求时间戳队列）"""

    # 桶：key=(ip, bucket_name) -> deque of monotonic timestamps
    _buckets: dict = defaultdict(deque)
    # 上次清理时间（用于按需触发清理；monotonic 时钟）
    _last_cleanup: float = 0.0
    _lock = Lock()
    WINDOW_SECONDS = 60.0

    def _cleanup_idle_buckets(self) -> int:
        """清理超过 BUCKET_IDLE_SECONDS 未活跃的空桶（P1-16）"""
        now = time.monotonic()
        idle_threshold = now - BUCKET_IDLE_SECONDS
        removed = 0
        keys_to_remove = []
        for key, dq in self._buckets.items():
            if not dq:
                keys_to_remove.append(key)
                continue
            # 最新一条（dq[-1]）也超过 idle 阈值，说明整个桶都已过期
            # （时间戳按入队顺序单调递增，最新过期 ⇒ 全部过期）
            if dq[-1] < idle_threshold:
                keys_to_remove.append(key)
        for key in keys_to_remove:
            del self._buckets[key]
            removed += 1
        if removed:
            logger.info(f"限流桶清理: 移除 {removed} 个空闲桶, 剩余 {len(self._buckets)}")
        return removed

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # 公开路径不限流（与鉴权中间件同一集合，见 utils/proxy.py）
        if path in public_paths():
            return await call_next(request)

        # 只对 /api/* 限流
        if not path.startswith("/api/"):
            return await call_next(request)

        ip = client_ip(request)
        bucket = "expensive" if _is_expensive(path) else "general"
        limit = (
            settings.rate_limit_expensive_per_min
            if bucket == "expensive"
            else settings.rate_limit_general_per_min
        )
        # P3-4: 桶键用归一化后的 IP（IPv6 聚合到 /64；IPv4 不变），防 /64 内绕过
        key = (_bucket_ip(ip), bucket)

        now = time.monotonic()
        window_start = now - self.WINDOW_SECONDS

        with self._lock:
            # P1-16: 定期清理空闲桶（每 ~5 分钟一次）
            if now - self._last_cleanup > CLEANUP_INTERVAL_SECONDS:
                self._cleanup_idle_buckets()
                self._last_cleanup = now

            bucket_deque = self._buckets[key]
            # 弹出过期时间戳
            while bucket_deque and bucket_deque[0] <= window_start:
                bucket_deque.popleft()

            if len(bucket_deque) >= limit:
                # 计算 Retry-After（最早一条过期还需多少秒）
                retry_after = max(1, int(bucket_deque[0] + self.WINDOW_SECONDS - now) + 1)
                logger.warning(
                    f"限流触发: ip={ip}, bucket={bucket}, path={path}, "
                    f"count={len(bucket_deque)}/{limit}, retry_after={retry_after}s"
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "code": 429,
                        "message": f"请求过于频繁（{bucket} 接口 {limit}/min），请在 {retry_after} 秒后重试",
                        "data": None,
                    },
                    headers={"Retry-After": str(retry_after)},
                )

            # 通过，记录本次时间戳
            bucket_deque.append(now)

        return await call_next(request)
