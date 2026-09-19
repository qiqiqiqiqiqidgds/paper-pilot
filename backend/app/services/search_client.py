"""
联网搜索客户端

- TavilyClient：通用网页搜索（需 TAVILY_API_KEY）
- ArxivClient：arXiv 学术搜索（免费无需 key，项目默认方案，SEARCH_PROVIDER=arxiv）
两个客户端实现同一接口 search_related_papers(title, abstract, max_results)，
统一入口 get_search_client() 按 settings.search_provider 选择。

P1-6/7/8/9 修复（Tavily）：
- 复用 httpx.AsyncClient 连接池（P1-7）
- 指数退避重试（429/5xx/Timeout，P1-6）
- API Key 改 Bearer Header（P1-9，避免被请求体日志泄露）
- 超时分级：basic=20s，advanced=60s（P1-8，从配置可覆盖）
"""
import asyncio
import re
import time
from typing import List, Dict, Any, Optional

import defusedxml.ElementTree as ET  # P2-5: 替换标准库 xml.etree（见下）
import httpx

from app.config import settings
from app.services.runtime_settings import SearchConnConfig, runtime_settings
from app.utils.logger import logger

# 重试参数
RETRY_MAX_ATTEMPTS = 3
RETRY_BACKOFF_BASE = 1.0   # 1s
RETRY_BACKOFF_FACTOR = 2.0  # 2^n
# 哪些状态码重试（429/5xx）；其他 4xx 直接抛
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# arXiv 礼貌使用政策：请求间隔（秒）
ARXIV_REQUEST_INTERVAL = 3.0

# 英文停用词（关键词提取用）
_STOPWORDS = {
    "a", "an", "the", "of", "on", "for", "with", "via", "using", "based", "in",
    "to", "and", "or", "at", "by", "from", "into", "toward", "towards", "we",
    "our", "this", "that", "these", "those", "it", "is", "are", "was", "were",
    "have", "has", "had", "be", "been", "not", "but", "as", "than", "over",
    "under", "new", "novel", "propose", "proposed", "proposing", "approach",
    "method", "methods", "model", "models", "paper", "study", "studies",
    "results", "result", "performance", "improve", "improved", "improving",
    "first", "also", "their", "them", "they", "its", "his", "her", "between",
}


class SearchError(Exception):
    """
    搜索调用失败（区别于业务上的"无结果"）。

    当 Tavily 调用真正失败（超时/网络/HTTP 5xx 重试耗尽）时抛出，
    由上层 API 捕获后返回 502 固定文案；key 未配置 / 无结果是业务正常，
    不抛此异常。
    """


def _is_retryable(exc: httpx.HTTPError) -> bool:
    """判断异常是否值得重试"""
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_STATUS_CODES
    if isinstance(exc, httpx.NetworkError):
        return True
    return False


