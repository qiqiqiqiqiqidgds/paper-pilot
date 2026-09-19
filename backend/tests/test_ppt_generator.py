"""
PPT 生成器单元测试（不需要 LLM API Key）
验证 README 宣称的 8-15 页下限：内容不足时用已有分析结果补页
"""
import io
import sys
import warnings
import zipfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.ppt_generator import PPTGenerator, MAX_SLIDES


def _count_pages(data: dict) -> int:
    """生成 PPT 并统计页数"""
    gen = PPTGenerator()
    gen.generate_from_analysis(**data)
    return len(gen.prs.slides)


def test_min_8_pages_innovation_only():
    """只跑创新点（5 条）时应补到 >=8 页（原先仅 7 页）"""
    paper_meta = {"title": "Test Paper", "authors": ["A"], "year": 2024}
    innovation = {
        "core_innovations": [
            {"title": f"创新点 {i}", "description": f"这是第 {i} 个创新点的描述"}
            for i in range(1, 6)
        ],
        "innovation_level": "significant",
        "level_reasoning": "性能提升明显",
        "applicable_scenarios": ["场景 A", "场景 B"],
    }
    pages = _count_pages({
        "paper_meta": paper_meta,
        "innovation": innovation,
        "include_flaws": False,
        "include_compare": False,
    })
    assert pages >= 8, f"只跑创新点也应 >=8 页，实际 {pages}"


def test_min_8_pages_minimal_breakdown():
    """只跑拆解且内容很少（2 段）时应补到 >=8 页"""
    paper_meta = {"title": "Minimal", "authors": [], "year": None, "abstract": "简短摘要" * 10}
    breakdown = {
        "summary": "概述",
        "conclusion": "结论",
        "key_points": ["要点1", "要点2", "要点3"],
        "quotes": [
            {"section": "Abstract", "text": "原文引用一句", "page": 1},
            {"section": "Method", "text": "方法原文引用", "page": 3},
        ],
    }
    pages = _count_pages({
        "paper_meta": paper_meta,
        "breakdown": breakdown,
        "include_flaws": False,
        "include_compare": False,
    })
    assert pages >= 8, f"内容很少的拆解也应 >=8 页，实际 {pages}"


def test_full_data_stays_reasonable():
    """全量数据时页数不受影响（8-15 区间）"""
    paper_meta = {"title": "Full", "authors": ["A", "B"], "year": 2025}
    breakdown = {
        "summary": "s", "background": "b", "goal": "g",
        "method": "m", "experiment": "e", "conclusion": "c",
    }
    innovation = {
        "core_innovations": [
            {"title": f"创新点 {i}", "description": "描述" * 5}
            for i in range(1, 4)
        ],
    }
    pages = _count_pages({
        "paper_meta": paper_meta,
        "breakdown": breakdown,
        "innovation": innovation,
    })
    assert 8 <= pages <= 15, f"全量数据应在 8-15 页，实际 {pages}"


def test_full_data_max_cap():
    """极端全量（6 拆解 + 5 创新 + 对比 + 漏洞）也应 <=15 页（README 8-15）"""
    paper_meta = {"title": "Max", "authors": ["A", "B"], "year": 2025}
    breakdown = {
        "summary": "s", "background": "b", "goal": "g",
        "method": "m", "experiment": "e", "conclusion": "c",
    }
    innovation = {
        "core_innovations": [
            {"title": f"创新点 {i}", "description": "描述" * 5}
            for i in range(1, 6)
        ],
        "innovation_level": "significant",
        "level_reasoning": "理由",
        "applicable_scenarios": ["场景 1", "场景 2"],
    }
    flaws = {
        "overall_assessment": "总体评价",
        "method_level": [{"description": "局限 1"}],
        "experiment_level": [{"description": "局限 2"}],
        "writing_level": [{"description": "局限 3"}],
    }
    compare = {
        "related_papers": [
            {"title": f"相关工作 {i}", "year": 2020} for i in range(1, 6)
        ],
        "summary": "对比总结",
        "main_advantages": ["优势"],
        "main_disadvantages": ["劣势"],
    }
    pages = _count_pages({
        "paper_meta": paper_meta,
        "breakdown": breakdown,
        "innovation": innovation,
        "flaws": flaws,
        "compare": compare,
        "include_flaws": True,
        "include_compare": True,
    })
    assert pages <= 15, f"极端全量应 <=15 页，实际 {pages}"
    assert pages >= 8, f"极端全量应 >=8 页，实际 {pages}"


