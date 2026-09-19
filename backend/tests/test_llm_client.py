"""
llm_client 单元测试：结构化校验 / 重试 / JSON 容错 / 日志清洗

这些逻辑（P1-P0 新增）此前完全未被测试覆盖，且是 LLM 链路上最脆弱的一环。
全部 mock OpenAI SDK，不依赖真实网络。
"""
import json
from typing import Optional
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APIConnectionError, BadRequestError, RateLimitError
from pydantic import BaseModel, Field

from app.config import settings
from app.models.schemas import BreakdownResult, InnovationResult
from app.services import llm_client as lc
from app.services.llm_client import LLMClient


def _make_status_error(status_code: int):
    """构造 openai APIStatusError 子类（429 / 400 / 500）"""
    request = httpx.Request("POST", "http://test")
    response = httpx.Response(status_code, request=request)
    if status_code == 429:
        return RateLimitError("rate limited", response=response, body=None)
    if status_code >= 500:
        from openai import InternalServerError
        return InternalServerError("server error", response=response, body=None)
    return BadRequestError("bad request", response=response, body=None)


class FakeModel(BaseModel):
    """测试用最小模型"""
    name: str = ""
    count: int = 0
    tags: list = Field(default_factory=list)


# ===== _sanitize_for_log =====

def test_sanitize_strips_control_chars_and_truncates():
    text = "abc\x00\x1fdef" + "x" * 200
    out = lc._sanitize_for_log(text)
    assert "\x00" not in out and "\x1f" not in out
    assert len(out) == 120
    assert lc._sanitize_for_log("") == ""
    assert lc._sanitize_for_log(None) == ""


# ===== _is_retryable =====

def test_is_retryable():
    request = httpx.Request("POST", "http://test")
    assert lc._is_retryable(APIConnectionError(request=request)) is True
    assert lc._is_retryable(_make_status_error(429)) is True
    assert lc._is_retryable(_make_status_error(500)) is True
    assert lc._is_retryable(_make_status_error(400)) is False
    assert lc._is_retryable(ValueError("x")) is False


# ===== _to_int / 归一化 =====

@pytest.mark.parametrize("val,expected", [
    ("3", 3), ("3.7", 3), (3.7, 3), (True, 1), (5, 5), ("abc", 0), (None, 0),
])
def test_to_int(val, expected):
    assert lc._to_int(val) == expected


def test_normalize_value():
    assert lc._normalize_value(int, "3") == 3
    assert lc._normalize_value(int, 3.9) == 3
    assert lc._normalize_value(str, 42) == "42"
    assert lc._normalize_value(bool, "true") is True
    assert lc._normalize_value(bool, False) is False
    assert lc._normalize_value(list[int], "not-a-list") == []
    assert lc._normalize_value(list[FakeModel], ["junk"]) == []
    assert lc._normalize_value(dict, {"a": 1}) == {"a": 1}
    assert lc._normalize_value(FakeModel, {"name": "x"})["name"] == "x"
    assert lc._normalize_value(Optional[str], None) is None


def test_normalize_for_model_skips_unknown_keys():
    out = lc._normalize_for_model(FakeModel, {"name": "n", "count": "7", "extra": "drop"})
    assert out == {"name": "n", "count": 7}
    assert lc._normalize_for_model(FakeModel, "not-dict") == "not-dict"


# ===== _validate_with_model =====

def test_validate_with_model_valid():
    out = lc._validate_with_model(FakeModel, {"name": "a", "count": 3, "tags": ["t"]})
    assert out == {"name": "a", "count": 3, "tags": ["t"]}


def test_validate_with_model_invalid_type_normalized():
    # count 是字符串数字 → 归一化后通过
    out = lc._validate_with_model(FakeModel, {"name": "a", "count": "7"})
    assert out["count"] == 7


def test_validate_with_model_non_dict_raises():
    with pytest.raises(ValueError):
        lc._validate_with_model(FakeModel, ["junk"])


def test_validate_with_model_fallback_on_unrecoverable():
    # count 无法归一化 → 兜底返回归一化 dict（接口不崩）
    out = lc._validate_with_model(FakeModel, {"count": "not-a-number"})
    assert isinstance(out, dict)
    assert out["count"] == 0


# ===== 真实模型：BreakdownResult / InnovationResult =====

