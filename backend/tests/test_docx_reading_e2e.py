"""
DOCX 文件读取端到端测试（P1 修复后验收）

测试流程：
1. DOCX Magic Number 校验（PK\x03\x04）
2. validators 模块对 DOCX 相关路径 / 文件名校验
3. 创建并解析 DOCX 样本（用 python-docx 构造，写入 tmp_path，不污染仓库样本）
4. DOCXParser 提取 metadata / pages / full_text / toc
5. 与 PDFParser 输出格式一致（接口兼容性）
6. 真实上传的 DOCX 文件解析（有则测，无则 skip）

用法：
    cd backend
    python -m pytest tests/test_docx_reading_e2e.py -v
"""
import sys
import os
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 测试环境：禁用鉴权 / 降级日志
os.environ.setdefault("APP_API_KEY", "")
os.environ.setdefault("LOG_LEVEL", "WARNING")

from fastapi import HTTPException
from app.utils.logger import logger
from app.utils.validators import (
    validate_paper_id,
    validate_filename,
    check_file_magic,
    ALLOWED_FILE_EXTENSIONS,
    DOCX_MAGIC,
)
from app.services.docx_parser import DOCXParser, parse_docx

PASS = "✅"
FAIL = "❌"

# 仓库自带的真实样本（只读，测试不应覆盖写它）
REPO_SAMPLE_DOCX = BACKEND_DIR / "data" / "papers" / "test_samples" / "transformer_sample.docx"


def check(name: str, condition: bool, detail: str = ""):
    icon = PASS if condition else FAIL
    suffix = f" — {detail}" if detail else ""
    print(f"  {icon} {name}{suffix}")
    return condition


def _raises_http(fn):
    try:
        fn()
        return False
    except HTTPException:
        return True
    except Exception:
        return False


def create_sample_docx(target: Path) -> Path:
    """构造一个示例 DOCX 到 target（临时目录），不污染仓库 data 目录"""
    from docx import Document

    doc = Document()
    doc.add_heading("Attention Is All You Need", level=1)
    doc.add_paragraph("Ashish Vaswani, Noam Shazeer, Niki Parmar, Jakob Uszkoreit")
    doc.add_paragraph("Abstract")
    doc.add_paragraph(
        "We propose a new simple network architecture, the Transformer, "
        "based solely on attention mechanisms, dispensing with recurrence "
        "and convolutions entirely. Experiments on two machine translation "
        "tasks show these models to be superior in quality while being more "
        "parallelizable and requiring significantly less time to train."
    )
    doc.add_paragraph("Keywords: attention, transformer, neural networks")
    doc.add_heading("1 Introduction", level=1)
    doc.add_paragraph(
        "Recurrent neural networks, long short-term memory and gated recurrent "
        "neural networks have been firmly established as state-of-the-art approaches "
        "in sequence modeling and transduction problems such as language modeling."
    )
    doc.add_paragraph(
        "However, RNNs suffer from sequential computation which prevents parallelization "
        "within training examples."
    )
    doc.add_heading("2 Background", level=1)
    doc.add_paragraph(
        "The goal of reducing sequential computation has been addressed by various models. "
        "Extended Neural GPU and ConvS2S use convolutional neural networks as building blocks."
    )
    doc.add_heading("3 Method", level=1)
    doc.add_heading("3.1 Scaled Dot-Product Attention", level=2)
    doc.add_paragraph(
        "We call our particular attention Scaled Dot-Product Attention. "
        "The input consists of queries and keys of dimension dk."
    )
    # 多塞段落让分页触发
    for i in range(30):
        doc.add_paragraph(f"This is filler paragraph {i+1} to ensure the document spans multiple pages.")
    doc.add_heading("4 Experiments", level=1)
    doc.add_paragraph(
        "We evaluate our model on two machine translation tasks. On WMT 2014 "
        "English-to-German translation task, our model achieves 28.4 BLEU."
    )
    doc.add_heading("5 Conclusion", level=1)
    doc.add_paragraph(
        "In this work, we presented the Transformer, the first sequence transduction "
        "model based entirely on attention."
    )

    target.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(target))
    return target


