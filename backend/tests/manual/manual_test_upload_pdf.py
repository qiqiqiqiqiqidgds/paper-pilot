"""
PDF 上传端到端手动测试
=========================

目标：把 `data/papers/test_samples/transformer_sample.pdf` 真的走一遍完整
upload pipeline（TestClient in-process，无 uvicorn），验证：

  1. 上传成功 + 返回元数据正确
  2. 解析后 text.json 包含 toc / pages / meta
  3. list / detail / file / analyze 端点都正常
  4. 清理：测试完后论文目录被删掉

运行：
    cd backend
    venv/Scripts/python -m tests.manual.manual_test_upload_pdf     # Windows
    python -m tests.manual.manual_test_upload_pdf                  # 已激活 venv
    # 或直接：python tests/manual/manual_test_upload_pdf.py

注意：本文件是手动脚本（不以 test_ 开头），pytest 不会收集；pytest.ini 仅收集 test_*.py。

与 test_e2e.py 的区别：
  - test_e2e.py 走的是 in-memory 字节流（create_sample_pdf() 拼出来的）
  - 本脚本用磁盘上真实存在的 PDF 文件 → 更接近前端 fetch 上传的真实路径
"""
import json
import os
import shutil
import sys
import traceback
from pathlib import Path
from unittest.mock import AsyncMock, patch

# 让 Windows GBK 终端也能正确输出 emoji
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ====== env var 必须在 import settings/app 之前注入 ======
# 和 test_e2e.py 保持一致，避免 settings.auth_enabled 状态在不同文件里不一致
os.environ.setdefault("APP_API_KEY", "manual-test-api-key-2026")
os.environ.setdefault("RATE_LIMIT_GENERAL_PER_MIN", "200")
os.environ.setdefault("RATE_LIMIT_EXPENSIVE_PER_MIN", "10")
os.environ.setdefault("LLM_API_KEY", "")  # 显式置空，强制走 mock 分支（兼容老 DEEPSEEK_API_KEY 别名）
os.environ.setdefault("TAVILY_API_KEY", "")

# 让能找到 app 包
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient

from app.main import app
from app.services.llm_client import LLMClient
from app.utils.ratelimit import RateLimitMiddleware
from app.utils.storage import delete_paper, get_paper_dir

# ====== 常量 ======
API_KEY = "manual-test-api-key-2026"
HEADERS = {"X-API-Key": API_KEY}
SAMPLE_PDF = BACKEND_DIR / "data" / "papers" / "test_samples" / "transformer_sample.pdf"
PAPERS_DIR = BACKEND_DIR / "data" / "papers"
GITKEEP_NAME = ".gitkeep"
TEST_SAMPLES_DIR = "test_samples"  # 已提交进仓库的测试样本目录，清理时须跳过


# ====== 简单结果收集 ======
class ResultRecorder:
    def __init__(self):
        self.steps = []  # [(name, ok, detail), ...]
        self.bugs = []   # [(severity, description, repro), ...]

    def ok(self, name, detail=""):
        self.steps.append((name, True, detail))
        print(f"✅ {name}{(' — ' + detail) if detail else ''}")

    def fail(self, name, detail=""):
        self.steps.append((name, False, detail))
        print(f"❌ {name}{(' — ' + detail) if detail else ''}")

    def bug(self, severity, desc, repro):
        self.bugs.append((severity, desc, repro))
        print(f"🐛 [BUG-{severity}] {desc}\n   复现: {repro}")