def test_validate_breakdown_with_missing_fields():
    out = lc._validate_with_model(BreakdownResult, {"summary": "s"})
    assert out["summary"] == "s"
    assert out["background"] == ""
    assert out["key_points"] == []


def test_validate_innovation_string_page_ref():
    out = lc._validate_with_model(
        InnovationResult,
        {"core_innovations": [{"title": "t", "page_ref": "3"}], "innovation_level": "高"},
    )
    assert out["core_innovations"][0]["page_ref"] == 3
    assert isinstance(out["core_innovations"][0], dict)


# ===== chat_json：JSON 容错 + response_model =====
# 注：chat_json 的调用接缝是 _chat_content（返回 (content, finish_reason)），
# finish_reason 供截断重试判断（P-BUG-2a），mock 一律返回二元组。


@pytest.mark.asyncio
async def test_chat_json_valid_with_model(monkeypatch):
    client = LLMClient()
    monkeypatch.setattr(
        client, "_chat_content",
        AsyncMock(return_value=(json.dumps({"name": "x", "count": "2"}), "stop")),
    )
    out = await client.chat_json(
        [{"role": "system", "content": "json"}, {"role": "user", "content": "hi"}],
        response_model=FakeModel,
    )
    assert out["count"] == 2


@pytest.mark.asyncio
async def test_chat_json_recovers_from_code_blocks(monkeypatch):
    # 响应被 ```json``` 包裹 → 剥围栏后解析
    client = LLMClient()
    monkeypatch.setattr(
        client, "_chat_content",
        AsyncMock(return_value=('```json\n{"name": "x", "count": 1}\n```', "stop")),
    )
    out = await client.chat_json([{"role": "user", "content": "hi"}])
    assert out["name"] == "x"


@pytest.mark.asyncio
async def test_chat_json_invalid_raises(monkeypatch):
    client = LLMClient()
    monkeypatch.setattr(client, "_chat_content", AsyncMock(return_value=("not json at all", "stop")))
    with pytest.raises(ValueError):
        await client.chat_json([{"role": "user", "content": "hi"}])


# ===== P2-2：失败日志不得残留论文内容（响应正文） =====

@pytest.mark.asyncio
async def test_chat_json_failure_log_excludes_content(monkeypatch, caplog):
    # P2-2 回归：JSON 解析失败的最终 WARNING 只留元信息（finish_reason/长度），
    # 不得把响应正文（可能含用户论文内容）写进日志
    import logging

    client = LLMClient()
    marker = "SECRET_PAPER_MARKER_绝密论文正文片段"
    monkeypatch.setattr(
        client, "_chat_content",
        AsyncMock(return_value=(f"{marker} not json at all", "stop")),
    )
    # caplog 的 handler 挂在 root logger，paperpilot logger 默认 propagate=False，
    # 测试期间临时打开传播（monkeypatch 自动还原）
    monkeypatch.setattr(lc.logger, "propagate", True)
    with caplog.at_level(logging.DEBUG, logger=lc.logger.name):
        with pytest.raises(ValueError):
            await client.chat_json([{"role": "user", "content": "hi"}])

    assert "JSON 解析失败" in caplog.text, "失败告警应存在（含 finish_reason/长度元信息）"
    assert "finish_reason=stop" in caplog.text, "告警应保留 finish_reason 元信息"
    assert marker not in caplog.text, "失败日志不得携带响应正文片段"
    assert "not json at all" not in caplog.text


@pytest.mark.asyncio
async def test_chat_content_debug_log_excludes_content(monkeypatch):
    # P2-2 回归：_chat_content 的 debug 日志同样只留 length/finish_reason，
    # 不再有 preview=...（响应正文截断预览）
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    client = LLMClient()
    marker = "SECRET_PAPER_MARKER_debug"

    choice = type("Choice", (), {})()
    choice.message = type("Msg", (), {})()
    choice.message.content = f"{marker} " + json.dumps({"a": 1})
    choice.finish_reason = "stop"
    response = type("Response", (), {})()
    response.choices = [choice]
    monkeypatch.setattr(client, "_create_with_retry", AsyncMock(return_value=response))

    debug_calls = []
    monkeypatch.setattr(lc.logger, "debug", lambda *a, **k: debug_calls.append(a))

    content, finish_reason = await client._chat_content(
        messages=[], temperature=0.2, max_tokens=10, response_format=None,
    )

    assert marker in content, "返回值仍是完整正文（业务路径不受日志清洗影响）"
    assert finish_reason == "stop"
    assert marker not in str(debug_calls), "debug 日志不得包含响应正文"
    assert all("preview" not in str(a) for a in debug_calls)