@pytest.fixture(scope="module")
def sample_docx(tmp_path_factory) -> Path:
    """模块级构造示例 DOCX 到临时目录，各用例独立使用，消除顺序依赖"""
    return create_sample_docx(tmp_path_factory.mktemp("docx_e2e_samples") / "transformer_sample.docx")


def test_docx_magic_number():
    """测试 DOCX Magic Number 校验"""
    print(f"\n{'='*60}\n1️⃣  DOCX Magic Number（P1-2）\n{'='*60}")

    ok = True

    # DOCX Magic 应是 ZIP 的 PK\x03\x04
    ok &= check("DOCX_MAGIC = b'PK\\x03\\x04'", DOCX_MAGIC == b"PK\x03\x04")

    # 真 DOCX（只读仓库样本）
    if REPO_SAMPLE_DOCX.exists():
        content = REPO_SAMPLE_DOCX.read_bytes()
        ok &= check(f"真 DOCX 头匹配 (前 4 字节: {content[:4]!r})",
                    check_file_magic(content, ".docx"))
        ok &= check("DOCX 不被误判为 PDF", not check_file_magic(content, ".pdf"))
    else:
        print("  ⚠️  跳过（样本不存在）")

    # 模拟测试
    fake_docx = b"PK\x03\x04rest of zip content"
    fake_pdf = b"%PDF-1.4 fake pdf"
    fake_html = b"<html>not a real file</html>"
    ok &= check("Magic: 模拟真 DOCX 通过", check_file_magic(fake_docx, ".docx"))
    ok &= check("Magic: 模拟真 PDF 通过", check_file_magic(fake_pdf, ".pdf"))
    ok &= check("Magic: HTML 不能伪装成 DOCX", not check_file_magic(fake_html, ".docx"))
    ok &= check("Magic: HTML 不能伪装成 PDF", not check_file_magic(fake_html, ".pdf"))
    ok &= check("Magic: 空文件拦截", not check_file_magic(b"", ".docx"))
    ok &= check("Magic: 太小（<8 字节）拦截", not check_file_magic(b"PK\x03", ".docx"))

    # 文件后缀白名单
    ok &= check(".docx 在 ALLOWED_FILE_EXTENSIONS", ".docx" in ALLOWED_FILE_EXTENSIONS)
    ok &= check(".pdf 在 ALLOWED_FILE_EXTENSIONS", ".pdf" in ALLOWED_FILE_EXTENSIONS)
    ok &= check(".exe 不在白名单", ".exe" not in ALLOWED_FILE_EXTENSIONS)

    assert ok


def test_docx_metadata(sample_docx: Path):
    """测试 DOCX 元数据提取"""
    print(f"\n{'='*60}\n2️⃣  DOCX 元数据提取\n{'='*60}")

    ok = True
    print(f"  样本: {sample_docx.name}")

    with DOCXParser(sample_docx) as parser:
        meta = parser.extract_metadata()
        print(f"  📌 标题: {meta.title}")
        print(f"  👥 作者: {meta.authors}")
        print(f"  📅 年份: {meta.year}")
        print(f"  🔑 关键词: {meta.keywords}")
        print(f"  📝 摘要: {meta.abstract[:120]}...")

        ok &= check("标题含 'Attention'", "Attention" in meta.title, f"actual: '{meta.title}'")
        ok &= check("作者数 >= 2", len(meta.authors) >= 2, f"actual: {len(meta.authors)}")
        ok &= check("摘要含 'Transformer'", "Transformer" in meta.abstract)
        ok &= check("关键词数 >= 1", len(meta.keywords) >= 1)
        ok &= check("作者列表元素是字符串", all(isinstance(a, str) for a in meta.authors))
        ok &= check("关键词列表元素是字符串", all(isinstance(k, str) for k in meta.keywords))

    assert ok