class TavilyClient:
    """Tavily 搜索客户端（专为 AI 设计）"""

    def __init__(self, config: Optional[SearchConnConfig] = None):
        if config is None:
            config = runtime_settings.effective_search()
        self.api_key = config.tavily_api_key
        self.base_url = config.tavily_base_url
        # P1-7: 复用连接池（进程内单例）
        self._http: Optional[httpx.AsyncClient] = None
        if self.api_key:
            logger.info("Tavily 客户端初始化成功")
        else:
            logger.warning("TAVILY_API_KEY 未配置，联网搜索将不可用")

    @property
    def is_configured(self) -> bool:
        """Tavily 需要 key 才可用"""
        return bool(self.api_key)

    def _get_client(self) -> httpx.AsyncClient:
        """懒初始化共享的 AsyncClient"""
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                timeout=settings.tavily_timeout_seconds,
                limits=httpx.Limits(
                    max_connections=10,
                    max_keepalive_connections=5,
                ),
            )
        return self._http

    async def aclose(self) -> None:
        """关闭连接池（应用关闭时调用）"""
        if self._http and not self._http.is_closed:
            await self._http.aclose()
            self._http = None

    async def _do_search_with_retry(
        self,
        payload: Dict[str, Any],
        timeout: float,
    ) -> Dict[str, Any]:
        """
        带指数退避的重试（P1-6）
        4xx（非 429）直接抛；429/5xx/Timeout/NetworkError 重试
        """
        last_exc: Optional[Exception] = None
        for attempt in range(1, RETRY_MAX_ATTEMPTS + 1):
            try:
                client = self._get_client()
                # P1-9: API Key 通过 Bearer Header 传递
                headers = {"Authorization": f"Bearer {self.api_key}"}
                response = await client.post(
                    f"{self.base_url}/search",
                    json=payload,
                    headers=headers,
                    timeout=timeout,
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as e:
                last_exc = e
                if not _is_retryable(e):
                    logger.error(f"Tavily 搜索失败（不可重试）: {e}")
                    raise
                if attempt >= RETRY_MAX_ATTEMPTS:
                    logger.error(f"Tavily 搜索失败（重试 {attempt-1} 次后放弃）: {e}")
                    raise
                backoff = RETRY_BACKOFF_BASE * (RETRY_BACKOFF_FACTOR ** (attempt - 1))
                logger.warning(
                    f"Tavily 搜索失败，{backoff:.1f}s 后重试 "
                    f"（{attempt}/{RETRY_MAX_ATTEMPTS}）: {type(e).__name__}"
                )
                await asyncio.sleep(backoff)
        # 不会到这里
        raise last_exc if last_exc else RuntimeError("Unknown error")

    async def search(
        self,
        query: str,
        max_results: int = 5,
        search_depth: str = "advanced",
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        执行搜索

        :param query: 搜索关键词
        :param max_results: 返回数量
        :param search_depth: basic / advanced（advanced 更慢但更准）
        :param include_domains: 限定域名（如 ["arxiv.org"]）
        :param exclude_domains: 排除域名
        :return: 搜索结果列表
        """
        if not self.api_key:
            raise ValueError("TAVILY_API_KEY 未配置")

        payload = {
            "query": query,
            "max_results": max_results,
            "search_depth": search_depth,
        }
        if include_domains:
            payload["include_domains"] = include_domains
        if exclude_domains:
            payload["exclude_domains"] = exclude_domains

        # P1-8: 超时分级
        if search_depth == "basic":
            timeout = min(20.0, settings.tavily_timeout_seconds)
        else:
            timeout = settings.tavily_timeout_seconds

        try:
            data = await self._do_search_with_retry(payload, timeout=timeout)
            return data.get("results", [])
        except httpx.HTTPError as e:
            logger.error(f"Tavily 搜索失败: {e}")
            raise

    async def search_related_papers(
        self,
        title: str,
        abstract: str = "",
        max_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        搜索与某论文相关的工作

        策略：用论文标题 + 关键词搜索 arxiv、ACL、IEEE、ACM 等学术源
        """
        if not self.api_key:
            return []

        # 构造查询：用论文标题，找相关工作
        # 简单策略：标题 + "related work"
        query = f"{title} related work survey"

        try:
            results = await self.search(
                query=query,
                max_results=max_results,
                search_depth="advanced",
                include_domains=[
                    "arxiv.org",
                    "aclanthology.org",
                    "ieee.org",
                    "acm.org",
                    "openreview.net",
                    "papers.nips.cc",
                    "proceedings.mlr.press",
                    "jmlr.org",
                ],
            )
        except Exception as e:
            # P1-修复：真正的调用失败（超时/网络/5xx）必须抛给上层，
            # 不能再吞成空结果（否则 search.py 的 except 全是死代码，用户只看到"未搜到"）。
            logger.error(f"搜索相关工作调用失败: {e}")
            raise SearchError(f"搜索相关工作调用失败: {e}") from e

        # 格式化结果
        formatted = []
        for r in results:
            formatted.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", "")[:1000],  # 限制长度
                "score": r.get("score", 0),
            })
        return formatted


# 单例（按当前生效配置缓存：网页端改配置后指纹变化，自动重建）
_client: Optional[TavilyClient] = None
_client_fingerprint: Optional[tuple] = None


def get_tavily_client() -> TavilyClient:
    global _client, _client_fingerprint
    config = runtime_settings.effective_search()
    fingerprint = config.fingerprint()
    if _client is None or fingerprint != _client_fingerprint:
        old = _client
        _client = TavilyClient(config)
        _client_fingerprint = fingerprint
        if old is not None:
            _schedule_aclose(old)
    return _client


def _schedule_aclose(client: TavilyClient) -> None:
    """异步关闭被替换客户端的连接池（仅在事件循环内可调度时）"""
    try:
        asyncio.get_running_loop().create_task(client.aclose())
    except RuntimeError:
        # 无运行中的事件循环（同步上下文）：放弃优雅关闭，进程退出时由 OS 回收
        pass


# ============== ArxivClient ==============

_ARXIV_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


