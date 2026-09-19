"""
E2E SSE 流式分析端点测试（/api/analyze/stream）

覆盖（此前唯一无自动化测试的 API 端点）：
- test_sse_01: 完整 Map-Reduce 事件序列（started → chapters_detected → map_* → progress → maps_completed → reduce_started → reduce_completed → done）
- test_sse_02: 章节不足走 legacy 兜底（fallback_legacy 事件）
- test_sse_03: 部分章节 Map 失败仍能 Reduce（map_failed 事件）
- test_sse_04: 非 breakdown 类型 → error 事件
- test_sse_05: 论文不存在 → error 事件（HTTP 恒 200）
"""
import json
import unittest
import fitz
from unittest.mock import AsyncMock, patch

from test_e2e import E2ETestBase, HEADERS, MOCK_BREAKDOWN
from app.services.llm_client import LLMClient


def parse_sse(body: str) -> list:
    """解析 SSE 文本为 [{event, data}, ...]"""
    events = []
    for frame in body.split("\n\n"):
        frame = frame.strip()
        if not frame:
            continue
        event_name = "message"
        data_lines = []
        for line in frame.split("\n"):
            if line.startswith("event: "):
                event_name = line[7:].strip()
            elif line.startswith("data: "):
                data_lines.append(line[6:])
        if data_lines:
            events.append({"event": event_name, "data": json.loads("".join(data_lines))})
    return events


def create_plain_pdf() -> bytes:
    """无章节标题的纯文本 PDF（触发 legacy 兜底）"""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    y = 50
    for _ in range(30):
        page.insert_text((50, y), "Some random prose without any section heading words at all.", fontsize=11)
        y += 18
    out = doc.tobytes()
    doc.close()
    return out


# 章节 Map 输出（mock LLM 每次调用返回下一个值）
MAP_1 = {
    "chapter_name": "Introduction",
    "summary": "引言章节摘要",
    "key_points": ["RNN 并行性差"],
    "key_quote": "RNNs suffer from sequential computation.",
    "page_ref": 1,
    "section_type": "introduction",
}
MAP_2 = {
    "chapter_name": "Method",
    "summary": "方法章节摘要",
    "key_points": ["自注意力"],
    "key_quote": "The Transformer uses stacked self-attention.",
    "page_ref": 2,
    "section_type": "method",
}
MAP_3 = {
    "chapter_name": "Experiments",
    "summary": "实验章节摘要",
    "key_points": ["28.4 BLEU"],
    "key_quote": "Our model achieves 28.4 BLEU.",
    "page_ref": 3,
    "section_type": "experiment",
}
MAP_4 = {
    "chapter_name": "Conclusion",
    "summary": "结论章节摘要",
    "key_points": ["首个纯注意力架构"],
    "key_quote": "The first sequence transduction model based entirely on attention.",
    "page_ref": 4,
    "section_type": "conclusion",
}
# P2-1 修复后样例 PDF 第 3 页同页双标题（"3 Experiments" + "3.2 Model Variations"）
# 均被识别为章节，Map 调用顺序中第 4 个对应 Model 章（旧实现每页只认一个标题，
# 该章被静默丢弃，下方 side_effect 列表按此同步扩充）
MAP_5 = {
    "chapter_name": "Model",
    "summary": "模型变体章节摘要",
    "key_points": ["Base 与 Big 变体对比"],
    "key_quote": "We varied the base model in different ways.",
    "page_ref": 3,
    "section_type": "method",
}


