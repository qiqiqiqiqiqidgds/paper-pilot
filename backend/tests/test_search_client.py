"""
搜索客户端单元测试（重试/退避/Bearer/arxiv，全部 mock httpx，不打外网）

覆盖 CHANGELOG 宣称的 P1-6/7/9（Tavily 重试 + 连接池 + Bearer Header）与
arxiv provider（此前均无直接测试）。
"""
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import httpx

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.services.search_client as sc
from app.config import settings


@pytest.fixture(autouse=True)
def _fast_retry():
    """把所有重试退避 sleep 替换为立即返回（测试不想等 1s+2s）"""
    with patch.object(sc.asyncio, "sleep", new=AsyncMock()):
        yield


# ============== _is_retryable ==============

def test_is_retryable_timeout():
    exc = httpx.ConnectTimeout("timeout")
    assert sc._is_retryable(exc) is True


def test_is_retryable_5xx():
    req = httpx.Request("GET", "http://x")
    for code in (500, 502, 503, 504, 429):
        exc = httpx.HTTPStatusError("err", request=req, response=httpx.Response(code))
        assert sc._is_retryable(exc) is True, f"{code} 应可重试"


def test_is_retryable_4xx():
    req = httpx.Request("GET", "http://x")
    exc = httpx.HTTPStatusError("err", request=req, response=httpx.Response(404))
    assert sc._is_retryable(exc) is False


# ============== TavilyClient ==============

class TestTavilyRetry:
    def _client(self):
        c = sc.TavilyClient()
        c.api_key = "tvly-test-key"
        return c

    @pytest.mark.asyncio
    async def test_retry_then_success(self):
        """429 → 503 → 成功：共 3 次调用，返回结果"""
        c = self._client()
        req = httpx.Request("POST", "http://tavily/search")

        async def fake_post(url, json=None, headers=None, timeout=None):
            nonlocal c
            attempts = getattr(fake_post, "n", 0)
            fake_post.n = attempts + 1
            if attempts < 2:
                code = [429, 503][attempts]
                raise httpx.HTTPStatusError("err", request=req, response=httpx.Response(code, request=req))
            return httpx.Response(200, json={"results": [{"title": "T", "url": "u", "score": 0.9}]}, request=req)

        with patch.object(c, "_get_client") as get_client:
            get_client.return_value.post = fake_post
            results = await c.search("test query")
        assert results == [{"title": "T", "url": "u", "score": 0.9}]
        assert fake_post.n == 3, f"应重试 2 次共 3 次调用，实际 {fake_post.n}"

    @pytest.mark.asyncio
    async def test_give_up_after_retries(self):
        """持续 5xx：重试耗尽后抛 HTTPStatusError"""
        c = self._client()
        req = httpx.Request("POST", "http://tavily/search")

        async def always_fail(url, json=None, headers=None, timeout=None):
            raise httpx.HTTPStatusError("err", request=req, response=httpx.Response(503, request=req))

        with patch.object(c, "_get_client") as get_client:
            get_client.return_value.post = always_fail
            with pytest.raises(httpx.HTTPStatusError):
                await c.search("test query")

    @pytest.mark.asyncio
    async def test_non_retryable_raises_immediately(self):
        """404（非重试码）不重试，直接抛"""
        c = self._client()
        req = httpx.Request("POST", "http://tavily/search")
        calls = {"n": 0}

        async def fail_404(url, json=None, headers=None, timeout=None):
            calls["n"] += 1
            raise httpx.HTTPStatusError("err", request=req, response=httpx.Response(404, request=req))

        with patch.object(c, "_get_client") as get_client:
            get_client.return_value.post = fail_404
            with pytest.raises(httpx.HTTPStatusError):
                await c.search("test query")
        assert calls["n"] == 1, "非重试码不应重试"

    @pytest.mark.asyncio
    async def test_bearer_header(self):
        """P1-9：API Key 必须通过 Bearer Header 传递（不能进 body）"""
        c = self._client()
        captured = {}
        req = httpx.Request("POST", "http://tavily/search")

        async def fake_post(url, json=None, headers=None, timeout=None):
            captured.update({"url": url, "json": json, "headers": headers})
            return httpx.Response(200, json={"results": []}, request=req)

        with patch.object(c, "_get_client") as get_client:
            get_client.return_value.post = fake_post
            await c.search("q")
        assert captured["headers"]["Authorization"] == "Bearer tvly-test-key"
        # body 里不应出现 key
        assert "tvly-test-key" not in str(captured["json"])

    @pytest.mark.asyncio
    async def test_search_related_returns_empty_when_not_configured(self):
        """未配置 key：search_related_papers 返回空（业务正常，不抛）"""
        c = self._client()
        c.api_key = ""
        assert c.is_configured is False
        assert await c.search_related_papers("title") == []


