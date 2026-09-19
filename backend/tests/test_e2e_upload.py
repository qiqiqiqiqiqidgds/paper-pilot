"""
E2E 上传 + 论文库 + 文件下载（Sprint 4 / R2 拆分）
- test_08 ~ test_20：上传校验 + 列表 + 详情 + 删除 + 文件下载
- test_21：带书签大纲（TOC）PDF 上传回归（P0-1）
"""
import io
import json

import fitz

from test_e2e import (
    E2ETestBase, HEADERS, PAPERS_DIR, create_sample_pdf, create_sample_docx, upload_via_client,
)


def create_sample_pdf_with_toc() -> bytes:
    """生成带书签大纲（TOC）的测试 PDF

    P0-1 回归样本：arXiv / IEEE 出版版学术 PDF 几乎都带书签（LaTeX hyperref 产物），
    此前 create_sample_pdf() 从不 set_toc，恰好漏掉了这条最常见链路。
    """
    doc = fitz.open()
    pages = [
        "Attention Is All You Need\nAshish Vaswani et al.\n\nAbstract\nWe propose Transformer, based solely on attention.\n",
        "2 Methods\nThe Transformer uses stacked self-attention layers.\n",
    ]
    for text in pages:
        page = doc.new_page(width=595, height=842)
        y = 50
        for line in text.split("\n"):
            if line.strip():
                page.insert_text((50, y), line, fontsize=11)
            y += 15
    doc.set_toc([[1, "Introduction", 1], [1, "Methods", 2], [2, "1.1 Detail", 2]])
    out = doc.tobytes()
    doc.close()
    return out


