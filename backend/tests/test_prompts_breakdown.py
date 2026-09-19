"""
提示词构造测试（不需要 LLM API Key）
验证页码协议：Reduce 输入必须透传 Map 输出的 page_ref
"""
import json
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agent.prompts.breakdown import (
    build_chapter_map_messages,
    build_reduce_messages,
    REDUCE_CHAPTERS_JSON_MAX_CHARS,
    REDUCE_OMIT_MARK,
    REDUCE_RETRY_BUDGET_CHARS,
    REDUCE_SUMMARY_MAX_CHARS,
    INNOVATION_SYSTEM_PROMPT,
    FLAWS_SYSTEM_PROMPT,
)


def _make_oversize_chapter_maps(n: int = 20) -> list:
    """构造超长 summary / key_points / key_quote 的章节 Map 结果（每项远超单章上限）"""
    return [
        {
            "chapter_name": f"Chapter {i}",
            "summary": "很长的摘要内容" * 1000,       # 7000 字符 > 单章上限
            "key_points": [f"第 {j} 个要点" * 200 for j in range(1, 4)],
            "key_quote": "一段很长的原文引用" * 400,
            "page_ref": i,
            "section_type": "other",
        }
        for i in range(1, n + 1)
    ]


def _extract_chapters_json(user_content: str) -> list:
    """从 Reduce user prompt 中解析出 chapters_json（与现有测试相同的定位方式）"""
    start = user_content.index("[")
    end = user_content.rindex("]") + 1
    return json.loads(user_content[start:end])


def test_reduce_messages_preserve_page_ref():
    """Reduce 输入必须携带每章的 page_ref（联动高亮页码链路的关键）"""
    chapter_maps = [
        {
            "chapter_name": "Abstract",
            "summary": "提出新架构",
            "key_points": ["注意力机制"],
            "key_quote": "Attention is all you need.",
            "page_ref": 1,
            "section_type": "abstract",
        },
        {
            "chapter_name": "Method",
            "summary": "多头注意力",
            "key_points": ["多头"],
            "key_quote": "We call it multi-head.",
            "page_ref": 4,
            "section_type": "method",
        },
    ]

    messages = build_reduce_messages(chapter_maps, {"title": "Test"})
    user_content = messages[-1]["content"]

    # user prompt 里包含各章节 JSON，必须能看到 page_ref 字段
    assert '"page_ref": 1' in user_content
    assert '"page_ref": 4' in user_content

    # 解析出章节数组，逐个校验字段
    # 找到 [ 开始到 ] 结束的章节数组（user prompt 中 `各章节分析结果（共 2 章）` 后）
    start = user_content.index("[")
    end = user_content.rindex("]") + 1
    parsed = json.loads(user_content[start:end])
    assert len(parsed) == 2
    assert parsed[0]["page_ref"] == 1
    assert parsed[1]["page_ref"] == 4


def test_reduce_summary_single_chapter_clamped():
    """P1-2: 单章 summary 超上限时截断并加省略标记，page_ref / section_type 保留"""
    maps = [{
        "chapter_name": "Abstract",
        "summary": "x" * 5000,
        "key_points": [],
        "key_quote": "",
        "page_ref": 2,
        "section_type": "abstract",
    }]
    messages = build_reduce_messages(maps, {"title": "T"})
    parsed = _extract_chapters_json(messages[-1]["content"])
    assert len(parsed) == 1
    assert parsed[0]["summary"].endswith(REDUCE_OMIT_MARK), "截断应带省略标记"
    assert len(parsed[0]["summary"]) == REDUCE_SUMMARY_MAX_CHARS
    assert parsed[0]["page_ref"] == 2
    assert parsed[0]["section_type"] == "abstract"