def _extract_keywords(title: str, abstract: str = "", max_keywords: int = 5) -> List[str]:
    """
    从标题+摘要中提取英文关键词（去停用词），用于构建 arXiv 查询。
    标题优先；不足再从摘要补。
    """
    seen: List[str] = []
    text = title or ""
    for raw in re.findall(r"[A-Za-z][A-Za-z0-9\-]{1,40}", text):
        w = raw.lower()
        if w in _STOPWORDS or len(w) < 3:
            continue
        if w not in seen:
            seen.append(w)
        if len(seen) >= max_keywords:
            break
    if len(seen) < max_keywords and abstract:
        for raw in re.findall(r"[A-Za-z][A-Za-z0-9\-]{1,40}", abstract):
            w = raw.lower()
            if w in _STOPWORDS or len(w) < 3:
                continue
            if w not in seen:
                seen.append(w)
            if len(seen) >= max_keywords:
                break
    return seen


class ArxivClient:
    """
    arXiv 学术搜索客户端（免费、无需 API Key）

    返回结构与 TavilyClient.search_related_papers 一致：
    [{title, url, content, score}]，score 为基于排序的伪分数（arXiv 不提供）。
    """

    def __init__(self):
        self.base_url = "https://export.arxiv.org/api/query"
        self._http: Optional[httpx.AsyncClient] = None
        self._last_request_at = 0.0
        # B16: 限速时间戳读写的并发保护（检查间隔-sleep-更新时间戳必须原子）
        self._arxiv_lock = asyncio.Lock()
        logger.info("Arxiv 搜索客户端初始化成功（免费无需 key）")

    @property
    def is_configured(self) -> bool:
        """arXiv 无需 key，始终可用"""
        return True

    def _get_client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            # BUG-2b: 实测后端到 export.arxiv.org 偶发 ConnectError
            # （"All connection attempts failed"，同机 curl 可达）。
            # ① 超时分级：连接阶段单独给 10s（TCP 握手偶发变慢），读写沿用
            #    tavily_timeout_seconds；② transport 层对"连接建立失败"做 2 次
            #    立即重试（仅作用于连接阶段，不会放大业务请求次数）。
            _limits = httpx.Limits(
                max_connections=10,
                max_keepalive_connections=5,
            )
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(settings.tavily_timeout_seconds, connect=10.0),
                limits=_limits,
                transport=httpx.AsyncHTTPTransport(retries=2, limits=_limits),
                headers={
                    "User-Agent": "PaperPilot/0.1 (AI paper reading assistant)",
                    "Accept": "application/atom+xml, application/xml",
                },
            )
        return self._http

    async def aclose(self) -> None:
        if self._http and not self._http.is_closed:
            await self._http.aclose()
            self._http = None

    async def _rate_limited_request(self, params: Dict[str, Any]) -> bytes:
        """带礼貌限速（arXiv 要求请求间隔）和重试的 GET"""
        last_exc: Optional[Exception] = None
        for attempt in range(1, RETRY_MAX_ATTEMPTS + 1):
            # B16: 每次尝试（含重试）都先进入限速临界区，保证"检查间隔-sleep-
            # 更新时间戳"原子执行；HTTP 请求本身不锁在临界区内
            async with self._arxiv_lock:
                # arXiv 礼貌使用政策：两次请求至少间隔 3 秒
                since = time.monotonic() - self._last_request_at
                if since < ARXIV_REQUEST_INTERVAL:
                    await asyncio.sleep(ARXIV_REQUEST_INTERVAL - since)
                self._last_request_at = time.monotonic()

            try:
                client = self._get_client()
                response = await client.get(self.base_url, params=params)
                response.raise_for_status()
                return response.content
            except httpx.HTTPError as e:
                last_exc = e
                if not _is_retryable(e):
                    logger.error(f"Arxiv 搜索失败（不可重试）: {e}")
                    raise
                if attempt >= RETRY_MAX_ATTEMPTS:
                    logger.error(f"Arxiv 搜索失败（重试 {attempt-1} 次后放弃）: {e}")
                    raise
                backoff = RETRY_BACKOFF_BASE * (RETRY_BACKOFF_FACTOR ** (attempt - 1))
                logger.warning(
                    f"Arxiv 搜索失败，{backoff:.1f}s 后重试 "
                    f"（{attempt}/{RETRY_MAX_ATTEMPTS}）: {type(e).__name__}"
                )
                await asyncio.sleep(backoff)
        raise last_exc if last_exc else RuntimeError("Unknown error")

    @staticmethod
    def _parse_feed(xml_bytes: bytes) -> List[Dict[str, Any]]:
        """解析 arXiv Atom feed，返回 [{title, url, content, published, authors}]

        P2-5: 按 Python 官方 XML 漏洞矩阵建议改用 defusedxml 解析（模块级别名
        `as ET`，fromstring 之外未再直接使用 ElementTree 其他符号）。arXiv 为
        固定可信源 + HTTPS，风险低，但标准库 ElementTree 不防实体展开 / 外部
        实体注入，defusedxml 提供零成本防御纵深。
        """
        root = ET.fromstring(xml_bytes)
        items: List[Dict[str, Any]] = []
        for entry in root.findall("atom:entry", _ARXIV_ATOM_NS):
            title_el = entry.find("atom:title", _ARXIV_ATOM_NS)
            id_el = entry.find("atom:id", _ARXIV_ATOM_NS)
            summary_el = entry.find("atom:summary", _ARXIV_ATOM_NS)
            published_el = entry.find("atom:published", _ARXIV_ATOM_NS)
            title = " ".join((title_el.text or "").split())
            url = (id_el.text or "").strip() if id_el is not None else ""
            summary = " ".join((summary_el.text or "").split())
            if not title:
                continue
            items.append({
                "title": title,
                "url": url,
                "content": summary,
                "published": (published_el.text or "").strip() if published_el is not None else "",
            })
        return items

    async def search_related_papers(
        self,
        title: str,
        abstract: str = "",
        max_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        用论文标题关键词搜索 arXiv 相关工作（免费，无需 key）

        策略：标题关键词提取 → 前 3 词 AND 查询；
        结果不足 2 条时放宽为前 2 词 AND 再搜一次（合并去重）。
        返回结构与 Tavily 版一致。
        """
        keywords = _extract_keywords(title, abstract)
        if not keywords:
            logger.warning("无法从论文提取关键词，arXiv 搜索跳过")
            return []

        try:
            # 第一轮：前 3 个关键词 AND（相关度最高）
            top = keywords[:3]
            query = " AND ".join(f"abs:{kw}" for kw in top)
            entries = await self._query(query, max_results)

            # 结果不足时放宽：前 2 词 AND
            if len(entries) < 2 and len(keywords) >= 2:
                relaxed = keywords[:2]
                query2 = " AND ".join(f"abs:{kw}" for kw in relaxed)
                relaxed_entries = await self._query(query2, max_results)
                seen_urls = {e["url"] for e in entries}
                for e in relaxed_entries:
                    if e["url"] not in seen_urls:
                        entries.append(e)
        except Exception as e:
            logger.error(f"arXiv 搜索调用失败: {e}")
            raise SearchError(f"arXiv 搜索调用失败: {e}") from e

        # 过滤与主论文同标题的结果 + 限制数量 + 生成伪 score（按相关度排序递减）
        main_title_norm = re.sub(r"\W+", "", title).lower()
        formatted: List[Dict[str, Any]] = []
        for rank, e in enumerate(entries[:max_results]):
            if re.sub(r"\W+", "", e["title"]).lower() == main_title_norm:
                continue
            formatted.append({
                "title": e["title"],
                "url": e["url"],
                "content": e["content"][:1000],  # 限制长度
                "score": max(0.0, 1.0 - rank * 0.1),
            })
        return formatted

    async def _query(self, search_query: str, max_results: int) -> List[Dict[str, Any]]:
        params = {
            "search_query": search_query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        content = await self._rate_limited_request(params)
        return self._parse_feed(content)


# ============== 统一入口 ==============

_arxiv_client: Optional[ArxivClient] = None


def get_search_client():
    """
    按当前生效搜索供应商（.env + 网页端设置合并）返回搜索客户端
    （TavilyClient 或 ArxivClient，接口一致：is_configured / search_related_papers / aclose）
    """
    provider = runtime_settings.effective_search().provider
    if provider == "tavily":
        return get_tavily_client()
    global _arxiv_client
    if _arxiv_client is None:
        _arxiv_client = ArxivClient()
    return _arxiv_client


def get_created_search_client():
    """P3-8: 仅当搜索客户端单例已被创建时返回它，否则返回 None。

    供应用关闭逻辑使用：旧实现关闭时无条件调 get_search_client().aclose()，
    若进程生命周期内从未用过联网搜索，会"先实例化一个客户端再关闭它"——
    既多做了一次无谓初始化，也让关闭路径意外依赖配置合法性。
    """
    if settings.search_provider == "tavily":
        return _client
    return _arxiv_client
