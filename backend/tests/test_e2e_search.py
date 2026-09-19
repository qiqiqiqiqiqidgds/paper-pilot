"""
E2E 联网搜索（Sprint 4 / R2 拆分）
- test_28 ~ test_30：Tavily 联网搜相关工作
- test_31：compare 时搜索供应商故障 → 502（不能伪装成 4001"未搜到"）
"""
from unittest.mock import AsyncMock, patch

from test_e2e import (
    E2ETestBase, HEADERS, MOCK_SEARCH_RESULTS,
)
from app.services.search_client import TavilyClient


class TestSearch(E2ETestBase):
    """联网搜相关工作测试"""

    def test_28_search_related(self):
        """POST /api/search-related"""
        paper_id = self._upload_pdf()
        with self.mocks.patch_tavily(MOCK_SEARCH_RESULTS):
            res = self.client.post(
                "/api/search-related",
                json={"paper_id": paper_id, "max_results": 5},
                headers=HEADERS,
            )
        self.assertEqual(res.status_code, 200, f"search 应 200，实际 {res.status_code}: {res.text}")
        data = res.json()["data"]
        self.assertIn("related", data)
        self.assertEqual(len(data["related"]), 2, f"应有 2 篇 mock 结果，实际 {len(data['related'])}")
        for r in data["related"]:
            for k in ("title", "url", "content", "score"):
                self.assertIn(k, r)
        print(f"✅ search-related → {len(data['related'])} 篇相关工作")

    def test_29_search_related_no_key(self):
        """POST /api/search-related - Tavily key 未配置 → code=4001（业务状态码）"""
        paper_id = self._upload_pdf()
        # 临时把 api_key 置空
        import app.services.search_client as _sc
        _sc._client.api_key = ""
        try:
            res = self.client.post(
                "/api/search-related",
                json={"paper_id": paper_id, "max_results": 5},
                headers=HEADERS,
            )
        finally:
            _sc._client.api_key = "tvly-fake-key-for-test"
        self.assertEqual(res.status_code, 200, "业务 4001 也应 HTTP 200")
        body = res.json()
        self.assertEqual(body["code"], 4001, f"未配置 Tavily 应 code=4001，实际 {body['code']}")
        print(f"✅ search-related (无 Tavily key) → code=4001, msg: {body['message'][:50]}")

    def test_30_search_related_paper_not_found(self):
        """POST /api/search-related - 论文不存在 → 404"""
        res = self.client.post(
            "/api/search-related",
            json={"paper_id": "p_2099_xxxxxx", "max_results": 5},
            headers=HEADERS,
        )
        self.assertEqual(res.status_code, 404)
        print("✅ search-related (论文不存在) → 404")

    def test_31_compare_search_provider_failure_returns_502(self):
        """POST /api/compare - 搜索供应商故障 → 502

        回归：旧实现吞掉 SearchError 后落到 code=4001「未搜到相关工作」，
        用户会把"供应商挂了"误判成"这篇论文没有相关工作"。
        """
        paper_id = self._upload_pdf()
        mock = AsyncMock(side_effect=RuntimeError("tavily is down"))
        with patch.object(TavilyClient, "search_related_papers", new=mock):
            res = self.client.post(
                "/api/compare",
                json={"paper_id": paper_id, "max_results": 5},
                headers=HEADERS,
            )
        self.assertEqual(
            res.status_code, 502,
            f"搜索供应商故障应 502，实际 {res.status_code}: {res.text}",
        )
        self.assertIn("联网搜索失败", res.json()["message"])
        print("✅ compare (搜索供应商故障) → 502 而非 4001")