def test_reduce_messages_bounded_under_oversize_input():
    """P1-2: 20 章超长 summary 下 Reduce prompt 长度有界，chapters_json 仍可 json.loads"""
    maps = _make_oversize_chapter_maps(20)
    messages = build_reduce_messages(maps, {"title": "Test"})
    user_content = messages[-1]["content"]

    # 截断标记出现（说明确实发生了截断）
    assert REDUCE_OMIT_MARK in user_content
    # prompt 长度有界：默认总预算 60000 + 脚手架余量（防 Reduce 超上下文）
    assert len(user_content) < REDUCE_CHAPTERS_JSON_MAX_CHARS + 2000, (
        f"Reduce prompt 应有界，实际 {len(user_content)} 字符"
    )
    # 产物仍为合法 JSON，章节数不丢、字段不缺
    parsed = _extract_chapters_json(user_content)
    assert len(parsed) == 20
    assert all(e["page_ref"] == i + 1 for i, e in enumerate(parsed))
    assert all(len(e["summary"]) <= REDUCE_SUMMARY_MAX_CHARS for e in parsed)


def test_reduce_messages_aggressive_retry_budget():
    """P1-2c: 传入激进总预算（上下文超限重试场景）后 prompt 显著收紧且有界"""
    maps = _make_oversize_chapter_maps(20)
    messages = build_reduce_messages(
        maps, {"title": "Test"}, total_budget_chars=REDUCE_RETRY_BUDGET_CHARS
    )
    user_content = messages[-1]["content"]

    assert len(user_content) < REDUCE_RETRY_BUDGET_CHARS + 2000, (
        f"激进预算下 prompt 应 < {REDUCE_RETRY_BUDGET_CHARS}+脚手架，实际 {len(user_content)}"
    )
    # 仍然合法可解析、章节一个不少
    parsed = _extract_chapters_json(user_content)
    assert len(parsed) == 20
    # 激进预算下单章文本应比默认预算下更短
    default_messages = build_reduce_messages(maps, {"title": "Test"})
    assert len(user_content) < len(default_messages[-1]["content"])


def test_map_messages_mention_page_marker():
    """Map user prompt 应告知 LLM 正文含 === Page N === 标记（含页码定位说明）"""
    from app.agent.chapter_splitter import Chapter

    ch = Chapter(name="Method", text="\n\n=== Page 4 ===\n\n方法内容", page_start=4, page_end=5)
    messages = build_chapter_map_messages(ch, {"title": "Test"})

    # 正文透传（含页标记）
    assert "=== Page 4 ===" in messages[-1]["content"]
    # system prompt 告知页码取自标记
    assert "page_ref" in messages[0]["content"]
    assert "=== Page N ===" in messages[0]["content"]


def test_innovation_prompt_verbatim_quote_and_page_protocol():
    """创新 prompt：evidence 必须逐字引用（禁翻译/禁页码标注），页码取自 === Page N === 标记"""
    prompt = INNOVATION_SYSTEM_PROMPT

    # 逐字引用要求（联动高亮依赖，防止 LLM 改写/翻译导致匹配失败）
    assert "逐字引用" in prompt, "evidence 应要求逐字引用原文"
    assert "禁止翻译" in prompt and "禁止改写" in prompt, "应禁止翻译/改写"
    # 页码标注禁止写进 evidence 文本（此前要求"方括号标注页码"导致匹配必然失败）
    assert "方括号标注页码" not in prompt, "不应再要求文本内页码标注"
    assert "禁止写进 evidence" in prompt or "页码只填" in prompt
    # 页标记协议（page_ref 不能靠猜）
    assert "=== Page N ===" in prompt
    assert "禁止凭空猜测" in prompt


def test_flaws_prompt_verbatim_quote_and_page_protocol():
    """漏洞 prompt：evidence 逐字引用 + 页码取自标记（与创新一致）"""
    prompt = FLAWS_SYSTEM_PROMPT

    assert "逐字引用" in prompt
    assert "禁止翻译" in prompt and "禁止改写" in prompt
    assert "=== Page N ===" in prompt
    assert "禁止凭空猜测" in prompt


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
