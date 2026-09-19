"""
章节识别器测试（不需要 LLM API Key）

用法：
    cd backend
    python -m tests.test_chapter_splitter
"""
import sys
from pathlib import Path

import pytest
import re

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agent.chapter_splitter import ChapterSplitter, MAX_CHAPTERS, split_chapters
from app.utils.logger import logger


def make_pages() -> list:
    """构造模拟的 pages 数据"""
    return [
        {
            "page_num": 1,
            "text": "Attention Is All You Need\n\nAshish Vaswani, Noam Shazeer\nGoogle Brain\n\nAbstract\nWe propose a new simple network architecture, the Transformer...",
            "width": 595, "height": 842, "blocks": []
        },
        {
            "page_num": 2,
            "text": "1 Introduction\n\nRecurrent neural networks have been firmly established as state-of-the-art approaches in sequence modeling. However, RNNs suffer from sequential computation...",
            "width": 595, "height": 842, "blocks": []
        },
        {
            "page_num": 3,
            "text": "2 Background\n\nThe goal of reducing sequential computation has been addressed by various models. Extended Neural GPU, ByteNet and ConvS2S all use convolutional neural networks...",
            "width": 595, "height": 842, "blocks": []
        },
        {
            "page_num": 4,
            "text": "3 Method\n\n3.1 Scaled Dot-Product Attention\nWe call our particular attention Scaled Dot-Product Attention. The input consists of queries and keys...",
            "width": 595, "height": 842, "blocks": []
        },
        {
            "page_num": 5,
            "text": "3.2 Multi-Head Attention\nInstead of performing a single attention function, we found it beneficial to linearly project the queries, keys and values h times...",
            "width": 595, "height": 842, "blocks": []
        },
        {
            "page_num": 6,
            "text": "4 Experiments\n\n4.1 Machine Translation\nWe evaluate our model on two machine translation tasks. On WMT 2014 English-to-German translation task...",
            "width": 595, "height": 842, "blocks": []
        },
        {
            "page_num": 7,
            "text": "5 Conclusion\n\nIn this work, we presented the Transformer, the first sequence transduction model based entirely on attention...",
            "width": 595, "height": 842, "blocks": []
        },
        {
            "page_num": 8,
            "text": "References\n\n[1] Bahdanau et al. Neural Machine Translation by Jointly Learning to Align and Translate. ICLR 2015.",
            "width": 595, "height": 842, "blocks": []
        },
    ]


def make_toc() -> list:
    """构造模拟的 PDF 大纲"""
    return [
        [1, "Abstract", 1],
        [1, "1 Introduction", 2],
        [1, "2 Background", 3],
        [1, "3 Method", 4],
        [1, "3.1 Scaled Dot-Product Attention", 4],
        [1, "3.2 Multi-Head Attention", 5],
        [1, "4 Experiments", 6],
        [1, "4.1 Machine Translation", 6],
        [1, "5 Conclusion", 7],
        [1, "References", 8],
    ]


def test_with_toc():
    """测试 1：用 PDF 大纲识别"""
    print("=" * 60)
    print("🧪 测试 1：基于 PDF 大纲识别章节")
    print("=" * 60)
    pages = make_pages()
    toc = make_toc()

    chapters = split_chapters(pages=pages, toc=toc, full_text="")

    print(f"\n识别到 {len(chapters)} 章：")
    for i, ch in enumerate(chapters, 1):
        print(f"  {i}. [{ch.name}] 第 {ch.page_start}-{ch.page_end} 页 (文本 {len(ch.text)} 字符)")

    # 断言
    assert len(chapters) >= 3, f"应该识别 >=3 章，实际 {len(chapters)}"
    assert chapters[0].page_start == 1, "第一章应该从第 1 页开始"

    # 验证每个章节都拿到了内容
    for ch in chapters:
        assert ch.text.strip(), f"章节 {ch.name} 文本为空"

    print("✅ 通过\n")


