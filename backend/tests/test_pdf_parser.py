"""
PDF 解析测试

不需要 API Key，pytest 下可独立运行：
    cd backend
    python -m pytest tests/test_pdf_parser.py -v

- 样本用 tmp_path 构造，不写入仓库 data/papers/test_samples/（避免污染真实样本）
- 解析结果有真实断言（结构 / 字段 / 页数），消除零断言的假通过
"""
import sys
from pathlib import Path

import pytest

# 让能找到 app 包
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.pdf_parser import PDFParser, parse_pdf


def _build_bookmarked_pdf(target: Path) -> Path:
    """构造带书签大纲（TOC）的测试 PDF（P0-1 回归样本，写入临时目录）"""
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 100), "1. Introduction", fontsize=14)
    page.insert_text((50, 130), "We study the attention mechanisms.", fontsize=11)
    page2 = doc.new_page(width=595, height=842)
    page2.insert_text((50, 100), "2. Methods", fontsize=14)
    doc.set_toc([[1, "Introduction", 1], [1, "Methods", 2], [2, "1.1 Detail", 2]])

    target.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(target))
    doc.close()
    return target


def _build_sample_pdf(target: Path) -> Path:
    """用 PyMuPDF 直接构造一个多页测试 PDF 并保存到 target（临时目录）"""
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)

    # 模拟论文首页
    text_blocks = [
        ("Attention Is All You Need", 18, 50, 100),
        ("", 12, 50, 140),
        ("Ashish Vaswani, Noam Shazeer, Niki Parmar, Jakob Uszkoreit,", 11, 50, 160),
        ("Llion Jones, Aidan N. Gomez, Lukasz Kaiser, Illia Polosukhin", 11, 50, 175),
        ("", 11, 50, 200),
        ("Abstract", 12, 50, 230),
        ("We propose a new simple network architecture, the Transformer,", 11, 50, 250),
        ("based solely on attention mechanisms, dispensing with recurrence", 11, 50, 265),
        ("and convolutions entirely. Experiments on two machine translation", 11, 50, 280),
        ("tasks show these models to be superior in quality while being more", 11, 50, 295),
        ("parallelizable and requiring significantly less time to train.", 11, 50, 310),
        ("", 11, 50, 340),
        ("Keywords: attention, transformer, neural networks, machine translation", 10, 50, 350),
        ("", 10, 50, 380),
        ("1. Introduction", 14, 50, 400),
        ("Recurrent neural networks, long short-term memory and gated recurrent", 11, 50, 430),
        ("neural networks in particular, have been firmly established as state-of-the-art", 11, 50, 445),
        ("approaches in sequence modeling and transduction problems.", 11, 50, 460),
    ]

    for text, size, x, y in text_blocks:
        page.insert_text((x, y), text, fontsize=size)

    # 第二页
    page2 = doc.new_page(width=595, height=842)
    page2.insert_text((50, 100), "2. Background", fontsize=14)
    page2.insert_text(
        (50, 130),
        "The goal of reducing sequential computation also forms the foundation of the Extended Neural GPU, ByteNet and ConvS2S.",
        fontsize=11
    )

    target.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(target))
    doc.close()
    return target


@pytest.fixture(scope="module")
def sample_pdf(tmp_path_factory) -> Path:
    """模块级构造示例 PDF 到临时目录"""
    return _build_sample_pdf(tmp_path_factory.mktemp("pdf_samples") / "transformer_sample.pdf")


def test_create_sample(sample_pdf: Path):
    """生成测试 PDF（用 PyMuPDF 构造，写入临时目录）+ 真实断言解析结果"""
    print("=" * 60)
    print("🔧 生成测试 PDF（用 PyMuPDF 直接构造）")
    print("=" * 60)
    print(f"✅ 测试 PDF 已生成: {sample_pdf}")

    pdf_path = sample_pdf
    if not pdf_path.exists():
        pytest.fail(f"测试 PDF 未生成: {pdf_path}")

    with PDFParser(pdf_path) as parser:
        assert parser.page_count >= 2, f"应 >=2 页，实际 {parser.page_count}"

        meta = parser.extract_metadata()
        print(f"📌 标题: {meta.title}")
        print(f"👥 作者: {', '.join(meta.authors[:5])}")
        print(f"📅 年份: {meta.year}")
        print(f"🔑 关键词: {', '.join(meta.keywords[:5])}")
        print(f"📝 摘要: {meta.abstract[:200]}...")
        print()

        # 真实断言：结构 / 字段（标题提取启发式对不同版面敏感，只断言非空 + 首屏文本含关键词）
        assert meta.title, "应提取到标题"
        assert isinstance(meta.authors, list) and len(meta.authors) >= 1, "应解析出至少 1 个作者"
        assert meta.abstract, "应提取到摘要"
        assert isinstance(meta.keywords, list) and len(meta.keywords) >= 1, "应提取到至少 1 个关键词"

        # 页数
        print(f"📊 总页数: {parser.page_count}")

        # 前 3 页文本预览 + 断言
        pages = parser.extract_pages()
        assert len(pages) == parser.page_count, "页面列表长度应等于页数"
        for p in pages[:3]:
            print(f"--- 第 {p.page_num} 页（{len(p.text)} 字符，{len(p.blocks)} 个文本块）---")
            preview = p.text[:200].replace("\n", " ")
            print(f"{preview}...")
            print()

        # 内容断言：首页应包含论文标题文本
        first_page_text = pages[0].text if pages else ""
        assert "Attention Is All You Need" in first_page_text, "首页应包含标题文本"

    # 一站式 parse() 接口
    parsed = parse_pdf(str(pdf_path))
    for key in ("meta", "page_count", "full_text", "toc", "pages"):
        assert key in parsed, f"parse() 输出应含 '{key}' 字段"
    assert parsed["page_count"] == parser.page_count
    assert len(parsed["full_text"]) > 0, "full_text 应非空"

    print("✅ 解析完成！\n")