def test_docx_pages_and_toc(sample_docx: Path):
    """测试 DOCX 分页与 TOC"""
    print(f"\n{'='*60}\n3️⃣  DOCX 分页与 TOC\n{'='*60}")

    ok = True

    with DOCXParser(sample_docx) as parser:
        pages = parser.extract_pages()
        print(f"  📊 伪页数: {len(pages)}（每 25 段一页）")
        for p in pages[:3]:
            preview = p.text[:80].replace("\n", " ")
            print(f"    第 {p.page_num} 页（{len(p.text)} 字符）: {preview}...")

        ok &= check("页数 >= 2", len(pages) >= 2)
        ok &= check("所有页都有 page_num", all(p.page_num >= 1 for p in pages))
        ok &= check("所有页都有 text 字段", all(isinstance(p.text, str) for p in pages))
        ok &= check("页编号连续", [p.page_num for p in pages] == list(range(1, len(pages) + 1)))

        # TOC
        toc = parser.extract_toc()
        print(f"  📑 TOC 条数: {len(toc)}")
        for level, title, page in toc:
            print(f"    [{level}] {title} (P{page})")

        ok &= check("TOC 条数 >= 3", len(toc) >= 3)
        titles = [t[1].lower() for t in toc]
        ok &= check("TOC 含 'Introduction'", any("introduction" in t for t in titles))
        ok &= check("TOC 含 'Method'", any("method" in t for t in titles))
        ok &= check("TOC 含 'Conclusion'", any("conclusion" in t for t in titles))

    assert ok


def test_docx_full_parse(sample_docx: Path):
    """测试 DOCX parse() 一站式接口（与 PDF 接口一致）"""
    print(f"\n{'='*60}\n4️⃣  DOCX parse() 接口一致性\n{'='*60}")

    ok = True

    parsed = parse_docx(sample_docx)

    print(f"  meta.title: {parsed['meta']['title']}")
    print(f"  page_count: {parsed['page_count']}")
    print(f"  toc 条数: {len(parsed['toc'])}")
    print(f"  full_text 长度: {len(parsed['full_text'])} 字符")
    print(f"  pages 数量: {len(parsed['pages'])}")

    # 验证接口与 PDFParser 一致
    ok &= check("含 'meta' 字段", "meta" in parsed)
    ok &= check("含 'page_count' 字段", "page_count" in parsed)
    ok &= check("含 'full_text' 字段", "full_text" in parsed)
    ok &= check("含 'toc' 字段", "toc" in parsed)
    ok &= check("含 'pages' 字段", "pages" in parsed)

    # 验证 meta 子字段
    meta = parsed["meta"]
    required_meta_keys = ["title", "authors", "abstract", "keywords", "year"]
    for key in required_meta_keys:
        ok &= check(f"meta.{key} 存在", key in meta)

    # 验证 page 子字段（与 PDF 一致）
    if parsed["pages"]:
        p = parsed["pages"][0]
        for key in ["page_num", "text", "width", "height", "blocks"]:
            ok &= check(f"page.{key} 存在", key in p)

    # 验证数据类型
    ok &= check("page_count 是 int", isinstance(parsed["page_count"], int))
    ok &= check("full_text 是 str", isinstance(parsed["full_text"], str))
    ok &= check("authors 是 list", isinstance(meta["authors"], list))

    assert ok


