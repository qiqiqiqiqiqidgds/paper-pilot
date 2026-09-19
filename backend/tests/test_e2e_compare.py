"""
E2E 对比接口（Sprint 4 / R2 拆分）
- test_31 ~ test_37：联网搜 + LLM 对比 / 多篇库内对比 + 各种边界
"""
from test_e2e import (
    E2ETestBase, HEADERS, PAPERS_DIR, MOCK_COMPARE, MOCK_SEARCH_RESULTS,
)


class TestCompare(E2ETestBase):
    """对比接口测试（单论文联网搜对比 + 多篇库内对比）"""

    def test_31_compare(self):
        """POST /api/compare - 联网搜 + LLM 对比"""
        paper_id = self._upload_pdf()
        with self.mocks.patch_tavily(MOCK_SEARCH_RESULTS), self.mocks.patch_llm(MOCK_COMPARE):
            res = self.client.post(
                "/api/compare",
                json={"paper_id": paper_id, "max_results": 5},
                headers=HEADERS,
            )
        self.assertEqual(res.status_code, 200, f"compare 应 200，实际 {res.status_code}: {res.text}")
        data = res.json()["data"]
        self.assertIn("related_papers", data)
        self.assertIn("compare_table", data)
        self.assertIn("summary", data)
        cache = PAPERS_DIR / paper_id / "analysis_compare.json"
        self.assertTrue(cache.exists(), f"对比缓存应存在: {cache}")
        print(f"✅ compare → {len(data['related_papers'])} 篇对比, table {len(data['compare_table'])} 行")

    def test_32_compare_no_tavily_key(self):
        """POST /api/compare - Tavily key 未配置 → code=4001"""
        paper_id = self._upload_pdf()
        import app.services.search_client as _sc
        _sc._client.api_key = ""
        try:
            res = self.client.post(
                "/api/compare",
                json={"paper_id": paper_id, "max_results": 5},
                headers=HEADERS,
            )
        finally:
            _sc._client.api_key = "tvly-fake-key-for-test"
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["code"], 4001, "无 Tavily key 应 code=4001")
        self.assertEqual(body["data"]["related_papers"], [])
        print("✅ compare (无 Tavily key) → code=4001")

    def test_31b_has_compare_flag_after_compare(self):
        """compare 后 GET /api/papers 的 has_compare 应为 true（回归：此前前端看到恒为 false 疑为同步问题）"""
        paper_id = self._upload_pdf()

        # 对比前：has_compare=false
        res = self.client.get("/api/papers", headers=HEADERS)
        item = next(p for p in res.json()["data"]["items"] if p["paper_id"] == paper_id)
        self.assertFalse(item["has_compare"], "对比前 has_compare 应为 false")

        # 跑联网对比
        with self.mocks.patch_tavily(MOCK_SEARCH_RESULTS), self.mocks.patch_llm(MOCK_COMPARE):
            self.client.post(
                "/api/compare",
                json={"paper_id": paper_id, "max_results": 5},
                headers=HEADERS,
            )

        # 对比后：has_compare=true（列表实时反映缓存文件）
        res = self.client.get("/api/papers", headers=HEADERS)
        item = next(p for p in res.json()["data"]["items"] if p["paper_id"] == paper_id)
        self.assertTrue(item["has_compare"], "对比后 has_compare 应为 true")
        print("✅ has_compare 联动: false → true")

    def test_33_compare_papers(self):
        """POST /api/compare-papers - 2 篇论文"""
        pdf_id = self._upload_pdf()
        docx_id = self._upload_docx()
        with self.mocks.patch_llm(MOCK_COMPARE):
            res = self.client.post(
                "/api/compare-papers",
                json={
                    "paper_ids": [pdf_id, docx_id],
                    "main_id": pdf_id,
                    "paper_language": "中文",
                },
                headers=HEADERS,
            )
        self.assertEqual(res.status_code, 200, f"compare-papers 应 200，实际 {res.status_code}: {res.text}")
        data = res.json()["data"]
        self.assertIn("compare_table", data)
        self.assertIn("summary", data)
        cache = PAPERS_DIR / pdf_id / "analysis_compare.json"
        self.assertTrue(cache.exists(), f"对比缓存应存在: {cache}")
        print(f"✅ compare-papers → table {len(data['compare_table'])} 行, summary 长度={len(data['summary'])}")

    def test_34_compare_papers_three(self):
        """POST /api/compare-papers - 3 篇论文"""
        ids = [self._upload_pdf() for _ in range(2)]
        ids.append(self._upload_docx())
        with self.mocks.patch_llm(MOCK_COMPARE):
            res = self.client.post(
                "/api/compare-papers",
                json={"paper_ids": ids, "main_id": ids[0], "paper_language": "中文"},
                headers=HEADERS,
            )
        self.assertEqual(res.status_code, 200, f"3 篇对比应 200，实际 {res.status_code}: {res.text}")
        print("✅ compare-papers (3 篇) → 200")

    def test_35_compare_papers_too_few(self):
        """POST /api/compare-papers - 少于 2 篇 → 422（Pydantic 校验）"""
        pdf_id = self._upload_pdf()
        res = self.client.post(
            "/api/compare-papers",
            json={"paper_ids": [pdf_id], "main_id": pdf_id},
            headers=HEADERS,
        )
        self.assertEqual(res.status_code, 422, f"少于 2 篇应 422，实际 {res.status_code}")
        print("✅ compare-papers (1 篇) → 422 (Pydantic 校验)")

    def test_36_compare_papers_invalid_main(self):
        """POST /api/compare-papers - main_id 不在 paper_ids → 400"""
        pdf_id = self._upload_pdf()
        docx_id = self._upload_docx()
        res = self.client.post(
            "/api/compare-papers",
            json={"paper_ids": [pdf_id, docx_id], "main_id": "p_2099_invalid"},
            headers=HEADERS,
        )
        self.assertEqual(res.status_code, 400, f"main_id 不在列表应 400，实际 {res.status_code}")
        print("✅ compare-papers (main_id 不在列表) → 400")

    def test_37_compare_papers_not_found(self):
        """POST /api/compare-papers - 论文不存在 → 404"""
        pdf_id = self._upload_pdf()
        res = self.client.post(
            "/api/compare-papers",
            json={"paper_ids": [pdf_id, "p_2099_xxxxxx"], "main_id": pdf_id},
            headers=HEADERS,
        )
        self.assertEqual(res.status_code, 404, f"论文不存在应 404，实际 {res.status_code}")
        print("✅ compare-papers (论文不存在) → 404")