@pytest.mark.asyncio
async def test_chat_json_parses_with_trailing_prose_after_fence(monkeypatch):
    # 回归（终审 P1）：LLM 在闭合围栏后追加 Markdown 说明文字 → 尾围栏不在
    # 字符串末尾，_strip_code_fence 剥不掉，json.loads 报 Extra data；
    # 依赖贪婪提取兜底（恢复旧实现 r"\{.*\}" 行为）。
    client = LLMClient()
    raw = '```json\n{"a": 1}\n```\n\n**重要说明**：以上即结果，请注意"引号"与（括号）'
    monkeypatch.setattr(client, "_chat_content", AsyncMock(return_value=(raw, "stop")))
    out = await client.chat_json([{"role": "user", "content": "hi"}])
    assert out == {"a": 1}


@pytest.mark.asyncio
async def test_chat_json_adds_json_instruction(monkeypatch):
    # 不真正调用 LLM：验证 system 提示词被追加 json 要求
    client = LLMClient()

    async def fake_chat_content(**kwargs):
        msgs = kwargs["messages"]
        assert "json" in msgs[0]["content"].lower()
        assert msgs[0]["content"] != "请分析"
        return "{}", "stop"

    monkeypatch.setattr(client, "_chat_content", fake_chat_content)
    await client.chat_json([{"role": "system", "content": "请分析"}, {"role": "user", "content": "hi"}])


# ===== _strip_think_tags（P-MiniMax-1 核心兜底，回归：大小写变体不能绕过） =====

def test_strip_think_tags_basic():
    assert lc._strip_think_tags("<think>reasoning</think>{\"a\": 1}") == '{"a": 1}'


def test_strip_think_tags_case_insensitive():
    # 大小写变体（<Think>/<THINK>）曾绕过快速路径导致 json.loads 失败
    for variant in ("<Think>", "<THINK>", "<tHiNk>"):
        content = f"{variant}chain of thought</Think>{{\"a\": 1}}"
        assert lc._strip_think_tags(content) == '{"a": 1}', f"变体 {variant} 未被剥离"


def test_strip_think_tags_no_tags_passthrough():
    content = "普通响应，无任何思考标签"
    assert lc._strip_think_tags(content) == content
    assert lc._strip_think_tags("") == ""


def test_strip_think_tags_standalone_open_tag():
    # 只有开标签没有闭标签：正则不匹配，原样返回（不误删正文）
    content = '我说的是 <think 这个词 {"a": 1}'
    assert lc._strip_think_tags(content) == content


# ===== chat_json 不原地修改调用方 messages =====

@pytest.mark.asyncio
async def test_chat_json_does_not_mutate_caller_messages(monkeypatch):
    client = LLMClient()
    monkeypatch.setattr(client, "_chat_content", AsyncMock(return_value=('{"a": 1}', "stop")))
    messages = [{"role": "system", "content": "请分析"}, {"role": "user", "content": "hi"}]
    snapshot = [dict(m) for m in messages]
    await client.chat_json(messages)
    await client.chat_json(messages)  # 复用同一列表（重试/缓存场景）
    assert messages == snapshot, "chat_json 不得原地修改调用方传入的 messages（重复调用会重复追加 JSON 指令）"


# ===== response_format=json_object 不兼容网关降级 =====

@pytest.mark.asyncio
async def test_chat_json_falls_back_without_response_format(monkeypatch):
    # 网关对 response_format 返回 400 → 去掉该参数重试一次
    client = LLMClient()
    calls = []

    async def fake_chat_content(**kwargs):
        calls.append(kwargs.get("response_format"))
        if kwargs.get("response_format") is not None:
            raise _make_status_error(400)
        return '{"a": 1}', "stop"

    monkeypatch.setattr(client, "_chat_content", fake_chat_content)
    out = await client.chat_json([{"role": "user", "content": "hi"}])
    assert out == {"a": 1}
    assert calls[0] == {"type": "json_object"}
    assert calls[1] is None, "降级重试不应再带 response_format"


