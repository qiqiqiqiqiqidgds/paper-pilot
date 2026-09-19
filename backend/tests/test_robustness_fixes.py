"""
2026-09 健壮性修复回归测试

覆盖本轮修复（此前无自动化测试保护的路径）：
- legacy 整篇分析整体超时 → 502（此前只有 Map/Reduce 有超时）
- text.json 里 abstract/title 为显式 null 时不 500（get 默认值只防键缺失，不防 null）
- 上传后半程（save_text_json）失败时清理"幽灵目录"
- PPT 文件名：null 标题不 TypeError、空标题不用 "_汇报" 畸形名
- X-Request-ID 非法输入被替换（防日志注入/伪造）
"""
import asyncio
import re
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from test_e2e import E2ETestBase, HEADERS, MOCK_COMPARE
from app.config import settings
from app.utils.storage import save_text_json


# ===== legacy 整体超时 =====

@pytest.mark.asyncio
async def test_legacy_analysis_timeout_returns_502(monkeypatch):
    """_analyze_with_legacy 整体超时 → HTTPException 502

    旧实现没有外层 asyncio.timeout，一次挂起的 LLM 请求（含 SDK 重试最坏 4 次）
    可占用连接约 8 分钟。"""
    from app.api import analyze as analyze_mod

    monkeypatch.setattr(settings, "llm_timeout_seconds", 0.1)

    class HangingLLM:
        async def chat_json(self, **kwargs):
            await asyncio.Event().wait()  # 永不完成

    monkeypatch.setattr(analyze_mod, "get_llm_client", lambda: HangingLLM())

    with pytest.raises(HTTPException) as ctx:
        await analyze_mod._analyze_with_legacy(
            "paper text", {}, "中文", lambda *args: []
        )
    assert ctx.value.status_code == 502
    assert "超时" in ctx.value.detail


@pytest.mark.asyncio
async def test_legacy_analysis_config_error_transparent(monkeypatch):
    """缺 LLM_API_KEY 的根因仍然透出（不能被超时改动误伤）"""
    from app.api import analyze as analyze_mod
    from app.services.llm_client import LLMConfigError

    class NoKeyLLM:
        async def chat_json(self, **kwargs):
            raise LLMConfigError("LLM_API_KEY 未配置")

    monkeypatch.setattr(analyze_mod, "get_llm_client", lambda: NoKeyLLM())

    with pytest.raises(HTTPException) as ctx:
        await analyze_mod._analyze_with_legacy(
            "paper text", {}, "中文", lambda *args: []
        )
    assert ctx.value.status_code == 502
    assert "LLM_API_KEY" in ctx.value.detail


# ===== prompts null 兜底（单元级） =====

def test_build_compare_messages_null_fields():
    """abstract/authors/title 为显式 null 时不抛 TypeError"""
    from app.agent.prompts.compare import build_compare_messages

    msgs = build_compare_messages(
        {"title": None, "authors": None, "abstract": None, "year": None},
        [{"title": None, "url": None, "content": None}],
        "中文",
    )
    assert len(msgs) == 2
    assert "未提供" in msgs[1]["content"]


def test_build_breakdown_messages_null_fields():
    """breakdown 系列提示词对 null meta 字段不抛 TypeError（第三轮发现的漏网：
    get 默认值只防键缺失，meta.abstract=null 时 [:500] 切片会 TypeError → 误导性 502）"""
    from app.agent.chapter_splitter import Chapter
    from app.agent.prompts.breakdown import (
        build_breakdown_messages,
        build_chapter_map_messages,
        build_reduce_messages,
    )

    meta = {"title": None, "authors": None, "abstract": None}
    # legacy 整篇
    msgs = build_breakdown_messages("正文内容 " * 50, meta, "中文")
    assert len(msgs) == 2 and msgs[1]["content"]
    # map（单章）
    ch = Chapter(name="Introduction", text="intro text " * 20, page_start=1, page_end=1, level=1)
    msgs = build_chapter_map_messages(ch, meta, "中文")
    assert len(msgs) == 2 and msgs[1]["content"]
    # reduce（汇总）
    msgs = build_reduce_messages([{"chapter_name": "a", "summary": "s"}], meta, "中文")
    assert len(msgs) == 2 and msgs[1]["content"]
    print("✅ breakdown prompts (null meta 字段) 不再 TypeError")