def test_with_pattern():
    """测试 2：无大纲，用文本模式识别"""
    print("=" * 60)
    print("🧪 测试 2：基于文本模式识别章节（无大纲）")
    print("=" * 60)
    pages = make_pages()
    # 不传 toc

    chapters = split_chapters(pages=pages, toc=None, full_text="")

    print(f"\n识别到 {len(chapters)} 章：")
    for i, ch in enumerate(chapters, 1):
        print(f"  {i}. [{ch.name}] 第 {ch.page_start}-{ch.page_end} 页 (文本 {len(ch.text)} 字符)")

    assert len(chapters) >= 3, f"应该识别 >=3 章，实际 {len(chapters)}"

    print("✅ 通过\n")


def test_fallback():
    """测试 3：完全识别不到时兜底"""
    print("=" * 60)
    print("🧪 测试 3：章节识别失败时的兜底逻辑")
    print("=" * 60)
    # 没有任何章节标识的 pages
    pages = [
        {"page_num": 1, "text": "随便写点内容\n没有任何章节标识\n就是些普通段落", "width": 595, "height": 842, "blocks": []},
        {"page_num": 2, "text": "继续写\n还是没有章节标识\n只有纯文本", "width": 595, "height": 842, "blocks": []},
    ]

    chapters = split_chapters(pages=pages, toc=None, full_text="")

    print(f"\n兜底结果：{len(chapters)} 章")
    for i, ch in enumerate(chapters, 1):
        print(f"  {i}. [{ch.name}] 第 {ch.page_start}-{ch.page_end} 页")

    assert len(chapters) == 1, f"兜底应该只有 1 章，实际 {len(chapters)}"
    assert chapters[0].name == "全文", f"兜底章节名应为'全文'，实际'{chapters[0].name}'"

    print("✅ 通过\n")


def test_normalize():
    """测试 4：标题归一化"""
    print("=" * 60)
    print("🧪 测试 4：标题归一化")
    print("=" * 60)

    test_cases = [
        ("1 Introduction", "Introduction"),
        ("1. Introduction", "Introduction"),
        ("1 INTRODUCTION", "Introduction"),
        ("3 Method", "Method"),
        ("2.1 Background", "Background"),
        ("Related Work", "Related Work"),
        ("5 Conclusion", "Conclusion"),
    ]

    splitter = ChapterSplitter(pages=[], toc=[], full_text="")
    passed = 0
    for input_title, expected in test_cases:
        result = splitter._normalize_title(input_title)
        status = "✅" if result == expected else "❌"
        if result != expected:
            print(f"  {status} '{input_title}' -> '{result}' (期望 '{expected}')")
        else:
            passed += 1

    assert passed == len(test_cases), f"归一化测试失败：{len(test_cases) - passed} 个"
    print(f"✅ 全部 {passed} 个归一化测试通过\n")


def test_with_real_pdf():
    """测试 5：用仓库自带的真实 PDF（不存在则跳过）"""
    print("=" * 60)
    print("🧪 测试 5：真实 PDF（可选）")
    print("=" * 60)

    # 用仓库内已提交的真实样本定位，不依赖 CWD / sys.argv（pytest 下 argv 不可靠）
    test_sample_pdf = BACKEND_DIR / "data" / "papers" / "test_samples" / "transformer_sample.pdf"
    if not test_sample_pdf.exists():
        print(f"⚠️  样本不存在: {test_sample_pdf}，跳过\n")
        pytest.skip(f"样本不存在: {test_sample_pdf}")

    from app.services.pdf_parser import PDFParser

    pdf_path = test_sample_pdf

    with PDFParser(pdf_path) as parser:
        parsed = parser.parse()

    chapters = split_chapters(
        pages=parsed["pages"],
        toc=parsed.get("toc", []),
        full_text=parsed["full_text"],
    )

    print(f"\n📄 {pdf_path.name} ({parsed['page_count']} 页)")
    print(f"PDF 大纲: {len(parsed.get('toc', []))} 条")
    print(f"识别章节: {len(chapters)} 章\n")
    for i, ch in enumerate(chapters, 1):
        print(f"  {i}. [{ch.name}] 第 {ch.page_start}-{ch.page_end} 页 ({len(ch.text)} 字符)")
        preview = ch.text[:80].replace("\n", " ")
        print(f"     预览: {preview}...")

    # 真实断言：至少能切出 1 章，且每章都拿到内容
    assert len(chapters) >= 1, "真实 PDF 应至少识别出 1 章"
    for ch in chapters:
        assert ch.text.strip(), f"章节 {ch.name} 文本为空"
    print("✅ 完成\n")