class TestAnalyzeStream(E2ETestBase):
    """SSE 流式分析端点"""

    def _stream(self, body: dict):
        """发起 SSE 请求，返回 (status, events)"""
        with self.client.stream("POST", "/api/analyze/stream", json=body, headers=HEADERS) as r:
            status = r.status_code
            text = "".join(r.iter_text())
        return status, parse_sse(text)

    def test_sse_01_full_map_reduce_sequence(self):
        """完整 Map-Reduce：事件序列 + 结果落库"""
        paper_id = self._upload_pdf()
        mock = AsyncMock(side_effect=[MAP_1, MAP_2, MAP_3, MAP_5, MAP_4, MOCK_BREAKDOWN])
        with patch.object(LLMClient, "chat_json", new=mock):
            status, events = self._stream({"paper_id": paper_id, "type": "breakdown", "paper_language": "中文"})

        self.assertEqual(status, 200, f"SSE HTTP 应恒 200，实际 {status}")
        names = [e["event"] for e in events]

        # 事件序列
        self.assertEqual(names[0], "started")
        self.assertIn("chapters_detected", names)
        self.assertGreaterEqual(names.count("map_started"), 3)
        self.assertGreaterEqual(names.count("map_completed"), 3)
        self.assertIn("maps_completed", names)
        self.assertIn("reduce_started", names)
        self.assertIn("reduce_completed", names)
        self.assertEqual(names[-1], "done", f"应以 done 结尾，实际: {names}")

        # chapters_detected 带章节列表与页码范围
        cd = next(e for e in events if e["event"] == "chapters_detected")
        self.assertGreater(cd["data"]["count"], 0)
        self.assertTrue(all("page_start" in c and "page_end" in c for c in cd["data"]["chapters"]))

        # progress 事件累计到 total
        progresses = [e for e in events if e["event"] == "progress"]
        self.assertTrue(progresses, "应有 progress 事件")
        last_progress = progresses[-1]["data"]
        self.assertEqual(last_progress["completed"], last_progress["total"])

        # reduce_completed 携带结构化结果
        rc = next(e for e in events if e["event"] == "reduce_completed")
        self.assertEqual(rc["data"]["result"]["summary"], MOCK_BREAKDOWN["summary"])

        # done 事件含 elapsed_ms + result
        done = events[-1]["data"]
        self.assertIn("elapsed_ms", done)
        self.assertEqual(done["result"]["conclusion"], MOCK_BREAKDOWN["conclusion"])

        # 结果落库：缓存读可返回
        cache = self.client.get(f"/api/analyze/{paper_id}/breakdown", headers=HEADERS)
        self.assertEqual(cache.status_code, 200)
        self.assertEqual(cache.json()["data"]["result"]["summary"], MOCK_BREAKDOWN["summary"])
        print(f"✅ SSE 完整 Map-Reduce: {names}")

    def test_sse_02_legacy_fallback(self):
        """无章节的论文走 legacy 兜底（fallback_legacy 事件）"""
        res = self.client.post(
            "/api/upload",
            files={"file": ("plain.pdf", create_plain_pdf(), "application/pdf")},
            headers=HEADERS,
        )
        self.assertEqual(res.status_code, 200, f"上传失败: {res.text}")
        paper_id = res.json()["data"]["paper_id"]

        mock = AsyncMock(return_value=MOCK_BREAKDOWN)
        with patch.object(LLMClient, "chat_json", new=mock):
            status, events = self._stream({"paper_id": paper_id, "type": "breakdown", "paper_language": "中文"})

        self.assertEqual(status, 200)
        names = [e["event"] for e in events]
        self.assertIn("fallback_legacy", names, f"应走 legacy 兜底，实际事件: {names}")
        # legacy 路径也发 reduce_completed（mode=legacy）+ done
        rc = next(e for e in events if e["event"] == "reduce_completed")
        self.assertEqual(rc["data"].get("mode"), "legacy")
        self.assertEqual(names[-1], "done")
        # LLM 只被调一次（整篇）
        self.assertEqual(mock.await_count, 1)
        print(f"✅ SSE legacy 兜底: {names}")

    def test_sse_03_partial_map_failure(self):
        """部分章节 Map 失败：发 map_failed，其余章节继续 Reduce"""
        paper_id = self._upload_pdf()
        mock = AsyncMock(side_effect=[MAP_1, RuntimeError("boom"), MAP_3, MAP_5, MAP_4, MOCK_BREAKDOWN])
        with patch.object(LLMClient, "chat_json", new=mock):
            status, events = self._stream({"paper_id": paper_id, "type": "breakdown", "paper_language": "中文"})

        self.assertEqual(status, 200)
        names = [e["event"] for e in events]
        self.assertIn("map_failed", names)
        # 失败后仍完成 Reduce
        self.assertIn("reduce_started", names)
        self.assertIn("done", names)
        # 事件中不泄露内部异常详情（固定文案）
        mf = next(e for e in events if e["event"] == "map_failed")
        self.assertIn("该章节分析失败", mf["data"]["error"])
        print(f"✅ SSE 部分章节失败容忍: {names}")

    def test_sse_04_non_breakdown_type_error(self):
        """非 breakdown 类型 → error 事件（HTTP 恒 200）"""
        paper_id = self._upload_pdf()
        status, events = self._stream({"paper_id": paper_id, "type": "innovation", "paper_language": "中文"})
        self.assertEqual(status, 200)
        self.assertEqual(events[0]["event"], "error")
        self.assertEqual(events[0]["data"]["code"], 400)
        print(f"✅ SSE 非 breakdown → error: {events[0]['data']}")

    def test_sse_05_paper_not_found(self):
        """论文不存在 → error 事件（HTTP 恒 200）"""
        status, events = self._stream({"paper_id": "p_2099_not_exists", "type": "breakdown"})
        self.assertEqual(status, 200)
        self.assertEqual(events[0]["event"], "error")
        self.assertEqual(events[0]["data"]["code"], 404)
        print(f"✅ SSE 论文不存在 → error: {events[0]['data']}")