# ===== API 级：null meta / 幽灵目录 / PPT 文件名 / request-id =====

class TestRobustnessFixes(E2ETestBase):

    def _corrupt_meta(self, paper_id: str, **overrides):
        """把已上传论文的 text.json meta 字段改成显式 null（模拟损坏/旧数据）"""
        from app.utils.storage import load_text_json
        data = load_text_json(paper_id) or {}
        data.setdefault("meta", {})
        for k, v in overrides.items():
            data["meta"][k] = v
        save_text_json(paper_id, data)

    def test_compare_papers_with_null_abstract(self):
        """/api/compare-papers - 两篇论文 abstract 均为 null → 不 500"""
        from app.services.llm_client import LLMClient
        from unittest.mock import AsyncMock

        pid_a = self._upload_pdf()
        pid_b = self._upload_docx()
        self._corrupt_meta(pid_a, abstract=None, title=None)
        self._corrupt_meta(pid_b, abstract=None)

        mock = AsyncMock(return_value=MOCK_COMPARE)
        with patch.object(LLMClient, "chat_json", new=mock):
            res = self.client.post(
                "/api/compare-papers",
                json={"paper_ids": [pid_a, pid_b], "main_id": pid_a},
                headers=HEADERS,
            )
        self.assertEqual(res.status_code, 200, f"null abstract 不应 500，实际: {res.text}")
        self.assertEqual(res.json()["code"], 0)
        print("✅ compare-papers (null abstract) → 200")

    def test_upload_save_text_json_failure_cleans_up(self):
        """save_text_json 失败（磁盘满等）→ 500 且不留幽灵目录"""
        paper_dir_before = set(Path(settings.papers_dir).iterdir()) \
            if Path(settings.papers_dir).exists() else set()

        from test_e2e import create_sample_pdf, upload_via_client
        with patch("app.api.upload.save_text_json", side_effect=OSError("disk full")):
            res = upload_via_client(self.client, create_sample_pdf(), "p.pdf", headers=HEADERS)

        self.assertEqual(res.status_code, 500, f"落盘失败应 500，实际 {res.status_code}: {res.text}")
        self.assertIn("保存解析结果失败", res.json()["message"])

        # 幽灵目录断言：papers 目录里不能出现只有 raw.* 没有 text.json 的新目录
        paper_dir_after = set(Path(settings.papers_dir).iterdir()) \
            if Path(settings.papers_dir).exists() else set()
        new_dirs = paper_dir_after - paper_dir_before
        for d in new_dirs:
            files = {f.name for f in d.iterdir()}
            self.assertFalse(
                "text.json" not in files and files,
                f"幽灵目录残留: {d.name} -> {files}",
            )
        print("✅ upload (save_text_json 失败) → 500 + 目录已清理")

    def test_ppt_filename_with_null_or_empty_title(self):
        """PPT 文件名：null 标题不 TypeError，空标题不用 '_汇报' 畸形名"""
        paper_id = self._upload_pdf()
        # 写入一份 breakdown 结果（PPT 生成的前提）
        from app.utils.storage import save_analysis_result
        save_analysis_result(paper_id, "breakdown", {
            "summary": "s", "background": "b", "goal": "g",
            "method": "m", "experiment": "e", "conclusion": "c",
            "key_points": [], "quotes": [],
        })
        self._corrupt_meta(paper_id, title=None)

        res = self.client.post(
            "/api/generate-ppt",
            json={"paper_id": paper_id},
            headers=HEADERS,
        )
        self.assertEqual(res.status_code, 200, f"null title 不应 500，实际: {res.text}")
        filename = res.json()["data"]["filename"]
        # save_ppt 的命名格式是 {paper_id}_{safe_title}_汇报.pptx；
        # null 标题应兜底为 "paper"（畸形名是 "_汇报"），且不抛 TypeError
        self.assertIn("paper_汇报", filename, f"空标题应用 paper 兜底，实际: {filename}")
        self.assertNotIn("__汇报", filename)
        print(f"✅ generate-ppt (null title) → 200, filename={filename}")

    def test_request_id_invalid_input_replaced(self):
        """非法 X-Request-ID（超长/非法字符）被替换为服务端生成的合法 id"""
        for bad in ("a" * 200, "bad id with spaces", "<script>alert(1)</script>"):
            res = self.client.get("/api/health", headers={"X-Request-ID": bad})
            rid = res.headers.get("X-Request-ID", "")
            self.assertTrue(
                re.fullmatch(r"[A-Za-z0-9\-_]{8,64}", rid),
                f"非法输入 {bad[:20]!r} 应被替换为合法 id，实际响应头: {rid!r}",
            )
        # 合法输入应原样保留（跨服务追踪场景）
        res = self.client.get("/api/health", headers={"X-Request-ID": "trace-id-12345"})
        self.assertEqual(res.headers.get("X-Request-ID"), "trace-id-12345")
        print("✅ X-Request-ID 清洗：非法替换、合法保留")

    def test_ppt_filename_with_null_authors(self):
        """PPT 标题页 authors=null 不 500（复查发现的同族缺口）"""
        paper_id = self._upload_pdf()
        from app.utils.storage import save_analysis_result
        save_analysis_result(paper_id, "breakdown", {
            "summary": "s", "background": "b", "goal": "g",
            "method": "m", "experiment": "e", "conclusion": "c",
            "key_points": [], "quotes": [],
        })
        self._corrupt_meta(paper_id, authors=None)

        res = self.client.post(
            "/api/generate-ppt",
            json={"paper_id": paper_id},
            headers=HEADERS,
        )
        self.assertEqual(res.status_code, 200, f"null authors 不应 500，实际: {res.text}")
        print("✅ generate-ppt (null authors) → 200")

    def test_get_analysis_corrupt_json_returns_500(self):
        """analysis_*.json 损坏 → 500（数据问题），而非 400（请求问题）"""
        paper_id = self._upload_pdf()
        from app.utils.storage import get_paper_dir
        (get_paper_dir(paper_id) / "analysis_breakdown.json").write_text(
            "{corrupted!!", encoding="utf-8"
        )
        res = self.client.get(f"/api/analyze/{paper_id}/breakdown", headers=HEADERS)
        self.assertEqual(res.status_code, 500, f"损坏 JSON 应 500，实际 {res.status_code}: {res.text}")
        self.assertIn("损坏", res.json()["message"])
        print("✅ get_analysis (损坏 JSON) → 500 + 可读文案")


# ===== /docs 生产收敛（复查 N1：中间件拦不住非 /api 路径，必须在路由注册层关闭） =====

def test_schema_urls_gated_by_env(monkeypatch):
    """prod 下 docs/redoc/openapi 全部关闭，dev 下照常注册"""
    from app import main as main_mod

    monkeypatch.setattr(main_mod.settings, "app_env", "prod")
    assert main_mod._schema_urls() == {
        "docs_url": None, "redoc_url": None, "openapi_url": None,
    }

    monkeypatch.setattr(main_mod.settings, "app_env", "dev")
    urls = main_mod._schema_urls()
    assert urls["docs_url"] == "/docs"
    assert urls["openapi_url"] == "/openapi.json"
    print("✅ _schema_urls: prod 关闭 schema 页面、dev 正常注册")
