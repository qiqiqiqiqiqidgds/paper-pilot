"""
validators 单元测试（P2-4 回归：400 detail / SSE error 事件回显前必须清洗原始输入）

背景：validate_paper_id / validate_analysis_type 校验失败时，detail 里曾原样
回显任意输入（paper_id[:32]）。该 detail 会进入两条通道：
  1. HTTP 400 响应体（FastAPI HTTPException detail）；
  2. SSE error 事件（analyze.py::_event_stream 把 he.detail 放进事件 payload）。
恶意输入（HTML / 控制字符 / 日志注入换行 / 超长）不得原样出现在其中。

修复方案取舍：选择"清洗后回显"而非"不回显"——保留安全字符片段更利于调用方
调试定位；非白名单字符一律替换为 "?"，长度截断与旧实现一致（32 字符）。
"""
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.utils.validators import validate_analysis_type, validate_paper_id


def _detail_of(fn, value: str) -> str:
    """调用校验函数并返回 HTTPException 的 detail 文本"""
    with pytest.raises(HTTPException) as ei:
        fn(value)
    return ei.value.detail


# ===== 合法输入不受影响 =====

def test_valid_paper_id_passthrough():
    assert validate_paper_id("p_2026_07_19_abc12345") == "p_2026_07_19_abc12345"
    assert validate_paper_id("abc-def-123") == "abc-def-123"


def test_valid_analysis_type_passthrough():
    assert validate_analysis_type("breakdown") == "breakdown"


# ===== P2-4：恶意输入回显前清洗 =====

def test_paper_id_echo_strips_html():
    """HTML 注入载体（尖括号/引号/括号）不得原样出现在 400 detail 中"""
    evil = '<script>alert("xss")</script>'
    detail = _detail_of(validate_paper_id, evil)
    assert "<" not in detail and ">" not in detail, f"detail 不得包含尖括号: {detail!r}"
    assert '<script>' not in detail
    assert "(" not in detail and '"' not in detail, f"detail 不得包含引号/括号: {detail!r}"


def test_paper_id_echo_strips_control_chars_and_newlines():
    """控制字符 / 换行（日志与 SSE 注入向量）不得进入 detail"""
    evil = "p_1\nINFO fake log line\r\n\x00\x07"
    detail = _detail_of(validate_paper_id, evil)
    for ch in ("\n", "\r", "\x00", "\x07"):
        assert ch not in detail, f"detail 不得包含控制字符 {ch!r}: {detail!r}"


def test_paper_id_echo_truncates_overlong_input():
    """超长输入（500 字符）回显长度有界（清洗后截断 32 字符）"""
    evil = "a" * 500
    detail = _detail_of(validate_paper_id, evil)
    assert len(detail) < 120, f"detail 应有界，实际长度 {len(detail)}"
    assert "a" * 33 not in detail


def test_paper_id_echo_keeps_safe_fragment_for_debugging():
    """调试友好：白名单安全字符片段保留，仅非法部分被替换为 ?"""
    evil = "p_2026_01_01_abc<script>"
    detail = _detail_of(validate_paper_id, evil)
    assert "p_2026_01_01_abc" in detail, f"安全片段应保留便于调试: {detail!r}"
    assert "<script>" not in detail


def test_analysis_type_echo_sanitized():
    """analysis_type 的回显同样清洗（路径注入 + SSE 注入载体）"""
    evil = "../breakdown\nINJECTED"
    detail = _detail_of(validate_analysis_type, evil)
    assert ".." not in detail and "/" not in detail, f"detail 不得包含路径穿越片段: {detail!r}"
    assert "\n" not in detail, f"detail 不得包含换行: {detail!r}"
    assert "INJECT\n" not in detail


def test_error_detail_safe_for_sse_payload():
    """端到端语义：清洗后的 detail 可安全经 json.dumps 进入 SSE error 事件"""
    import json

    from app.api.analyze import _sse_bytes

    evil = 'x"\n</script>\x00'
    detail = _detail_of(validate_paper_id, evil)
    payload = _sse_bytes("error", {"message": detail, "code": 400})
    decoded = payload.decode("utf-8")
    # SSE 帧不能被注入换行撕裂出伪造事件
    assert decoded.count("event: error") == 1
    # 数据行可被 JSON 解析（无裸控制字符破坏协议）
    data_line = [x for x in decoded.splitlines() if x.startswith("data: ")][0]
    parsed = json.loads(data_line[len("data: "):])
    assert parsed["code"] == 400


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