def ensure_sample_pdf() -> bool:
    """保证 sample PDF 存在，不在就跑 test_pdf_parser 生成一个。"""
    if SAMPLE_PDF.exists():
        print(f"📄 使用已有 sample PDF: {SAMPLE_PDF} ({SAMPLE_PDF.stat().st_size} bytes)")
        return True

    print(f"⚠️  sample PDF 不存在: {SAMPLE_PDF}")
    print("🔧 跑 test_pdf_parser 自动生成...")
    import subprocess
    res = subprocess.run(
        [sys.executable, "-m", "tests.test_pdf_parser"],
        cwd=str(BACKEND_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",  # 避免 GBK 解码失败打断测试
    )
    if res.returncode != 0:
        print("❌ 生成失败:")
        print(res.stdout)
        print(res.stderr)
        return False
    if not SAMPLE_PDF.exists():
        print("❌ 生成后仍找不到 sample PDF")
        return False
    print(f"✅ 已生成: {SAMPLE_PDF}")
    return True


def main():
    rec = ResultRecorder()
    client = TestClient(app)

    # ====== 前置：清空 papers 目录（保留 .gitkeep）+ 重置限流 ======
    if PAPERS_DIR.exists():
        for entry in PAPERS_DIR.iterdir():
            if entry.name == GITKEEP_NAME:
                continue
            if entry.name == TEST_SAMPLES_DIR:
                continue
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)
    else:
        PAPERS_DIR.mkdir(parents=True, exist_ok=True)
        (PAPERS_DIR / GITKEEP_NAME).touch()
    RateLimitMiddleware._buckets.clear()

    paper_id = None
    paper_dir = None
    try:
        # ====== Step 0: 保证 sample PDF 存在 ======
        if not ensure_sample_pdf():
            rec.fail("sample PDF 就绪", "test_pdf_parser 跑失败")
            return
        rec.ok("sample PDF 就绪", f"{SAMPLE_PDF.stat().st_size} bytes")
        pdf_size = SAMPLE_PDF.stat().st_size

        # ====== Step 1: 上传 ======
        print("\n--- Step 1: 上传 PDF ---")
        with open(SAMPLE_PDF, "rb") as f:
            res = client.post(
                "/api/upload",
                files={"file": ("test.pdf", f, "application/pdf")},
                headers=HEADERS,
            )
        if res.status_code != 200:
            rec.fail("POST /api/upload", f"status={res.status_code}, body={res.text[:300]}")
            return
        rec.ok("POST /api/upload", "HTTP 200")

        body = res.json()
        data = body.get("data") or {}
        paper_id = data.get("paper_id")
        if not paper_id:
            rec.fail("上传响应包含 paper_id", f"resp={json.dumps(data, ensure_ascii=False)[:300]}")
            return

        meta_summary = {
            "paper_id": paper_id,
            "filename": data.get("filename"),
            "size": data.get("size"),
            "pages": data.get("pages"),
            "file_type": data.get("file_type"),
            "title": (data.get("title") or "")[:60],
            "authors_count": len(data.get("authors") or []),
            "abstract_len": len(data.get("abstract") or ""),
        }
        print(f"   返回元数据: {json.dumps(meta_summary, ensure_ascii=False)}")
        rec.ok("返回 paper_id", paper_id)

        # 验证元数据
        if data.get("file_type") != "pdf":
            rec.bug("MEDIUM", f"file_type 应为 'pdf'，实际 {data.get('file_type')!r}",
                    f"上传 {SAMPLE_PDF}，检查 data['file_type']")
        else:
            rec.ok("file_type == 'pdf'", "pdf")

        if not (data.get("size") and data["size"] > 0):
            rec.bug("HIGH", f"size 应 > 0，实际 {data.get('size')!r}",
                    "上传任意有效 PDF")
        elif data["size"] != pdf_size:
            # 文件本身有变化算 BUG（说明 server 端读到的字节数与磁盘不一致）
            rec.bug("MEDIUM",
                    f"上传 size ({data['size']}) != 磁盘文件大小 ({pdf_size})",
                    f"上传 {SAMPLE_PDF}，对比 data['size'] vs stat().st_size")
        else:
            rec.ok("size 一致", f"{data['size']} bytes")

        if not (data.get("pages") and data["pages"] > 0):
            rec.bug("HIGH", f"pages 应 > 0，实际 {data.get('pages')!r}",
                    "上传 sample PDF，pages 字段为 0 或缺失")
        else:
            rec.ok("pages > 0", f"{data['pages']} 页")

        # 标题非空
        if not (data.get("title") and data["title"].strip()):
            rec.bug("LOW", f"title 为空: {data.get('title')!r}", "上传 sample PDF")
        else:
            rec.ok("title 非空", data["title"][:40])

        # 论文目录已生成
        paper_dir = get_paper_dir(paper_id).resolve()
        if not paper_dir.exists():
            rec.bug("HIGH", f"论文目录未创建: {paper_dir}",
                    f"上传后检查 {paper_dir}")
        else:
            rec.ok("论文目录已创建", str(paper_dir.relative_to(BACKEND_DIR.resolve())))

        # ====== Step 2: 解析结果 text.json ======
        print("\n--- Step 2: 解析结果 ---")
        text_json = paper_dir / "text.json"
        if not text_json.exists():
            rec.bug("HIGH", f"text.json 未生成: {text_json}",
                    "上传后检查 paper_dir/text.json")
        else:
            try:
                parsed = json.loads(text_json.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                rec.bug("HIGH", f"text.json JSON 解析失败: {e}",
                        f"读 {text_json}")
                parsed = {}

            has_meta = "meta" in parsed and isinstance(parsed["meta"], dict)
            has_pages = "page_count" in parsed and parsed["page_count"] > 0
            has_toc = "toc" in parsed and isinstance(parsed["toc"], list)
            has_full_text = "full_text" in parsed and len(parsed["full_text"]) > 0
            has_pages_list = "pages" in parsed and isinstance(parsed["pages"], list)

            print(f"   text.json 字段: meta={has_meta}, page_count={parsed.get('page_count')}, "
                  f"toc={'YES('+str(len(parsed.get('toc', [])))+' 项)' if has_toc else 'NO'}, "
                  f"pages={len(parsed.get('pages', [])) if has_pages_list else 0}, "
                  f"full_text_len={len(parsed.get('full_text', ''))}")

            if has_meta:
                rec.ok("text.json 含 meta", str(list(parsed['meta'].keys())))
            else:
                rec.bug("HIGH", "text.json 缺少 meta 字段", f"读 {text_json}")

            if has_pages:
                rec.ok("text.json 含 page_count", f"{parsed['page_count']} 页")
            else:
                rec.bug("HIGH", f"text.json page_count 异常: {parsed.get('page_count')!r}",
                        f"读 {text_json}")

            if has_toc:
                rec.ok("text.json 含 toc", f"{len(parsed['toc'])} 项")
            else:
                rec.bug("MEDIUM", "text.json 缺少 toc 或为空（PDF 应有目录）",
                        f"读 {text_json}")

            if has_pages_list:
                rec.ok("text.json 含 pages 列表", f"{len(parsed['pages'])} 页详情")
            else:
                rec.bug("MEDIUM", "text.json 缺少 pages 列表", f"读 {text_json}")

            if has_full_text:
                rec.ok("text.json 含 full_text", f"{len(parsed['full_text'])} 字符")
            else:
                rec.bug("HIGH", "text.json 缺少 full_text 或为空", f"读 {text_json}")

        # ====== Step 3: GET /api/papers 列表 ======
        print("\n--- Step 3: 列表查询 ---")
        res = client.get("/api/papers", headers=HEADERS)
        if res.status_code != 200:
            rec.fail("GET /api/papers", f"status={res.status_code}, body={res.text[:200]}")
        else:
            items = res.json().get("data", {}).get("items", [])
            ids = {it.get("paper_id") for it in items}
            if paper_id in ids:
                rec.ok("GET /api/papers 找到刚上传的", f"total={len(items)}")
            else:
                rec.bug("HIGH",
                        f"刚上传的 paper_id={paper_id} 不在列表中",
                        f"上传后立即 GET /api/papers, 实际 ids={ids}")
                rec.fail("GET /api/papers 找到刚上传的", "missing")

        # ====== Step 4: GET /api/papers/{id} 详情 ======
        print("\n--- Step 4: 详情 ---")
        res = client.get(f"/api/papers/{paper_id}", headers=HEADERS)
        if res.status_code != 200:
            rec.fail("GET /api/papers/{id}", f"status={res.status_code}, body={res.text[:200]}")
        else:
            d = res.json().get("data") or {}
            if d.get("page_count", 0) > 0:
                rec.ok("GET /api/papers/{id}", f"page_count={d.get('page_count')}, "
                    f"full_text_length={d.get('full_text_length')}")
            else:
                rec.bug("HIGH",
                        f"详情 page_count={d.get('page_count')}",
                        f"GET /api/papers/{paper_id}")
                rec.fail("GET /api/papers/{id}", "page_count 异常")

        # ====== Step 5: GET /api/papers/{id}/file 下载 ======
        print("\n--- Step 5: 文件下载 ---")
        res = client.get(f"/api/papers/{paper_id}/file", headers=HEADERS)
        if res.status_code != 200:
            rec.fail("GET /api/papers/{id}/file", f"status={res.status_code}, body={res.text[:200]}")
        else:
            content_type = res.headers.get("content-type", "")
            content_disp = res.headers.get("content-disposition", "")
            downloaded_size = len(res.content)
            print(f"   content-type: {content_type}")
            print(f"   content-disposition: {content_disp}")
            print(f"   downloaded_size: {downloaded_size} bytes (原始 {pdf_size} bytes)")

            if content_type != "application/pdf":
                rec.bug("MEDIUM",
                        f"下载 content-type 异常: {content_type!r} (期望 application/pdf)",
                        f"GET /api/papers/{paper_id}/file")
            else:
                rec.ok("下载 content-type", "application/pdf")

            if downloaded_size != pdf_size:
                rec.bug("HIGH",
                        f"下载字节数 ({downloaded_size}) != 原始 ({pdf_size})",
                        f"GET /api/papers/{paper_id}/file 后 len(res.content)")
            else:
                rec.ok("下载字节数一致", f"{downloaded_size} bytes")

            # 验证 magic number（真的 PDF，不是损坏的）
            if not res.content.startswith(b"%PDF"):
                rec.bug("HIGH",
                        "下载内容 magic number 不是 %PDF，可能损坏或被改写",
                        "下载后检查 res.content[:4]")
            else:
                rec.ok("下载内容 magic number 正确", "%PDF-...")

        # ====== Step 6: analyze 端点（mock LLM） ======
        print("\n--- Step 6: analyze 端点（mock LLM） ---")
        MOCK_INNOVATION = {
            "core_innovations": [{"title": "manual-test", "description": "x", "page_ref": 1}],
            "innovation_level": "disruptive",
            "level_reasoning": "manual",
            "applicable_scenarios": ["test"],
            "quotes": [],
        }
        try:
            # 重要：必须 patch 的是被调用方的属性，而不是参数路径上 import 的本地引用。
            # endpoint 用 `from ... import LLMClient`，每次调用仍走 LLMClient 类上的方法。
            with patch.object(LLMClient, "chat_json", new=AsyncMock(return_value=MOCK_INNOVATION)):
                res = client.post(
                    "/api/analyze",
                    json={"paper_id": paper_id, "type": "innovation"},
                    headers=HEADERS,
                )
            if res.status_code != 200:
                rec.bug("HIGH",
                        f"analyze innovation 失败: status={res.status_code}, body={res.text[:200]}",
                        "POST /api/analyze (mock LLM)")
                rec.fail("POST /api/analyze", f"status={res.status_code}")
            else:
                aj = res.json()
                aj_code = aj.get("code")
                aj_data = aj.get("data") or {}
                # analyze 走代码 0 表示真正成功；有些项目里 business fail 也可能 code!=0
                if aj_code == 0 and aj_data.get("type") == "innovation":
                    rec.ok("POST /api/analyze (innovation)",
                           f"elapsed_ms={aj_data.get('elapsed_ms')}, "
                           f"core_innovations={len(aj_data.get('result', {}).get('core_innovations', []))}")
                else:
                    rec.bug("MEDIUM",
                            f"analyze 返回结构异常: code={aj_code}, data={json.dumps(aj_data, ensure_ascii=False)[:200]}",
                            "POST /api/analyze (mock LLM)")
                    rec.fail("POST /api/analyze", "结构异常")
        except Exception as e:
            rec.fail("POST /api/analyze", f"异常: {e}")
            traceback.print_exc()

        # ====== Step 7: analyze 缓存读取 ======
        print("\n--- Step 7: analyze 缓存读取 ---")
        res = client.get(f"/api/analyze/{paper_id}/innovation", headers=HEADERS)
        if res.status_code == 200:
            rec.ok("GET /api/analyze/{id}/innovation (缓存)", "200")
        else:
            # 不算 BUG：endpoint 可能用别的路径或文件名；但要看 body 提示什么
            rec.fail("GET /api/analyze/{id}/innovation",
                     f"status={res.status_code}, body={res.text[:200]}")
            rec.bug("MEDIUM",
                    f"analyze 缓存读取失败: {res.status_code}",
                    "先 POST /api/analyze 生成，再 GET /api/analyze/{id}/{type}")

        # ====== Step 8: 清理 ======
        print("\n--- Step 8: 清理 ---")
        # 用 API 删
        res = client.delete(f"/api/papers/{paper_id}", headers=HEADERS)
        if res.status_code != 200:
            rec.bug("HIGH",
                    f"DELETE /api/papers/{id} 失败: status={res.status_code}, body={res.text[:200]}",
                    f"DELETE /api/papers/{paper_id}")
            rec.fail("DELETE /api/papers/{id}", f"status={res.status_code}")
        else:
            rec.ok("DELETE /api/papers/{id}", "200")

        # 再次 GET 应 404
        res = client.get(f"/api/papers/{paper_id}", headers=HEADERS)
        if res.status_code == 404:
            rec.ok("删除后 GET → 404", "确认已清理")
        else:
            rec.bug("MEDIUM",
                    f"删除后 GET 仍返回 {res.status_code}",
                    f"DELETE 之后 GET /api/papers/{paper_id}")

        # 磁盘上 paper_dir 应不存在
        if paper_dir and paper_dir.exists():
            rec.bug("HIGH",
                    f"论文目录未被删除: {paper_dir}",
                    "DELETE 后检查 paper_dir.exists()")
        else:
            rec.ok("论文目录已从磁盘删除", "✅")
            paper_dir = None  # 防止 finally 再删一次报错

    finally:
        # 兜底清理：万一 API 删失败，磁盘上必须删干净
        if paper_dir and paper_dir.exists():
            try:
                shutil.rmtree(paper_dir)
                print(f"🧹 兜底删除: {paper_dir}")
            except Exception as e:
                print(f"⚠️  兜底删除失败: {e}")
        if paper_id:
            try:
                delete_paper(paper_id)  # 删可能残留的 PPT
            except Exception:
                pass

    # ====== 汇总报告 ======
    print("\n" + "=" * 60)
    print("📊 测试结果汇总")
    print("=" * 60)
    ok_count = sum(1 for _, ok, _ in rec.steps if ok)
    fail_count = len(rec.steps) - ok_count
    print(f"通过: {ok_count} / {len(rec.steps)}")
    print(f"失败: {fail_count}")
    print(f"BUG:  {len(rec.bugs)}")

    if rec.bugs:
        print("\n🐛 发现的 BUG:")
        for sev, desc, repro in rec.bugs:
            print(f"  [{sev}] {desc}")
            print(f"      复现: {repro}")
    else:
        print("\n✨ 没有发现 BUG")

    print("\n" + "=" * 60)
    print("步骤明细:")
    for name, ok, detail in rec.steps:
        mark = "✅" if ok else "❌"
        print(f"  {mark} {name}{(' — ' + detail) if detail else ''}")

    # exit code: 有 BUG 或失败步骤就非零
    sys.exit(1 if (fail_count or rec.bugs) else 0)


if __name__ == "__main__":
    main()