# ============== ArxivClient ==============

SAMPLE_ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1810.04805v2</id>
    <title>   BERT: Pre-training of Deep Bidirectional Transformers   </title>
    <published>2018-10-11T00:00:00Z</published>
    <summary>  We introduce a new language representation model called BERT.  </summary>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2005.14165v4</id>
    <title>Language Models are Few-Shot Learners</title>
    <published>2020-05-28T00:00:00Z</published>
    <summary>Recent work has demonstrated substantial gains.</summary>
  </entry>
</feed>"""


def test_extract_keywords_basic():
    kws = sc._extract_keywords("Attention Is All You Need and Transformers", "with abstract text")
    assert kws, "应提取出关键词"
    assert all(w not in sc._STOPWORDS for w in kws)


def test_parse_feed():
    entries = sc.ArxivClient._parse_feed(SAMPLE_ATOM)
    assert len(entries) == 2
    assert entries[0]["title"] == "BERT: Pre-training of Deep Bidirectional Transformers"  # 空白已归一
    assert entries[0]["url"] == "http://arxiv.org/abs/1810.04805v2"
    assert entries[1]["published"] == "2020-05-28T00:00:00Z"


def test_parse_feed_rejects_entity_expansion():
    """P2-5 回归：_parse_feed 已改用 defusedxml，实体展开（billion laughs 类）
    在解析阶段即被拒绝，而不是被标准库 ElementTree 静默展开"""
    from defusedxml.common import EntitiesForbidden

    evil = (
        b'<?xml version="1.0"?>\n'
        b'<!DOCTYPE feed [\n'
        b'  <!ENTITY a "AAAAAAAAAA">\n'
        b'  <!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">\n'
        b']>\n'
        b'<feed xmlns="http://www.w3.org/2005/Atom">'
        b"<entry><title>&b;</title></entry></feed>"
    )
    with pytest.raises(EntitiesForbidden):
        sc.ArxivClient._parse_feed(evil)


def test_search_client_no_stdlib_etree():
    """P2-5：search_client 模块不得再引用标准库 xml.etree（固定可信源也走 defusedxml）"""
    import xml.etree.ElementTree as stdlib_et

    assert not hasattr(sc, "ET") or sc.ET is not stdlib_et, (
        "search_client.ET 应为 defusedxml.ElementTree，而非标准库 xml.etree"
    )


@pytest.mark.asyncio
async def test_arxiv_search_dedup_and_self_filter():
    """放宽搜索合并去重 + 过滤同名论文 + 伪 score 递减"""
    c = sc.ArxivClient()
    c._last_request_at = time.monotonic() - 10  # 跳过礼貌限速等待
    urls = ["http://arxiv.org/abs/1", "http://arxiv.org/abs/2", "http://arxiv.org/abs/3"]

    state = {"n": 0}

    async def fake_query(query, max_results):
        state["n"] += 1
        if state["n"] == 1:
            # 第一轮：只有 1 条且与主论文同名（触发放宽搜索 + 最终被过滤）
            return [
                {"title": "Attention Is All You Need", "url": urls[0], "content": "same"},
            ]
        return [
            {"title": "Related Work A", "url": urls[1], "content": "content A"},
            {"title": "Relaxed B", "url": urls[2], "content": "content B"},
        ]

    with patch.object(c, "_query", new=AsyncMock(side_effect=fake_query)):
        results = await c.search_related_papers("Attention Is All You Need", max_results=5)

    # 放宽搜索被触发（共 2 次查询）
    assert state["n"] == 2, "结果不足时应触发放宽搜索"
    # 同名论文被过滤，放宽结果被合并
    titles = [r["title"] for r in results]
    assert "Attention Is All You Need" not in titles
    assert set(titles) == {"Related Work A", "Relaxed B"}
    assert len(results) <= 5
    # score 递减
    assert results[0]["score"] > results[1]["score"]


def test_get_search_client_arxiv():
    """SEARCH_PROVIDER=arxiv 时返回 ArxivClient"""
    old = settings.search_provider
    try:
        settings.search_provider = "arxiv"
        client = sc.get_search_client()
        assert isinstance(client, sc.ArxivClient)
    finally:
        settings.search_provider = old


def test_get_search_client_tavily():
    """SEARCH_PROVIDER=tavily 时返回 TavilyClient"""
    old = settings.search_provider
    try:
        settings.search_provider = "tavily"
        client = sc.get_search_client()
        assert isinstance(client, sc.TavilyClient)
    finally:
        settings.search_provider = old


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