class TestStreamTaskCancellation(unittest.TestCase):
    """B4 回归：SSE 生成器以任何方式退出时，已 create_task 的后台 LLM 任务必须被取消

    不走 HTTP（TestClient 无法模拟断连），直接驱动 analyze_stream 返回的
    async generator：消费到 Map 任务启动后 aclose()，断言挂起的 LLM 任务被取消。
    """

    def test_generator_close_cancels_map_tasks(self):
        import asyncio
        from unittest.mock import patch

        from app.api import analyze as analyze_mod
        from app.api.analyze import analyze_stream
        from app.agent.chapter_splitter import Chapter
        from app.models.schemas import AnalyzeRequest

        class HangingLLM:
            """chat_json 永远挂起，模拟卡死的 LLM 调用；记录自身所在 task"""

            def __init__(self):
                self.tasks = []

            async def chat_json(self, **kwargs):
                self.tasks.append(asyncio.current_task())
                await asyncio.Event().wait()  # 永不 set → 挂起

        fake_llm = HangingLLM()
        chapters = [
            Chapter(name="Introduction", text="intro", page_start=1, page_end=1, level=1),
            Chapter(name="Method", text="method", page_start=2, page_end=2, level=1),
        ]

        async def scenario():
            resp = await analyze_stream(
                AnalyzeRequest(paper_id="p_2026_01_01_abcd1234", type="breakdown")
            )
            gen = resp.body_iterator
            # 消费事件直到 Map 任务已被 create_task 启动（started / chapters_detected / map_started）
            await gen.__anext__()  # started
            await gen.__anext__()  # chapters_detected
            await asyncio.wait_for(gen.__anext__(), timeout=5)  # map_started（任务已起）
            # 模拟客户端断连：生成器被关闭
            await gen.aclose()
            await asyncio.sleep(0.05)
            # 在 loop 仍存活时读取取消状态（不能依赖 asyncio.run 的退出清理）
            return [t.cancelled() for t in fake_llm.tasks]

        with \
            patch.object(analyze_mod, "file_exists", return_value=True), \
            patch.object(analyze_mod, "load_text_json_async",
                         return_value={"full_text": "x", "meta": {}, "pages": [], "toc": []}), \
            patch.object(analyze_mod, "split_chapters", return_value=chapters), \
            patch.object(analyze_mod, "get_llm_client", return_value=fake_llm):
            cancel_flags = asyncio.run(scenario())

        # 两个 Map 任务的 LLM 调用都被取消（修复前会一直挂起泄漏）
        self.assertEqual(len(fake_llm.tasks), 2, f"应有 2 个 Map LLM 调用被启动，实际 {len(fake_llm.tasks)}")
        for i, cancelled in enumerate(cancel_flags):
            self.assertTrue(cancelled, f"Map LLM 任务 {i} 未被取消（泄漏）")
        print("✅ B4: 生成器关闭时后台 Map LLM 任务全部被取消")


if __name__ == "__main__":
    unittest.main()
