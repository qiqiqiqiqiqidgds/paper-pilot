"""
E2E 分析接口（Sprint 4 / R2 拆分）
- test_21 ~ test_27：breakdown / innovation / flaws + 缓存
- test_28 ~ test_29：P1-3 部分章节失败的统计透出（chapters_total/succeeded/failed_chapters）
"""
import asyncio

from test_e2e import (
    E2ETestBase, HEADERS, PAPERS_DIR, MOCK_BREAKDOWN, MOCK_INNOVATION, MOCK_FLAWS,
)
from app.config import settings

# 单章 Map 的最小合法返回（供 side_effect 列表复用）
MOCK_MAP_OK = {
    "chapter_name": "x", "summary": "本章摘要", "key_points": ["要点"],
    "key_quote": "原文引用", "page_ref": 1, "section_type": "other",
}


class TestAnalyze(E2ETestBase):
    """分析接口测试（breakdown / innovation / flaws + 缓存读写）"""

    def test_21_analyze_breakdown(self):
        """POST /api/analyze - breakdown（map-reduce）"""
        paper_id = self._upload_pdf()
        with self.mocks.patch_llm(MOCK_BREAKDOWN):
            res = self.client.post(
                "/api/analyze",
                json={"paper_id": paper_id, "type": "breakdown", "paper_language": "中文"},
                headers=HEADERS,
            )
        self.assertEqual(res.status_code, 200, f"breakdown 应 200，实际 {res.status_code}: {res.text}")
        body = res.json()
        data = body["data"]
        self.assertEqual(data["type"], "breakdown")
        self.assertIn("summary", data["result"])
        self.assertIn("method", data["result"])
        self.assertIn("elapsed_ms", data)
        cache_file = PAPERS_DIR / paper_id / "analysis_breakdown.json"
        self.assertTrue(cache_file.exists(), f"缓存文件应存在: {cache_file}")
        print(f"✅ analyze breakdown → {data['elapsed_ms']}ms, summary 长度={len(data['result']['summary'])}")

    def test_22_analyze_innovation(self):
        """POST /api/analyze - innovation（legacy）"""
        paper_id = self._upload_pdf()
        with self.mocks.patch_llm(MOCK_INNOVATION):
            res = self.client.post(
                "/api/analyze",
                json={"paper_id": paper_id, "type": "innovation"},
                headers=HEADERS,
            )
        self.assertEqual(res.status_code, 200, f"innovation 应 200，实际 {res.status_code}: {res.text}")
        data = res.json()["data"]
        self.assertIn("core_innovations", data["result"])
        self.assertEqual(data["result"]["innovation_level"], "disruptive")
        self.assertEqual(len(data["result"]["core_innovations"]), 2)
        print(f"✅ analyze innovation → {len(data['result']['core_innovations'])} 创新点, level={data['result']['innovation_level']}")

    def test_23_analyze_flaws(self):
        """POST /api/analyze - flaws（legacy）"""
        paper_id = self._upload_pdf()
        with self.mocks.patch_llm(MOCK_FLAWS):
            res = self.client.post(
                "/api/analyze",
                json={"paper_id": paper_id, "type": "flaws"},
                headers=HEADERS,
            )
        self.assertEqual(res.status_code, 200, f"flaws 应 200，实际 {res.status_code}: {res.text}")
        data = res.json()["data"]
        self.assertIn("method_level", data["result"])
        self.assertIn("overall_assessment", data["result"])
        self.assertEqual(len(data["result"]["method_level"]), 1)
        print(f"✅ analyze flaws → {len(data['result']['method_level'])} method-level, {len(data['result']['experiment_level'])} experiment-level")

    def test_24_analyze_invalid_type(self):
        """POST /api/analyze - 错误 type → 被拒绝（400 / 422）"""
        paper_id = self._upload_pdf()
        res = self.client.post(
            "/api/analyze",
            json={"paper_id": paper_id, "type": "unknown_type"},
            headers=HEADERS,
        )
        # AnalyzeRequest.type 是 Literal，未知 type 在 schema 层即被拒（422）；
        # 兜底 HTTPException 分支也可能返回 400，两种拒绝都接受。
        self.assertIn(res.status_code, (400, 422), f"未知 type 应被拒绝，实际 {res.status_code}")
        body = res.json()
        # error_handler 把 detail 写入 "message" 字段（detail 恒为空）
        self.assertIn("breakdown", body.get("message", ""))
        print(f"✅ analyze unknown type → {res.status_code}, message: {body['message'][:60]}")

    def test_25_analyze_paper_not_found(self):
        """POST /api/analyze - 论文不存在 → 404"""
        res = self.client.post(
            "/api/analyze",
            json={"paper_id": "p_2099_xxxxxx", "type": "innovation"},
            headers=HEADERS,
        )
        self.assertEqual(res.status_code, 404, f"论文不存在应 404，实际 {res.status_code}")
        print("✅ analyze (论文不存在) → 404")

    def test_26_get_cached_analysis(self):
        """GET /api/analyze/{id}/{type} - 读缓存"""
        paper_id = self._upload_pdf()
        with self.mocks.patch_llm(MOCK_INNOVATION):
            gen = self.client.post(
                "/api/analyze",
                json={"paper_id": paper_id, "type": "innovation"},
                headers=HEADERS,
            )
            self.assertEqual(gen.status_code, 200, f"生成失败: {gen.text}")
            res = self.client.get(f"/api/analyze/{paper_id}/innovation", headers=HEADERS)
        self.assertEqual(res.status_code, 200, f"读缓存应 200，实际 {res.status_code}: {res.text}")
        data = res.json()["data"]
        self.assertEqual(data["type"], "innovation")
        self.assertIn("core_innovations", data["result"])
        gen_data = gen.json()["data"]["result"]
        self.assertEqual(data["result"]["innovation_level"], gen_data["innovation_level"])
        print(f"✅ GET 缓存 /api/analyze/{paper_id[:15]}.../innovation → 200")

    def test_27_get_cached_not_found(self):
        """GET /api/analyze/{id}/{type} - 缓存不存在 → 404"""
        paper_id = self._upload_pdf()
        res = self.client.get(f"/api/analyze/{paper_id}/innovation", headers=HEADERS)
        self.assertEqual(res.status_code, 404, f"未生成的缓存应 404，实际 {res.status_code}")
        body = res.json()
        # error_handler 把 HTTPException.detail 写入 "message" 字段（detail 恒为空）
        self.assertIn("未生成", body.get("message", ""))
        print(f"✅ GET 缓存（未生成） → 404, message: {body['message']}")

    # ===== P1-3：部分章节失败的统计透出 =====

    def test_28_partial_map_failure_reports_stats(self):
        """部分章节 Map 失败 → 仍 200，data 含章节统计（不再零提示）

        样例 PDF 识别出 5 章（Introduction / Method / Experiments / Model /
        Conclusion）。P2-1 修复后第 3 页同页双标题 "3 Experiments" +
        "3.2 Model Variations" 均被识别（旧实现每页只认第一个标题，静默丢了
        Model 章，此处的 4 章正是 P2-1 缺陷的产物）。Map 调用顺序即章节顺序
        （Semaphore(3) 下前 3 章先发，第 4 章随后），最后一次调用是 Reduce。
        side_effect 让第 2 次（Method 章）失败。
        """
        paper_id = self._upload_pdf()
        mock = self.mocks.patch_llm(None)
        mock.side_effect = [
            dict(MOCK_MAP_OK),
            RuntimeError("模拟该章节 Map 失败"),   # 第 2 章 Method
            dict(MOCK_MAP_OK),
            dict(MOCK_MAP_OK),
            dict(MOCK_MAP_OK),                     # 第 4 章 Model（P2-1 后新增）
            MOCK_BREAKDOWN,                        # 最后一次：Reduce
        ]
        res = self.client.post(
            "/api/analyze",
            json={"paper_id": paper_id, "type": "breakdown"},
            headers=HEADERS,
        )
        self.assertEqual(res.status_code, 200, f"部分章节失败仍应 200: {res.text}")
        data = res.json()["data"]
        self.assertEqual(data["chapters_total"], 5)
        self.assertEqual(data["chapters_succeeded"], 4)
        self.assertEqual(data["failed_chapters"], ["Method"])
        self.assertIn("summary", data["result"])
        print(f"✅ analyze 部分章节失败 → 200, {data['chapters_succeeded']}/{data['chapters_total']} 章, 失败: {data['failed_chapters']}")

    def test_29_map_timeout_cancelled_chapter_counted_as_failed(self):
        """Map 整体超时 → 被取消章节（CancelledError）显式计入 failed_chapters

        CancelledError 是 BaseException 子类，isinstance(raw, Exception) 判不到；
        旧实现走"非 dict"分支被静默跳过。让第 2 章 Map 挂起超过整体超时，
        其余章节正常完成 → 只有第 2 章计入失败。
        """
        paper_id = self._upload_pdf()
        original_timeout = settings.llm_timeout_seconds
        settings.llm_timeout_seconds = 0.3  # 缩短 Map 整体超时
        self.addCleanup(setattr, settings, "llm_timeout_seconds", original_timeout)

        call_n = {"n": 0}

        async def fake_chat_json(*args, **kwargs):
            call_n["n"] += 1
            if call_n["n"] == 2:  # 第 2 章 Method：挂起 → 超时后被取消
                await asyncio.sleep(5)
            return dict(MOCK_MAP_OK)

        mock = self.mocks.patch_llm(None)
        mock.side_effect = fake_chat_json

        res = self.client.post(
            "/api/analyze",
            json={"paper_id": paper_id, "type": "breakdown"},
            headers=HEADERS,
        )
        self.assertEqual(res.status_code, 200, f"超时取消单章不应整体失败: {res.text}")
        data = res.json()["data"]
        self.assertEqual(data["chapters_total"], 5)   # P2-1 后样例 PDF 为 5 章
        self.assertEqual(data["chapters_succeeded"], 4)
        self.assertEqual(data["failed_chapters"], ["Method"])
        print(f"✅ analyze Map 超时取消 → 200, {data['chapters_succeeded']}/{data['chapters_total']} 章, 取消: {data['failed_chapters']}")

    # ===== P1-2c：Reduce 上下文超限的激进截断重试 =====

    def test_30_reduce_context_overflow_retries_with_aggressive_budget(self):
        """Reduce 疑似上下文超限 → 用激进截断预算重试一次且仅一次"""
        from unittest.mock import patch
        from app.api import analyze as analyze_mod
        from app.agent.prompts import breakdown as breakdown_mod

        paper_id = self._upload_pdf()
        build_calls = []
        real_build = breakdown_mod.build_reduce_messages

        def recording_build(*args, **kwargs):
            # None 表示未显式传参（走默认 60000 预算）
            build_calls.append(kwargs.get("total_budget_chars"))
            return real_build(*args, **kwargs)

        mock = self.mocks.patch_llm(None)
        mock.side_effect = [
            dict(MOCK_MAP_OK), dict(MOCK_MAP_OK), dict(MOCK_MAP_OK),
            dict(MOCK_MAP_OK), dict(MOCK_MAP_OK),   # P2-1 后 5 章各一次 Map
            Exception("This model's maximum context length is 16385 tokens, "
                      "however you requested 200000 tokens (prompt + completion)"),
            MOCK_BREAKDOWN,  # 激进截断重试成功
        ]
        with patch.object(analyze_mod, "build_reduce_messages", side_effect=recording_build):
            res = self.client.post(
                "/api/analyze",
                json={"paper_id": paper_id, "type": "breakdown"},
                headers=HEADERS,
            )
        self.assertEqual(res.status_code, 200, f"重试后应成功: {res.text}")
        data = res.json()["data"]
        self.assertEqual(data["chapters_succeeded"], 5)
        self.assertEqual(data["failed_chapters"], [])
        # 恰好两次 Reduce 构造：首次默认预算 + 重试激进预算（一次为限）
        self.assertEqual(
            build_calls,
            [None, breakdown_mod.REDUCE_RETRY_BUDGET_CHARS],
            f"Reduce 构造次数/预算不符: {build_calls}",
        )
        print(f"✅ analyze Reduce 上下文超限 → 激进截断重试一次成功, build 调用: {build_calls}")

    def test_31_reduce_non_overflow_failure_no_retry(self):
        """Reduce 非上下文超限失败（如普通 5xx）→ 不重试，直接 502"""
        from unittest.mock import patch
        from app.api import analyze as analyze_mod

        paper_id = self._upload_pdf()
        build_calls = []

        def recording_build(*args, **kwargs):
            build_calls.append(kwargs.get("total_budget_chars"))
            return []

        mock = self.mocks.patch_llm(None)
        mock.side_effect = [
            dict(MOCK_MAP_OK), dict(MOCK_MAP_OK), dict(MOCK_MAP_OK),
            dict(MOCK_MAP_OK), dict(MOCK_MAP_OK),   # P2-1 后 5 章各一次 Map
            RuntimeError("LLM 服务内部错误"),        # Reduce 调用（非超限失败）
        ]
        with patch.object(analyze_mod, "build_reduce_messages", side_effect=recording_build):
            res = self.client.post(
                "/api/analyze",
                json={"paper_id": paper_id, "type": "breakdown"},
                headers=HEADERS,
            )
        self.assertEqual(res.status_code, 502, f"非超限失败应 502: {res.text}")
        self.assertEqual(len(build_calls), 1, f"不应重试，实际构造 {len(build_calls)} 次")
        print("✅ analyze Reduce 普通失败 → 502 且不重试")