def test_page_markers():
    """测试 6：章节文本带页码标记（联动高亮依赖的页码协议）"""
    pages = make_pages()
    chapters = split_chapters(pages=pages, toc=None, full_text="")

    # 章节文本应包含 === Page N === 标记，且标记页码落在章节页范围内
    for ch in chapters:
        markers = re.findall(r"=== Page (\d+) ===", ch.text)
        for m in markers:
            page = int(m)
            assert ch.page_start <= page <= ch.page_end, (
                f"章节 {ch.name} 的页标记 {page} 超出范围 {ch.page_start}-{ch.page_end}"
            )
        assert markers, f"章节 {ch.name} 缺少页码标记"

    # 章节文本应以页标记开头（strip 后）
    first_ch = chapters[0]
    assert first_ch.text.strip().startswith("=== Page"), f"章节 {first_ch.name} 未以页标记开头"

    print(f"✅ 页码标记协议验证通过（{len(chapters)} 章均含页标记）\n")


def test_toc_filters_appendix_and_dedup():
    """测试 7（B9 回归）：目录切分过滤附录类章节 + 归一化去重"""
    pages = make_pages()
    # toc 含：References（附录类）、重复的 Introduction（跨页重复登记）、大小写变体
    toc = [
        [1, "Abstract", 1],
        [1, "1 Introduction", 2],
        [1, "INTRODUCTION", 2],          # 重复 → 去重
        [1, "2 Background", 3],
        [1, "3 Method", 4],
        [1, "5 Conclusion", 7],
        [1, "References", 8],            # 附录类 → 过滤
        [1, "Acknowledgments", 8],       # 附录类 → 过滤
        [1, "Appendix A: Details", 8],   # 附录类 → 过滤
    ]

    chapters = split_chapters(pages=pages, toc=toc, full_text="")
    names = [ch.name for ch in chapters]

    print(f"\n识别到 {len(chapters)} 章：{names}")

    assert len(chapters) >= 3, f"应识别 >=3 章，实际 {len(chapters)}"
    assert names.count("Introduction") == 1, f"Introduction 应去重只保留 1 次，实际 {names}"
    for banned in ("References", "Acknowledgment", "Appendix"):
        assert banned not in names, f"附录类章节 {banned} 不应出现在结果中: {names}"
    print("✅ 附录过滤 + 去重通过\n")


def test_chapter_cap_merges_tail_into_single_chapter():
    """测试 8（P1-2 回归）：章节数超 MAX_CHAPTERS 时尾部合并为单章（确定性策略）

    目录含 20 个 level-1 条目（均非关键词/附录类，每个都算一章），
    超上限后应保头（前 MAX_CHAPTERS-1 章原样）+ 尾部合并为"其余章节"。
    """
    pages = [
        {
            "page_num": i,
            "text": f"第 {i} 页的正文内容，对应 Alpha Topic {i}",
            "width": 595, "height": 842, "blocks": [],
        }
        for i in range(1, 22)
    ]
    toc = [[1, f"{i} Alpha Topic {i}", i] for i in range(1, 21)]

    chapters = split_chapters(pages=pages, toc=toc, full_text="")
    names = [ch.name for ch in chapters]

    print(f"\n识别到 {len(chapters)} 章（上限 {MAX_CHAPTERS}）：{names}")

    # 总数恰为上限
    assert len(chapters) == MAX_CHAPTERS, (
        f"超限后应恰为 {MAX_CHAPTERS} 章，实际 {len(chapters)}"
    )
    # 前 MAX_CHAPTERS-1 章原样保留（确定性：靠前章节优先）
    expected_head = [f"Alpha Topic {i}" for i in range(1, MAX_CHAPTERS)]
    assert names[: MAX_CHAPTERS - 1] == expected_head, f"保头章节不符: {names}"
    # 尾部合并为单章
    merged = chapters[-1]
    assert merged.name == "其余章节"
    assert merged.page_start == MAX_CHAPTERS, f"合并章应从第 {MAX_CHAPTERS} 章起，实际 {merged.page_start}"
    # 末章 page_end 延伸到文档末页（pages 共 21 页）
    assert merged.page_end == 21, f"合并章应到第 21 页止，实际 {merged.page_end}"
    # 合并章保留尾部内容与页码标记（页码定位协议不受合并影响）
    assert "=== Page 20 ===" in merged.text
    assert "Alpha Topic 20" in merged.text
    # 头部章节页范围不受影响
    assert chapters[0].page_start == 1 and chapters[0].page_end == 1
    print("✅ 章节数上限合并策略通过\n")


