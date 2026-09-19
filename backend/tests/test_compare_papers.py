"""
多篇对比 paper_id 回填逻辑测试（compare_papers._backfill_related_paper_ids）
LLM 输出顺序可能变化/少输出，纯位置回填会错位；验证标题匹配优先 + 位置兜底。
"""
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.compare_papers import _backfill_related_paper_ids


def _sources():
    return [
        {"paper_id": "p_a", "title": "Attention Is All You Need", "authors": ["Vaswani"]},
        {"paper_id": "p_b", "title": "BERT: Pre-training", "authors": ["Devlin"]},
        {"paper_id": "p_c", "title": "GPT-3", "authors": ["Brown"]},
    ]


def test_title_match_reordered():
    """LLM 重排输出顺序：按标题匹配回填（而非位置）"""
    related_papers = [
        {"title": "GPT-3", "url": ""},
        {"title": "Attention Is All You Need", "url": ""},
        {"title": "BERT: Pre-training", "url": ""},
    ]
    _backfill_related_paper_ids(related_papers, _sources())
    assert [p["paper_id"] for p in related_papers] == ["p_c", "p_a", "p_b"]


def test_title_match_case_and_space():
    """标题大小写/首尾空白差异不影响匹配"""
    related_papers = [
        {"title": "  attention is all you need ", "url": ""},
        {"title": "BERT: Pre-training", "url": ""},
        {"title": "GPT-3", "url": ""},
    ]
    _backfill_related_paper_ids(related_papers, _sources())
    assert [p["paper_id"] for p in related_papers] == ["p_a", "p_b", "p_c"]


def test_missing_entry_position_fallback():
    """LLM 少输出一条：先按标题匹配，剩余位置兜底（不越界、不重复）"""
    related_papers = [
        {"title": "BERT: Pre-training", "url": ""},
        {"title": "GPT-3", "url": ""},
    ]
    _backfill_related_paper_ids(related_papers, _sources())
    ids = [p["paper_id"] for p in related_papers]
    assert ids[0] == "p_b"
    assert ids[1] == "p_c"
    assert len(set(ids)) == len(ids), "paper_id 不应重复"


def test_invented_title_position_fallback():
    """LLM 编造了输入之外的标题：匹配不到则按位置兜底"""
    related_papers = [
        {"title": "Some Made Up Paper", "url": ""},
        {"title": "Attention Is All You Need", "url": ""},
    ]
    _backfill_related_paper_ids(related_papers, _sources())
    ids = [p["paper_id"] for p in related_papers]
    assert ids[1] == "p_a"          # 标题匹配成功
    assert ids[0] in ("p_b", "p_c")  # 编造标题位置兜底（未匹配的源按顺序）
    assert len(set(ids)) == 2


def test_already_filled_not_overwritten():
    """已有 paper_id 的条目不覆盖"""
    related_papers = [
        {"title": "Attention Is All You Need", "url": "", "paper_id": "p_keep"},
    ]
    _backfill_related_paper_ids(related_papers, _sources())
    assert related_papers[0]["paper_id"] == "p_keep"


def test_empty_inputs():
    """空输入不崩溃"""
    _backfill_related_paper_ids([], [])
    rp = [{"title": "x"}]
    _backfill_related_paper_ids(rp, [])
    assert rp[0].get("paper_id") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
