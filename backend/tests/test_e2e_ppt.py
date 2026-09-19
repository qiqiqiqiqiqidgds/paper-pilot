"""
E2E PPT 接口（Sprint 4 / R2 拆分）
- test_38 ~ test_44：generate-ppt + download-ppt + 路径遍历保护
"""
from test_e2e import (
    E2ETestBase, HEADERS, PPTS_DIR, MOCK_BREAKDOWN, MOCK_INNOVATION, MOCK_FLAWS, MOCK_COMPARE, MOCK_SEARCH_RESULTS,
)


class TestPPT(E2ETestBase):
    """PPT 生成 + 下载 + 安全测试"""

    def test_38_generate_ppt(self):
        """POST /api/generate-ppt - 基于已有 breakdown + innovation"""
        paper_id = self._upload_pdf()
        gen_b = self._run_analyze(paper_id, MOCK_BREAKDOWN, "breakdown")
        self.assertEqual(gen_b.status_code, 200, f"生成 breakdown 失败: {gen_b.text}")
        gen_i = self._run_analyze(paper_id, MOCK_INNOVATION, "innovation")
        self.assertEqual(gen_i.status_code, 200, f"生成 innovation 失败: {gen_i.text}")

        res = self.client.post(
            "/api/generate-ppt",
            json={"paper_id": paper_id, "include_flaws": False, "include_compare": False},
            headers=HEADERS,
        )
        self.assertEqual(res.status_code, 200, f"PPT 生成应 200，实际 {res.status_code}: {res.text}")
        data = res.json()["data"]
        self.assertIn("download_url", data)
        self.assertIn("filename", data)
        self.assertIn("/api/download-ppt/", data["download_url"])
        self.assertGreater(data["size"], 1000, f"PPT 至少 1KB，实际 {data['size']}")
        self.assertGreater(data["pages"], 1, f"PPT 应有多页，实际 {data['pages']}")
        ppt_file = PPTS_DIR / data["filename"]
        self.assertTrue(ppt_file.exists(), f"PPT 文件应存在: {ppt_file}")
        print(f"✅ generate-ppt → {data['pages']} 页, {data['size']} bytes, filename={data['filename']}")

    def test_39_generate_ppt_with_flaws_and_compare(self):
        """POST /api/generate-ppt - include_flaws + include_compare"""
        paper_id = self._upload_pdf()
        self._run_analyze(paper_id, MOCK_BREAKDOWN, "breakdown")
        self._run_analyze(paper_id, MOCK_INNOVATION, "innovation")
        self._run_analyze(paper_id, MOCK_FLAWS, "flaws")
        with self.mocks.patch_tavily(MOCK_SEARCH_RESULTS), self.mocks.patch_llm(MOCK_COMPARE):
            self.client.post(
                "/api/compare",
                json={"paper_id": paper_id, "max_results": 3},
                headers=HEADERS,
            )

        res = self.client.post(
            "/api/generate-ppt",
            json={"paper_id": paper_id, "include_flaws": True, "include_compare": True},
            headers=HEADERS,
        )
        self.assertEqual(res.status_code, 200, f"PPT 生成应 200，实际 {res.status_code}: {res.text}")
        data = res.json()["data"]
        self.assertGreater(data["pages"], 3, f"含 4 类内容应多页，实际 {data['pages']}")
        print(f"✅ generate-ppt (含 flaws+compare) → {data['pages']} 页")

    def test_40_generate_ppt_no_analysis(self):
        """POST /api/generate-ppt - 无任何分析 → 400"""
        paper_id = self._upload_pdf()
        res = self.client.post(
            "/api/generate-ppt",
            json={"paper_id": paper_id},
            headers=HEADERS,
        )
        self.assertEqual(res.status_code, 400, f"无分析应 400，实际 {res.status_code}: {res.text}")
        body = res.json()
        # error_handler 把 HTTPException.detail 写入 "message" 字段（detail 恒为空）
        self.assertIn("没有可用", body.get("message", ""))
        print(f"✅ generate-ppt (无分析) → 400, message: {body['message'][:50]}")

    def test_41_generate_ppt_paper_not_found(self):
        """POST /api/generate-ppt - 论文不存在 → 404"""
        res = self.client.post(
            "/api/generate-ppt",
            json={"paper_id": "p_2099_xxxxxx"},
            headers=HEADERS,
        )
        self.assertEqual(res.status_code, 404)
        print("✅ generate-ppt (论文不存在) → 404")

    def test_42_download_ppt(self):
        """GET /api/download-ppt/{filename}"""
        paper_id = self._upload_pdf()
        self._run_analyze(paper_id, MOCK_BREAKDOWN, "breakdown")
        gen_res = self.client.post(
            "/api/generate-ppt",
            json={"paper_id": paper_id},
            headers=HEADERS,
        )
        self.assertEqual(gen_res.status_code, 200)
        filename = gen_res.json()["data"]["filename"]

        res = self.client.get(f"/api/download-ppt/{filename}", headers=HEADERS)
        self.assertEqual(res.status_code, 200, f"下载 PPT 应 200，实际 {res.status_code}: {res.text[:200]}")
        self.assertIn("presentationml", res.headers["content-type"])
        self.assertGreater(len(res.content), 1000)
        print(f"✅ download-ppt/{filename[:30]}... → {len(res.content)} bytes, content-type={res.headers['content-type']}")

    def test_43_download_ppt_not_found(self):
        """GET /api/download-ppt/nonexistent.pptx → 404"""
        res = self.client.get("/api/download-ppt/does_not_exist_xxx.pptx", headers=HEADERS)
        self.assertEqual(res.status_code, 404)
        print("✅ download-ppt (不存在) → 404")

    def test_44_download_ppt_path_traversal(self):
        """GET /api/download-ppt/.. — 路径遍历保护"""
        attacks = [
            "/api/download-ppt/..",
            "/api/download-ppt/../etc",
            "/api/download-ppt/sub/../file.pptx",
        ]
        for url in attacks:
            res = self.client.get(url, headers=HEADERS)
            self.assertIn(
                res.status_code, (400, 404),
                f"路径遍历 {url!r} 应被拦，实际 {res.status_code}: {res.text}"
            )
        print(f"✅ PPT 路径遍历尝试全部被拦（{len(attacks)} 种）")

    def test_44b_generate_ppt_warnings_on_missing_analysis(self):
        """POST /api/generate-ppt - B14: 勾选但分析缺失 → data.warnings 非空；齐全/不勾选 → 空数组"""
        paper_id = self._upload_pdf()
        self._run_analyze(paper_id, MOCK_BREAKDOWN, "breakdown")

        # 1) 不勾选 → warnings 为空数组
        res = self.client.post(
            "/api/generate-ppt",
            json={"paper_id": paper_id, "include_flaws": False, "include_compare": False},
            headers=HEADERS,
        )
        self.assertEqual(res.status_code, 200, f"PPT 生成应 200，实际 {res.status_code}: {res.text}")
        data = res.json()["data"]
        self.assertEqual(
            data.get("warnings"), [],
            f"不勾选时 warnings 应为空数组，实际: {data.get('warnings')}",
        )

        # 2) 勾选但 flaws / compare 均未生成 → warnings 非空（2 条）
        res = self.client.post(
            "/api/generate-ppt",
            json={"paper_id": paper_id, "include_flaws": True, "include_compare": True},
            headers=HEADERS,
        )
        self.assertEqual(res.status_code, 200, f"PPT 生成应 200，实际 {res.status_code}: {res.text}")
        data = res.json()["data"]
        warnings = data.get("warnings") or []
        self.assertTrue(warnings, f"勾选但分析缺失时 warnings 应非空: {warnings}")
        self.assertEqual(len(warnings), 2, f"应有 2 条 warnings（flaws + compare），实际: {warnings}")

        # 3) 补齐 flaws + compare 分析后再勾选 → warnings 为空数组
        self._run_analyze(paper_id, MOCK_FLAWS, "flaws")
        with self.mocks.patch_tavily(MOCK_SEARCH_RESULTS), self.mocks.patch_llm(MOCK_COMPARE):
            self.client.post(
                "/api/compare",
                json={"paper_id": paper_id, "max_results": 3},
                headers=HEADERS,
            )
        res = self.client.post(
            "/api/generate-ppt",
            json={"paper_id": paper_id, "include_flaws": True, "include_compare": True},
            headers=HEADERS,
        )
        self.assertEqual(res.status_code, 200, f"PPT 生成应 200，实际 {res.status_code}: {res.text}")
        data = res.json()["data"]
        self.assertEqual(
            data.get("warnings"), [],
            f"分析齐全时 warnings 应为空数组，实际: {data.get('warnings')}",
        )
        print(f"✅ generate-ppt warnings: 缺失→{len(warnings)} 条 / 不勾选与齐全→空")