def test_same_page_multiple_level1_headings():
    """测试 9（P2-1 回归）：同一页出现两个 level-1 标题时两章都要被切出

    旧实现 found_in_page 命中即 break 两层，"5 Results" 与 "6 Conclusion"
    同页时 Conclusion 必丢（内容被并入 Results，边界错切）。
    """
    pages = [
        {
            "page_num": 1,
            "text": "1 Introduction\n\nRecurrent neural networks have been firmly established...",
            "width": 595, "height": 842, "blocks": [],
        },
        {
            "page_num": 2,
            "text": "2 Method\n\nWe propose the Transformer architecture...",
            "width": 595, "height": 842, "blocks": [],
        },
        {
            "page_num": 3,
            "text": (
                "5 Results\n\nOn WMT 2014 English-to-German translation task, "
                "our model achieves 28.4 BLEU...\n\n"
                "6 Conclusion\n\nIn this work, we presented the Transformer, "
                "the first sequence transduction model based entirely on attention..."
            ),
            "width": 595, "height": 842, "blocks": [],
        },
    ]

    chapters = split_chapters(pages=pages, toc=None, full_text="")
    names = [ch.name for ch in chapters]

    print(f"\n识别到 {len(chapters)} 章：{names}")

    # 同页双标题都要被切出（旧实现只切出 Results，Conclusion 丢失）
    assert "Results" in names, f"同页双标题时 Results 应被切出，实际 {names}"
    assert "Conclusion" in names, f"同页双标题时 Conclusion 不应丢失，实际 {names}"
    assert len(chapters) == 4, f"应有 4 章（Introduction/Method/Results/Conclusion），实际 {names}"
    # 位置序正确：Results 在 Conclusion 之前（同页按 offset 排序）
    assert names.index("Results") < names.index("Conclusion"), f"章节顺序应为 Results → Conclusion，实际 {names}"
    # 两章都落在第 3 页（页粒度边界：后章 start 前章 end 同页）
    results_ch = chapters[names.index("Results")]
    conclusion_ch = chapters[names.index("Conclusion")]
    assert results_ch.page_start == 3 and results_ch.page_end == 3
    assert conclusion_ch.page_start == 3 and conclusion_ch.page_end == 3
    for ch in chapters:
        assert ch.text.strip(), f"章节 {ch.name} 文本为空"
    print("✅ 同页双标题切分通过\n")


def main():
    print("\n" + "=" * 60)
    print("🚀 PaperPilot 章节识别器测试")
    print("=" * 60 + "\n")

    try:
        test_with_toc()
        test_with_pattern()
        test_fallback()
        test_normalize()
        test_toc_filters_appendix_and_dedup()
        test_page_markers()
        test_chapter_cap_merges_tail_into_single_chapter()
        test_with_real_pdf()
        print("=" * 60)
        print("🎉 所有测试通过！")
        print("=" * 60)
    except AssertionError as e:
        print(f"\n❌ 测试失败: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"测试异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