class TestUpload(E2ETestBase):
    """上传 / 列表 / 详情 / 删除 / 文件下载测试"""

    def test_08_upload_pdf(self):
        """POST /api/upload - PDF"""
        pdf_bytes = create_sample_pdf()
        res = upload_via_client(self.client, pdf_bytes, "test_paper.pdf")
        self.assertEqual(res.status_code, 200, f"PDF 上传应 200，实际 {res.status_code}: {res.text}")
        body = res.json()
        self.assertEqual(body["code"], 0)
        data = body["data"]
        self.assertIn("paper_id", data)
        self.assertEqual(data["file_type"], "pdf")
        self.assertEqual(data["filename"], "test_paper.pdf")
        self.assertGreater(data["pages"], 0)
        self.assertGreater(len(data["title"]), 0, f"标题应非空，实际 {data['title']!r}")
        print(f"✅ 上传 PDF → paper_id={data['paper_id'][:20]}..., pages={data['pages']}, title={data['title'][:40]!r}")

    def test_09_upload_docx(self):
        """POST /api/upload - DOCX"""
        docx_bytes = create_sample_docx()
        res = upload_via_client(self.client, docx_bytes, "test_paper.docx")
        self.assertEqual(res.status_code, 200, f"DOCX 上传应 200，实际 {res.status_code}: {res.text}")
        body = res.json()
        data = body["data"]
        self.assertEqual(data["file_type"], "docx")
        self.assertGreater(data["pages"], 0)
        self.assertIn("Attention", data["title"])
        print(f"✅ 上传 DOCX → paper_id={data['paper_id'][:20]}..., title={data['title'][:40]!r}")

    def test_10_upload_invalid_type(self):
        """上传 .txt → 400（业务校验，需先过鉴权）"""
        res = self.client.post(
            "/api/upload",
            files={"file": ("bad.txt", io.BytesIO(b"x" * 500), "text/plain")},
            headers=HEADERS,
        )
        self.assertEqual(res.status_code, 400, f"txt 应被拒，实际 {res.status_code}: {res.text}")
        body = res.json()
        # error_handler 把 HTTPException.detail 写入 "message" 字段（detail 恒为空）
        self.assertIn("PDF", body.get("message", ""))
        print(f"✅ 上传 .txt → 400, message: {body['message'][:50]}")

    def test_11_upload_too_small(self):
        """上传过小文件 → 400（业务校验，需先过鉴权）"""
        res = self.client.post(
            "/api/upload",
            files={"file": ("tiny.pdf", io.BytesIO(b"x" * 10), "application/pdf")},
            headers=HEADERS,
        )
        self.assertEqual(res.status_code, 400, f"过小文件应被拒，实际 {res.status_code}")
        print("✅ 过小文件 → 400")

    def test_12_list_papers_empty(self):
        """GET /api/papers - 空库"""
        res = self.client.get("/api/papers", headers=HEADERS)
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["code"], 0)
        self.assertEqual(body["data"]["total"], 0)
        self.assertEqual(body["data"]["items"], [])
        print("✅ GET /api/papers (空库) → total=0")

    def test_13_list_papers(self):
        """GET /api/papers - 列表（PDF + DOCX）"""
        pdf_id = self._upload_pdf()
        docx_id = self._upload_docx()
        res = self.client.get("/api/papers", headers=HEADERS)
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["data"]["total"], 2, f"应有 2 篇，实际 {body['data']['total']}")
        items = body["data"]["items"]
        ids = {it["paper_id"] for it in items}
        self.assertIn(pdf_id, ids)
        self.assertIn(docx_id, ids)
        types = {it["file_type"] for it in items}
        self.assertIn("pdf", types)
        self.assertIn("docx", types)
        for it in items:
            for k in ("has_breakdown", "has_innovation", "has_compare", "has_flaws"):
                self.assertIn(k, it)
        print("✅ GET /api/papers → 2 篇（PDF+DOCX），含 has_* 字段")

    def test_14_get_paper(self):
        """GET /api/papers/{id} - 详情"""
        paper_id = self._upload_pdf()
        res = self.client.get(f"/api/papers/{paper_id}", headers=HEADERS)
        self.assertEqual(res.status_code, 200, f"获取详情应 200，实际 {res.status_code}: {res.text}")
        body = res.json()
        data = body["data"]
        self.assertEqual(data["paper_id"], paper_id)
        self.assertIn("meta", data)
        self.assertIn("page_count", data)
        self.assertIn("full_text_length", data)
        self.assertGreater(data["full_text_length"], 0)
        self.assertEqual(data["file_type"], "pdf")
        print(f"✅ GET /api/papers/{paper_id[:20]}... → 200, pages={data['page_count']}, full_text_length={data['full_text_length']}")

    def test_15_get_paper_not_found(self):
        """GET /api/papers/{nonexistent} → 404"""
        res = self.client.get("/api/papers/p_2099_xxxxxx", headers=HEADERS)
        self.assertEqual(res.status_code, 404, f"不存在应 404，实际 {res.status_code}")
        print("✅ GET 不存在的论文 → 404")

    def test_16_delete_paper(self):
        """DELETE /api/papers/{id}"""
        paper_id = self._upload_pdf()
        res = self.client.delete(f"/api/papers/{paper_id}", headers=HEADERS)
        self.assertEqual(res.status_code, 200, f"删除应 200，实际 {res.status_code}: {res.text}")
        self.assertEqual(res.json()["code"], 0)
        res2 = self.client.get(f"/api/papers/{paper_id}", headers=HEADERS)
        self.assertEqual(res2.status_code, 404, "删除后 GET 应 404")
        self.assertFalse((PAPERS_DIR / paper_id).exists(), "论文目录应被删除")
        print(f"✅ DELETE /api/papers/{paper_id[:20]}... → 200, 之后 GET → 404")

    def test_17_delete_paper_not_found(self):
        """DELETE /api/papers/{nonexistent} → 404"""
        res = self.client.delete("/api/papers/p_2099_xxxxxx", headers=HEADERS)
        self.assertEqual(res.status_code, 404, f"删除不存在的应 404，实际 {res.status_code}")
        print("✅ DELETE 不存在的论文 → 404")

    def test_18_download_pdf(self):
        """GET /api/papers/{id}/file - PDF"""
        res = upload_via_client(self.client, create_sample_pdf(), "test_paper.pdf")
        paper_id = res.json()["data"]["paper_id"]

        res = self.client.get(f"/api/papers/{paper_id}/file", headers=HEADERS)
        self.assertEqual(res.status_code, 200, f"下载应 200，实际 {res.status_code}: {res.text}")
        self.assertEqual(res.headers["content-type"], "application/pdf")
        self.assertGreater(len(res.content), 1000, f"PDF 至少 1KB，实际 {len(res.content)}")
        self.assertIn("test_paper.pdf", res.headers.get("content-disposition", ""))
        print(f"✅ 下载 PDF → {len(res.content)} bytes, content-type={res.headers['content-type']}")

    def test_19_download_docx(self):
        """GET /api/papers/{id}/file - DOCX"""
        res = upload_via_client(self.client, create_sample_docx(), "test_paper.docx")
        paper_id = res.json()["data"]["paper_id"]

        res = self.client.get(f"/api/papers/{paper_id}/file", headers=HEADERS)
        self.assertEqual(res.status_code, 200, f"下载应 200，实际 {res.status_code}: {res.text}")
        self.assertIn("wordprocessingml", res.headers["content-type"])
        self.assertGreater(len(res.content), 1000)
        self.assertIn("test_paper.docx", res.headers.get("content-disposition", ""))
        print(f"✅ 下载 DOCX → {len(res.content)} bytes, content-type={res.headers['content-type']}")

    def test_20_download_file_not_found(self):
        """GET /api/papers/{nonexistent}/file → 404"""
        res = self.client.get("/api/papers/p_2099_xxxxxx/file", headers=HEADERS)
        self.assertEqual(res.status_code, 404)
        print("✅ download file (论文不存在) → 404")

    def test_21_upload_pdf_with_toc(self):
        """上传带书签大纲（TOC）的 PDF - P0-1 回归（端到端）

        事故：extract_toc() 曾用 get_toc(simple=False)，条目第 4 元素 dest dict 里的
        fitz.Point 不可 JSON 序列化，落盘 text.json 时 json.dumps 抛 TypeError →
        上传 500 且已保存的 raw 文件被联动删除。此测试走完整上传接口守住该链路。
        """
        res = upload_via_client(self.client, create_sample_pdf_with_toc(), "bookmarked_paper.pdf")
        self.assertEqual(
            res.status_code, 200,
            f"带书签 PDF 上传应 200，实际 {res.status_code}: {res.text}",
        )
        body = res.json()
        self.assertEqual(body["code"], 0)
        data = body["data"]
        paper_id = data["paper_id"]
        self.assertTrue(paper_id.startswith("p_"), f"paper_id 应有效，实际 {paper_id!r}")
        self.assertGreater(data["pages"], 0)

        # 事故现场断言：落盘失败时论文目录会被联动删除，raw 文件不复存在
        paper_dir = PAPERS_DIR / paper_id
        self.assertTrue(paper_dir.exists(), "论文目录应存在（不能因落盘失败被清理）")
        self.assertTrue((paper_dir / "raw.pdf").exists(), "raw PDF 应已保存")

        # 落盘的 text.json 必须能被 json.load 正常读回（事故爆点就是写盘前的 json.dumps）
        with open(paper_dir / "text.json", encoding="utf-8") as f:
            parsed = json.load(f)
        toc = parsed["toc"]
        self.assertIsInstance(toc, list)
        self.assertEqual(len(toc), 3, f"应保留 3 条书签，实际 {toc!r}")
        for entry in toc:
            self.assertIsInstance(entry, list, f"toc 条目应为 list，实际 {entry!r}")
            self.assertEqual(len(entry), 3, f"toc 条目应恰好 [level, title, page] 三元素，实际 {entry!r}")
            level, title, page = entry
            self.assertIsInstance(level, int)
            self.assertIsInstance(title, str)
            self.assertIsInstance(page, int)
        self.assertEqual(toc, [[1, "Introduction", 1], [1, "Methods", 2], [2, "1.1 Detail", 2]])
        print(f"✅ 上传带书签 PDF → paper_id={paper_id[:20]}..., pages={data['pages']}, toc={toc}")
