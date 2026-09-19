"""
DOCX 上传端到端测试（重点：走通真实 DOCX + Content-Type 正确性）

用 FastAPI TestClient 跑完整 upload → list → get → download 流程，
验证：
  1. 上传成功 + 元数据正确（file_type=docx, size>0, pages>0）
  2. 列表 / 详情接口正常
  3. 下载时 Content-Type 是 wordprocessingml
  4. 下载时 Content-Disposition 是 attachment + 原始文件名
  5. 清理：删除上传的论文

运行：
    cd backend
    python -m tests.manual.manual_test_upload_docx
    # 或直接：python tests/manual/manual_test_upload_docx.py

注意：本文件是手动脚本（不以 test_ 开头），pytest 不会收集；pytest.ini 仅收集 test_*.py。
"""
import os
import sys
from pathlib import Path

# Windows GBK 终端也能正确输出 emoji
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ====== 关键：env var 必须在 import settings/app 之前注入 ======
# (pydantic_settings 只在 import 时读一次)
os.environ.setdefault("APP_API_KEY", "manual-test-api-key-2026")
os.environ.setdefault("RATE_LIMIT_GENERAL_PER_MIN", "200")
os.environ.setdefault("RATE_LIMIT_EXPENSIVE_PER_MIN", "10")
os.environ.setdefault("LLM_API_KEY", "")             # 兼容老 DEEPSEEK_API_KEY 别名
os.environ.setdefault("TAVILY_API_KEY", "")

# 让能找到 app 包
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.utils.ratelimit import RateLimitMiddleware


API_KEY = "manual-test-api-key-2026"
HEADERS = {"X-API-Key": API_KEY}
DOCX_PATH = BACKEND_DIR / "data" / "papers" / "test_samples" / "transformer_sample.docx"
PAPERS_DIR = BACKEND_DIR / "data" / "papers"
GITKEEP_NAME = ".gitkeep"
TEST_SAMPLES_DIR = "test_samples"  # 已提交进仓库的测试样本目录，清理时须跳过


def _hr(title: str) -> None:
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)


def _ensure_sample_docx() -> Path:
    """确保 sample DOCX 存在；不在则用 python-docx 现场造一个"""
    if DOCX_PATH.exists():
        print(f"✓ 找到 sample DOCX: {DOCX_PATH} ({DOCX_PATH.stat().st_size} bytes)")
        return DOCX_PATH

    print(f"⚠️  sample DOCX 不存在: {DOCX_PATH}，正在生成...")
    try:
        from docx import Document
    except ImportError:
        print("❌ 需要 python-docx: pip install python-docx")
        sys.exit(1)

    DOCX_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc = Document()
    doc.add_heading("Attention Is All You Need", level=1)
    doc.add_paragraph("Ashish Vaswani, Noam Shazeer, Niki Parmar, Jakob Uszkoreit, Llion Jones")
    doc.add_paragraph("Abstract")
    doc.add_paragraph(
        "We propose a new simple network architecture, the Transformer, "
        "based solely on attention mechanisms, dispensing with recurrence "
        "and convolutions entirely."
    )
    doc.add_paragraph("Keywords: attention, transformer, neural networks")
    doc.add_heading("1 Introduction", level=1)
    doc.add_paragraph("RNNs suffer from sequential computation which prevents parallelization.")
    doc.add_heading("2 Method", level=1)
    doc.add_paragraph("The Transformer follows an encoder-decoder structure.")
    for i in range(30):
        doc.add_paragraph(f"Filler paragraph {i+1} to span multiple pages.")
    doc.add_heading("3 Experiments", level=1)
    doc.add_paragraph("WMT 2014 English-to-German translation task: 28.4 BLEU.")
    doc.add_heading("4 Conclusion", level=1)
    doc.add_paragraph("We presented the Transformer based entirely on attention.")
    doc.save(str(DOCX_PATH))
    print(f"✓ 已生成: {DOCX_PATH} ({DOCX_PATH.stat().st_size} bytes)")
    return DOCX_PATH


def _clean_papers() -> None:
    """清空 data/papers/（保留 .gitkeep）"""
    if PAPERS_DIR.exists():
        for entry in PAPERS_DIR.iterdir():
            if entry.name == GITKEEP_NAME:
                continue
            if entry.name == TEST_SAMPLES_DIR:
                continue
            if entry.is_dir():
                import shutil
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)


def _reset_rate_limit() -> None:
    RateLimitMiddleware._buckets.clear()