def _max_content_kwargs() -> dict:
    """构造超页场景：6 拆解 + 5 创新 + 对比 2 页 + 漏洞 1 页 = 14 内容页（> 预算 13）"""
    paper_meta = {"title": "Max", "authors": ["A", "B"], "year": 2025}
    breakdown = {
        "summary": "s", "background": "b", "goal": "g",
        "method": "m", "experiment": "e", "conclusion": "c",
    }
    innovation = {
        "core_innovations": [
            {"title": f"创新点 {i}", "description": "描述" * 5}
            for i in range(1, 6)
        ],
        "innovation_level": "significant",
        "level_reasoning": "理由",
        "applicable_scenarios": ["场景 1", "场景 2"],
    }
    flaws = {
        "overall_assessment": "总体评价",
        "method_level": [{"description": "局限 1"}],
        "experiment_level": [{"description": "局限 2"}],
        "writing_level": [{"description": "局限 3"}],
    }
    compare = {
        "related_papers": [
            {"title": f"相关工作 {i}", "year": 2020} for i in range(1, 6)
        ],
        "summary": "对比总结",
        "main_advantages": ["优势"],
        "main_disadvantages": ["劣势"],
    }
    return {
        "paper_meta": paper_meta,
        "breakdown": breakdown,
        "innovation": innovation,
        "flaws": flaws,
        "compare": compare,
        "include_flaws": True,
        "include_compare": True,
    }


def _assert_no_duplicate_zip_entries(data: bytes) -> None:
    """P1-1: 断言 pptx（zip）条目唯一（孤儿 slide part 会造成同名条目）"""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
    duplicates = sorted({n for n in names if names.count(n) > 1})
    assert not duplicates, f"zip 存在重复条目: {duplicates}"


def test_over_page_budget_no_duplicate_zip_entries():
    """P1-1a: 超页场景（14 内容页 > 预算 13）在组装阶段截断，
    生成的 pptx 无重复 zip 条目、无 Duplicate name 警告"""
    gen = PPTGenerator()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        data = gen.generate_from_analysis(**_max_content_kwargs())
    dup_warnings = [str(w.message) for w in caught if "Duplicate name" in str(w.message)]
    assert not dup_warnings, f"不应出现 Duplicate name 警告: {dup_warnings}"
    _assert_no_duplicate_zip_entries(data)
    assert len(gen.prs.slides) <= MAX_SLIDES, (
        f"预算控制后页数应 <= {MAX_SLIDES}，实际 {len(gen.prs.slides)}"
    )


def test_trim_fallback_drops_orphan_part(monkeypatch):
    """P1-1b: 运行时裁剪兜底路径正确 drop_rel（把预算上限调大强制触发裁剪），
    不留孤儿 slide part、无 Duplicate name 警告"""
    from app.services import ppt_generator as pg_mod

    # 绕过组装期预算控制：14 内容页全部生成 → 总页数 15 触发 _trim_over_max_slides
    monkeypatch.setattr(pg_mod, "MAX_CONTENT_SLIDES", 999)
    gen = PPTGenerator()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        data = gen.generate_from_analysis(**_max_content_kwargs())
    dup_warnings = [str(w.message) for w in caught if "Duplicate name" in str(w.message)]
    assert not dup_warnings, f"裁剪兜底不应产生 Duplicate name 警告: {dup_warnings}"
    _assert_no_duplicate_zip_entries(data)
    assert len(gen.prs.slides) <= MAX_SLIDES, (
        f"裁剪兜底后页数应 <= {MAX_SLIDES}，实际 {len(gen.prs.slides)}"
    )


def test_output_is_valid_pptx():
    """生成结果可被 python-pptx 重新打开

    B13 修复后静态补页不再重复添加相同页：极端退化输入（无摘要/作者年份数据
    齐全度极低的 "T" 样例）用尽全部唯一补页内容后为 7 页（不再靠重复页凑到 8），
    唯一性优先于凑数 —— 故断言 >= 7 且页标题不重复。
    """
    from pptx import Presentation
    gen = PPTGenerator()
    data = gen.generate_from_analysis(
        paper_meta={"title": "T", "authors": ["A"]},
        breakdown={"summary": "s"},
    )
    assert len(data) > 1000
    prs = Presentation(io.BytesIO(data))
    assert len(prs.slides) >= 7, f"退化输入也应有 >=7 页，实际 {len(prs.slides)}"
    # 页标题不应重复（B13：同一静态页不添加两次）
    titles = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame and shape.text_frame.text.strip():
                titles.append(shape.text_frame.text.strip())
                break
    assert len(titles) == len(set(titles)), f"页标题不应重复: {titles}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