@pytest.mark.asyncio
async def test_chat_json_non_400_status_not_degraded(monkeypatch):
    # 500 在 chat 内部重试耗尽后抛出，不属于"网关不支持 response_format"，不降级
    client = LLMClient()
    calls = []

    async def fake_chat_content(**kwargs):
        calls.append(1)
        raise _make_status_error(500)

    monkeypatch.setattr(client, "_chat_content", fake_chat_content)
    with pytest.raises(Exception):
        await client.chat_json([{"role": "user", "content": "hi"}])
    assert len(calls) == 1, "非 400 不应触发降级重试"


# ===== 截断 JSON 修复 + finish_reason=length 加倍重试（P-BUG-2a） =====

@pytest.mark.asyncio
async def test_chat_json_repairs_truncated_output(monkeypatch):
    # finish_reason=length 截断：宽松解析 + 截断修复应兜底成功（丢尾部数据但结构有效）
    client = LLMClient()
    truncated = '{"a": {"b": "x", "c": [1, 2'
    monkeypatch.setattr(client, "_chat_content", AsyncMock(return_value=(truncated, "length")))
    out = await client.chat_json([{"role": "user", "content": "hi"}])
    assert out == {"a": {"b": "x", "c": [1, 2]}}


@pytest.mark.asyncio
async def test_chat_json_retries_with_doubled_tokens_on_truncation(monkeypatch):
    # 截断且无法修复（修复结果不是 dict）→ max_tokens 加倍完整重试一次
    client = LLMClient()
    client.max_tokens_override = 0  # 隔离 .env 的 LLM_MAX_TOKENS，保证断言只依赖入参
    calls = []

    async def fake_chat_content(**kwargs):
        calls.append(kwargs["max_tokens"])
        if len(calls) == 1:
            return "garbage no json", "length"
        return '{"ok": 1}', "stop"

    monkeypatch.setattr(client, "_chat_content", fake_chat_content)
    out = await client.chat_json([{"role": "user", "content": "hi"}], max_tokens=1000)
    assert out == {"ok": 1}
    assert len(calls) == 2
    assert calls[1] == calls[0] * 2, "截断重试应把 max_tokens 翻倍"


# ===== _create_with_retry =====

@pytest.mark.asyncio
async def test_retry_succeeds_after_rate_limit(monkeypatch):
    client = LLMClient()
    create = AsyncMock(side_effect=[_make_status_error(429), "ok"])
    client.client.chat.completions.create = create
    sleeps = []
    monkeypatch.setattr(lc.asyncio, "sleep", AsyncMock(side_effect=lambda s: sleeps.append(s)))
    result = await client._create_with_retry(model="m", messages=[])
    assert result == "ok"
    assert create.call_count == 2
    assert len(sleeps) == 1


@pytest.mark.asyncio
async def test_retry_exhausted_raises(monkeypatch):
    client = LLMClient()
    err = _make_status_error(429)
    create = AsyncMock(side_effect=err)
    client.client.chat.completions.create = create
    monkeypatch.setattr(lc.asyncio, "sleep", AsyncMock())
    with pytest.raises(RateLimitError):
        await client._create_with_retry(model="m", messages=[])
    assert create.call_count == lc.RETRY_MAX_RETRIES + 1


@pytest.mark.asyncio
async def test_retry_non_retryable_raised_immediately(monkeypatch):
    client = LLMClient()
    err = _make_status_error(400)
    create = AsyncMock(side_effect=err)
    client.client.chat.completions.create = create
    monkeypatch.setattr(lc.asyncio, "sleep", AsyncMock())
    with pytest.raises(BadRequestError):
        await client._create_with_retry(model="m", messages=[])
    assert create.call_count == 1


@pytest.mark.asyncio
async def test_chat_empty_content_raises(monkeypatch):
    """P3-2: chat() 已删除，空 content 判错守卫（P1-Low，位于 _chat_content）
    改经唯一生产路径 chat_json 验证：choices 为空 / content 为空应抛 ValueError"""
    client = LLMClient()
    empty = type("M", (), {"content": None})()
    client.client.chat.completions.create = AsyncMock(
        return_value=type("C", (), {"message": empty})(),
    )
    with pytest.raises(ValueError):
        await client.chat_json([{"role": "user", "content": "hi"}])