def main() -> int:
    print("\n" + "🚀" * 20)
    print("PaperPilot DOCX 上传端到端测试")
    print("🚀" * 20)

    # 0. 前置检查
    _hr("0. 前置检查")
    assert settings.app_api_key == API_KEY, f"APP_API_KEY 未生效: {settings.app_api_key!r}"
    assert settings.auth_enabled is True, "鉴权应启用"
    print(f"  ✓ APP_API_KEY 已注入: {API_KEY}")
    print(f"  ✓ auth_enabled = {settings.auth_enabled}")
    print(f"  ✓ papers_dir   = {settings.papers_dir}")
    print(f"  ✓ data_dir     = {settings.data_dir}")

    # 0.5 清理环境 + 重置限流
    _clean_papers()
    _reset_rate_limit()

    # 0.7 sample DOCX
    _hr("0.7 准备 sample DOCX")
    docx_path = _ensure_sample_docx()

    # 1. 创建 TestClient
    client = TestClient(app)

    # ===== 1. 上传 =====
    _hr("1. POST /api/upload  (上传 DOCX)")
    with open(docx_path, "rb") as f:
        res = client.post(
            "/api/upload",
            files={"file": ("test.docx", f,
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            headers=HEADERS,
        )
    print(f"  HTTP {res.status_code}")
    print(f"  Body: {res.text[:300]}{'...' if len(res.text) > 300 else ''}")

    assert res.status_code == 200, f"上传失败: {res.status_code} {res.text}"
    body = res.json()
    assert body["code"] == 0, f"code 应为 0，实际 {body['code']}"
    data = body["data"]
    paper_id = data["paper_id"]
    print(f"  ✓ paper_id = {paper_id}")
    print(f"  ✓ file_type = {data['file_type']!r}")
    print(f"  ✓ filename  = {data['filename']!r}")
    print(f"  ✓ size      = {data['size']} bytes")
    print(f"  ✓ pages     = {data['pages']}")
    print(f"  ✓ title     = {data['title']!r}")
    print(f"  ✓ authors   = {data['authors']}")
    print(f"  ✓ uploaded_at = {data['uploaded_at']}")

    # 1.5 验证元数据
    assert data["file_type"] == "docx", \
        f"❌ file_type 应该是 'docx'，实际 {data['file_type']!r}"
    assert data["size"] > 0, f"❌ size 应 > 0，实际 {data['size']}"
    assert data["pages"] > 0, f"❌ pages 应 > 0（伪页），实际 {data['pages']}"
    assert data["filename"] == "test.docx", f"❌ filename 不匹配: {data['filename']!r}"
    assert len(data["title"]) > 0, f"❌ title 应非空，实际 {data['title']!r}"
    print("  ✅ 元数据全部正确")

    # ===== 1.6 验证 text.json 解析结果（含 toc / pages / meta）=====
    _hr("1.6 校验解析结果 (text.json)")
    import json
    text_json_path = PAPERS_DIR / paper_id / "text.json"
    assert text_json_path.exists(), f"❌ text.json 不存在: {text_json_path}"
    parsed = json.loads(text_json_path.read_text(encoding="utf-8"))
    print(f"  ✓ text.json 存在: {text_json_path}")

    # 关键字段
    assert "meta" in parsed, "❌ parsed 应含 'meta'"
    assert "toc" in parsed, "❌ parsed 应含 'toc'"
    assert "pages" in parsed, "❌ parsed 应含 'pages'"
    assert "page_count" in parsed, "❌ parsed 应含 'page_count'"
    assert "full_text" in parsed, "❌ parsed 应含 'full_text'"
    assert "original_filename" in parsed, "❌ parsed 应含 'original_filename'"

    print(f"  ✓ meta.title         = {parsed['meta'].get('title')!r}")
    print(f"  ✓ meta.authors       = {parsed['meta'].get('authors')}")
    print(f"  ✓ toc 条数           = {len(parsed['toc'])}")
    print(f"  ✓ pages (伪页) 条数  = {len(parsed['pages'])}")
    print(f"  ✓ page_count         = {parsed['page_count']}")
    print(f"  ✓ full_text 长度     = {len(parsed['full_text'])} 字符")
    print(f"  ✓ original_filename  = {parsed['original_filename']!r}")

    # toc / pages 必须非空
    assert len(parsed["toc"]) > 0, f"❌ toc 应非空，实际 {len(parsed['toc'])} 条"
    assert len(parsed["pages"]) > 0, f"❌ pages 应非空，实际 {len(parsed['pages'])} 条"
    # meta.title 应非空
    assert len(parsed["meta"].get("title", "")) > 0, "❌ meta.title 应非空"
    # original_filename 应还原
    assert parsed["original_filename"] == "test.docx", \
        f"❌ original_filename 应为 'test.docx'，实际 {parsed['original_filename']!r}"
    print("  ✅ 解析结果完整（meta/toc/pages/page_count/full_text）")

    # 打印 toc 前 3 条
    print("  toc 前 3 条:")
    for entry in parsed["toc"][:3]:
        print(f"    [L{entry[0]}] {entry[1]} (P{entry[2]})")
    print("  pages 第 1 页前 100 字符:")
    print(f"    {parsed['pages'][0]['text'][:100].replace(chr(10), ' ')}...")

    # ===== 2. 列表能查到 =====
    _hr("2. GET /api/papers  (列表)")
    res = client.get("/api/papers", headers=HEADERS)
    print(f"  HTTP {res.status_code}")
    assert res.status_code == 200, f"列表应 200，实际 {res.status_code}"
    list_data = res.json()["data"]
    print(f"  total = {list_data['total']}")
    print(f"  items = {list_data['items']}")
    found = any(p["paper_id"] == paper_id for p in list_data["items"])
    assert found, f"❌ 列表里找不到刚上传的 paper_id={paper_id}"
    print("  ✅ 列表能找到刚上传的论文")

    # ===== 3. 详情 =====
    _hr(f"3. GET /api/papers/{paper_id}  (详情)")
    res = client.get(f"/api/papers/{paper_id}", headers=HEADERS)
    print(f"  HTTP {res.status_code}")
    assert res.status_code == 200, f"详情应 200，实际 {res.status_code}: {res.text}"
    detail = res.json()["data"]
    print(f"  ✓ paper_id          = {detail['paper_id']}")
    print(f"  ✓ filename          = {detail['filename']!r}")
    print(f"  ✓ file_type         = {detail['file_type']!r}")
    print(f"  ✓ size              = {detail['size']}")
    print(f"  ✓ page_count        = {detail['page_count']}")
    print(f"  ✓ full_text_length  = {detail['full_text_length']}")
    print(f"  ✓ meta.title        = {detail['meta'].get('title')!r}")
    assert detail["file_type"] == "docx", \
        f"❌ 详情 file_type 应为 'docx'，实际 {detail['file_type']!r}"
    assert detail["full_text_length"] > 0, "❌ full_text_length 应 > 0"
    print("  ✅ 详情正确")

    # ===== 4. 下载文件 =====
    _hr(f"4. GET /api/papers/{paper_id}/file  (下载 - 重点验证)")
    res = client.get(f"/api/papers/{paper_id}/file", headers=HEADERS)
    print(f"  HTTP {res.status_code}")
    print(f"  Content-Type        = {res.headers.get('content-type')!r}")
    print(f"  Content-Disposition = {res.headers.get('content-disposition')!r}")
    print(f"  Content-Length      = {res.headers.get('content-length', '(chunked)')!r}")
    print(f"  Body 字节数         = {len(res.content)}")

    assert res.status_code == 200, f"下载应 200，实际 {res.status_code}: {res.text}"
    assert "wordprocessingml" in res.headers["content-type"], \
        f"❌ Content-Type 应含 'wordprocessingml'，实际 {res.headers['content-type']!r}"
    cd = res.headers.get("content-disposition", "")
    assert "attachment" in cd, f"❌ Content-Disposition 应含 'attachment'，实际 {cd!r}"
    assert "test.docx" in cd, \
        f"❌ Content-Disposition 应含 'test.docx'（原始文件名），实际 {cd!r}"
    assert len(res.content) > 1000, f"❌ 下载内容应 > 1KB，实际 {len(res.content)}"
    # zip magic header (PK\x03\x04) — DOCX 本质是 zip
    assert res.content[:2] == b"PK", \
        f"❌ DOCX 头两个字节应是 PK（zip 魔数），实际 {res.content[:4]!r}"
    print("  ✅ Content-Type = DOCX")
    print("  ✅ Content-Disposition = attachment + 原始文件名")
    print("  ✅ 内容是真实 DOCX（PK 头）")

    # ===== 5. 清理 =====
    _hr("5. DELETE /api/papers/{paper_id}  (清理)")
    res = client.delete(f"/api/papers/{paper_id}", headers=HEADERS)
    print(f"  HTTP {res.status_code}")
    assert res.status_code == 200, f"删除应 200，实际 {res.status_code}: {res.text}"
    body = res.json()
    print(f"  code={body['code']}, message={body['message']!r}")
    # 验证目录真的没了
    assert not (PAPERS_DIR / paper_id).exists(), \
        f"❌ 论文目录应被删除，实际还存在: {PAPERS_DIR / paper_id}"
    print("  ✅ 删除后目录已清理")

    # 再 GET 应 404
    res = client.get(f"/api/papers/{paper_id}", headers=HEADERS)
    assert res.status_code == 404, f"删除后 GET 应 404，实际 {res.status_code}"
    print("  ✅ 删除后 GET 详情 → 404")

    print()
    print("=" * 60)
    print("🎉 DOCX 上传全流程通过")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as e:
        print()
        print("=" * 60)
        print(f"❌ 测试失败: {e}")
        print("=" * 60)
        sys.exit(1)
    except Exception as e:
        print()
        print("=" * 60)
        print(f"❌ 异常: {e}")
        import traceback
        traceback.print_exc()
        print("=" * 60)
        sys.exit(1)