def test_extract_toc_bookmarked_json_serializable(tmp_path: Path):
    """P0-1 回归：带书签 PDF 的 extract_toc() / parse_pdf() 返回值必须 JSON 可序列化

    事故：get_toc(simple=False) 返回条目第 4 元素 dest dict 里的 "to" 字段是
    fitz.Point 对象，随解析结果落盘 text.json 时 json.dumps 抛
    "TypeError: Object of type Point is not JSON serializable"，带书签 PDF 上传必现 500。
    """
    import json

    pdf_path = _build_bookmarked_pdf(tmp_path / "bookmarked.pdf")

    with PDFParser(pdf_path) as parser:
        toc = parser.extract_toc()
        assert toc == [[1, "Introduction", 1], [1, "Methods", 2], [2, "1.1 Detail", 2]]
        for entry in toc:
            assert isinstance(entry, list) and len(entry) == 3, f"应恰好三元素，实际 {entry!r}"
            level, title, page = entry
            assert isinstance(level, int) and isinstance(title, str) and isinstance(page, int)
        # 事故直接爆点：返回值必须能过 json.dumps（simple=False 时这里抛 TypeError）
        json.dumps(toc, ensure_ascii=False)

    # parse() 全量结果（toc 随其余字段一起落盘 text.json）也必须可序列化
    parsed = parse_pdf(str(pdf_path))
    json.dumps(parsed, ensure_ascii=False)
    assert parsed["toc"] == toc
    print(f"✅ 带书签 PDF 解析结果 JSON 可序列化, toc={toc}")


def test_extract_toc_normalization_skips_abnormal_entries(tmp_path: Path):
    """防御性归一化：结构异常的 TOC 条目应被跳过，返回值始终是 [int, str, int] 三元素"""
    import json

    class _FakeDoc:
        """伪造 doc.get_toc 返回脏数据（不走 PyMuPDF，稳定触发归一化分支）"""

        def __init__(self, toc):
            self._toc = toc

        def get_toc(self, simple=True):
            return self._toc

        def close(self):
            pass  # PDFParser.close() 会调用

    pdf_path = _build_bookmarked_pdf(tmp_path / "bookmarked_abnormal.pdf")
    abnormal_toc = [
        [1, "Ok Entry", 1],        # 正常条目 → 保留
        "not-a-list",              # 非列表 → 跳过
        [2, "Too Short"],          # 不足三元素 → 跳过
        [3, None, 2],              # 标题 None → 归一化为 ""
        [1, "Bad Page", "nan"],    # 页码不可转 int → 跳过
        [0, "Bad Level", 3],       # level < 1 → 跳过
        [2, "Negative Page", -1],  # page < 1（无有效指向）→ 跳过
        [3, 12345, 2],             # 标题非 str → str() 归一化
    ]

    with PDFParser(pdf_path) as parser:
        # PDFParser 是普通 Python 类，直接替换 self.doc 即可注入脏数据
        parser.doc = _FakeDoc(abnormal_toc)
        toc = parser.extract_toc()

    assert toc == [[1, "Ok Entry", 1], [3, "", 2], [3, "12345", 2]]
    # 归一化结果必须 JSON 可序列化（二次防线的意义所在）
    json.dumps(toc, ensure_ascii=False)
    print(f"✅ 异常 TOC 条目被跳过/归一化, toc={toc}")


def run_file_test(pdf_path: str):
    """解析指定 PDF 的辅助函数（仅脚本模式手动调用，非 pytest 用例）"""
    path = Path(pdf_path)
    if not path.exists():
        print(f"❌ 文件不存在: {path}")
        return

    print(f"\n{'='*60}")
    print(f"📄 测试解析: {path.name}")
    print(f"{'='*60}\n")

    with PDFParser(path) as parser:
        # 1. 元数据
        meta = parser.extract_metadata()
        print(f"📌 标题: {meta.title}")
        print(f"👥 作者: {', '.join(meta.authors[:5])}")
        print(f"📅 年份: {meta.year}")
        print(f"🔑 关键词: {', '.join(meta.keywords[:5])}")
        print(f"📝 摘要: {meta.abstract[:200]}...")
        print()

        # 2. 页数
        print(f"📊 总页数: {parser.page_count}")
        print()

        # 3. 前 3 页文本预览
        pages = parser.extract_pages()
        for p in pages[:3]:
            print(f"--- 第 {p.page_num} 页（{len(p.text)} 字符，{len(p.blocks)} 个文本块）---")
            preview = p.text[:200].replace("\n", " ")
            print(f"{preview}...")
            print()

    print("✅ 解析完成！\n")


def main():
    """主入口（脚本模式）：python -m tests.test_pdf_parser [<pdf_path>]"""
    if len(sys.argv) > 1:
        run_file_test(sys.argv[1])
    else:
        print("🚀 PaperPilot PDF 解析测试")
        print()
        print("用法:")
        print("  python -m pytest tests/test_pdf_parser.py    # pytest 跑完整用例")
        print("  python -m tests.test_pdf_parser <file.pdf>   # 脚本模式解析指定 PDF")
        print()
        import pytest as _pytest
        sys.exit(_pytest.main([str(Path(__file__).resolve())]))


if __name__ == "__main__":
    main()