def test_docx_real_upload():
    """解析仓库自带的 DOCX 样本（不读真实用户数据，样本缺失则 skip）"""
    print(f"\n{'='*60}\n5️⃣  真实 DOCX 样本解析\n{'='*60}")

    ok = True

    if not REPO_SAMPLE_DOCX.exists():
        print(f"  ⚠️  仓库 DOCX 样本不存在，跳过: {REPO_SAMPLE_DOCX}")
        pytest.skip(f"仓库 DOCX 样本不存在: {REPO_SAMPLE_DOCX}")

    raw_path = REPO_SAMPLE_DOCX
    print(f"  📄 测试样本: {raw_path.name}")
    print(f"     文件大小: {raw_path.stat().st_size} bytes")

    # 1. 文件存在
    ok &= check("raw.docx 存在", raw_path.exists())

    # 2. Magic Number
    content = raw_path.read_bytes()
    ok &= check("Magic: 真 DOCX 识别", check_file_magic(content, ".docx"))

    # 3. 解析
    try:
        with DOCXParser(raw_path) as parser:
            parsed = parser.parse()
            ok &= check("解析无异常", True)
            ok &= check("meta 提取成功", bool(parsed.get("meta", {}).get("title")))
            ok &= check("页数 >= 1", parsed["page_count"] >= 1)
            ok &= check("全文非空", len(parsed["full_text"]) > 100)

            title = parsed["meta"]["title"]
            pages = parsed["page_count"]
            text_len = len(parsed["full_text"])
            print(f"     标题: {title[:60]}")
            print(f"     页数: {pages}, 文本长度: {text_len}")

    except Exception as e:
        ok &= check(f"解析异常: {type(e).__name__}: {e}", False)
        logger.exception("DOCX 解析异常")

    # 4. validate_paper_id 应该接受合法的 paper_id
    sample_paper_id = "p_2026_01_01_sample01"
    try:
        validate_paper_id(sample_paper_id)
        ok &= check(f"validate_paper_id({sample_paper_id}) 接受", True)
    except Exception as e:
        ok &= check(f"validate_paper_id({sample_paper_id}) 失败: {e}", False)

    assert ok


def test_docx_upload_validation():
    """测试上传 endpoint 的 DOCX 校验链（P1-1/2）"""
    print(f"\n{'='*60}\n6️⃣  DOCX 上传校验链\n{'='*60}")

    ok = True

    # 后缀校验（与后端 ALLOWED_EXTENSIONS 一致）
    from app.utils.validators import ALLOWED_FILE_EXTENSIONS as ALLOWED

    ok &= check(
        ".docx 在 validators.ALLOWED_FILE_EXTENSIONS",
        ".docx" in ALLOWED,
    )
    ok &= check(
        ".pdf 在 validators.ALLOWED_FILE_EXTENSIONS",
        ".pdf" in ALLOWED,
    )

    # 模拟：客户端上传 PDF 但声称 .docx
    fake_pdf_renamed = b"%PDF-1.4\nfake pdf content with docx extension"
    ok &= check(
        "Magic: PDF 内容 + .docx 后缀应被拒",
        not check_file_magic(fake_pdf_renamed, ".docx"),
    )

    # 模拟：客户端上传 EXE
    fake_exe = b"MZ\x90\x00fake exe"
    ok &= check("Magic: EXE 不能伪装成 DOCX", not check_file_magic(fake_exe, ".docx"))
    ok &= check("Magic: EXE 不能伪装成 PDF", not check_file_magic(fake_exe, ".pdf"))

    # 真实 DOCX 通过（只读仓库样本）
    if REPO_SAMPLE_DOCX.exists():
        content = REPO_SAMPLE_DOCX.read_bytes()
        ok &= check("真实 DOCX 通过 Magic 校验", check_file_magic(content, ".docx"))

    assert ok


def test_docx_filename_safety():
    """测试 DOCX 文件名安全校验"""
    print(f"\n{'='*60}\n7️⃣  DOCX 文件名安全（P1-4）\n{'='*60}")

    ok = True

    safe_names = [
        "paper_abc12345.docx",
        "report_2026-07-29.docx",
        "abc_DEF-123.docx",
    ]
    for name in safe_names:
        try:
            validate_filename(name)
            ok &= check(f"合法文件名通过: {name}", True)
        except Exception as e:
            ok &= check(f"合法文件名通过: {name}", False, str(e))

    bad_names = [
        "../etc/passwd",
        "a/b.docx",
        "a\\b.docx",
        ".hidden.docx",
        "",  # 空
    ]
    for name in bad_names:
        ok &= check(
            f"非法文件名拦截: {name[:30]!r}",
            _raises_http(lambda n=name: validate_filename(n)),
        )

    assert ok


def main():
    """手动运行入口：直接以 pytest 运行本文件（保证与 CI 行为一致）"""
    import pytest as _pytest
    sys.exit(_pytest.main([str(Path(__file__).resolve())]))


if __name__ == "__main__":
    main()
