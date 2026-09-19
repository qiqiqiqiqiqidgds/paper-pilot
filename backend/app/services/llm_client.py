"""
LLM 客户端：封装 OpenAI 兼容 chat.completions 接口

支持多家 provider:DeepSeek / MiniMax(M2/M2.5/M2.7/M3) / OpenAI / 任意 OpenAI 兼容网关。

P1-10: 修复 prompt 内容日志泄露
- 旧版 `logger.debug(f"LLM 响应: {content[:200]}...")` 会写入用户上传的论文内容
- 改为只记录长度 + 首字符诊断，不写入实际内容

P1-P0: 结构化校验
- chat_json 支持可选 response_model：json.loads 后用 Pydantic 校验，
  校验失败做容错归一化（字符串数字→int、漏字段补默认值），不整体 500。
- 指数退避重试：429 / 5xx / 超时 / 网络错误重试最多 3 次（1s/2s/4s + jitter）。

P-MiniMax-1: MiniMax M3 思考标签后处理
- 实测 MiniMax-M3 即便传 reasoning_split=True,content 仍含 <think>...</think> 标签
  (而非按官方文档所述分离到 reasoning_details 字段)。该标签会让 json.loads() 失败
  → PaperPilot Map 阶段全失败 → Reduce 无输入 → 502。
- chat_json() 在 JSON 解析前调用 _strip_think_tags() 兜底剥离。
"""
import asyncio
import inspect
import json
import random
import re
from typing import Any, Dict, List, Optional, Union, get_args, get_origin, get_type_hints

from openai import AsyncOpenAI, APIError, APIConnectionError, APIStatusError, APITimeoutError, RateLimitError
from pydantic import BaseModel, ValidationError

from app.services.runtime_settings import LLMConnConfig, runtime_settings
from app.utils.logger import logger


# 控制字符 + 日志注入防护
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")

# MiniMax 思考标签剥离（兼容 <think>...</think> 及其跨行变体）。
# 也兼容 <|think|>...</think|> 风格(实测 MiniMax 当前用的是普通 <think>,
# 但留个口子以防 provider 后续改用 chatml 风格)。
# DOTALL 必须打开,标签内可跨行。
_THINK_TAG_RE = re.compile(
    r"<\s*(?:\|\s*)?think\s*(?:\|\s*)?>.*?<\s*/\s*(?:\|\s*)?think\s*(?:\|\s*)?\s*>",
    re.IGNORECASE | re.DOTALL,
)

# 快速探测正则：与 _THINK_TAG_RE 的标签开头语义一致（含 </think> 闭标签变体），
# 仅供快速路径判断"有没有必要跑完整剥离"。注意必须与主正则一样 IGNORECASE，
# 否则 <Think> 这类大小写变体会绕过快速路径、漏掉剥离导致 json.loads 失败。
_THINK_TAG_PROBE_RE = re.compile(r"<\s*/?\s*(?:\|\s*)?think", re.IGNORECASE)


# 重试参数（参考 search_client.py 风格）
RETRY_MAX_RETRIES = 3            # 最多重试 3 次（共 4 次尝试）
RETRY_BACKOFF_BASE = 1.0         # 1s
RETRY_BACKOFF_FACTOR = 2.0       # 2^n → 1s / 2s / 4s
RETRY_JITTER_MAX = 0.5           # 退避抖动上限（秒）

# JSON 输出因 finish_reason=length 截断时的重试输出预算上限（tokens）
TRUNCATION_RETRY_MAX_TOKENS = 32768

# 缺 LLM_API_KEY 时的明确报错（根因透出给用户，避免「Map 全失败」式晦涩文案）
MISSING_KEY_MESSAGE = (
    "LLM_API_KEY 未配置，无法调用大模型（请在 backend/.env 中配置 LLM_API_KEY 后重启）"
)


class LLMConfigError(ValueError):
    """LLM 未配置/配置错误（区别于 LLM 调用失败）"""


def _sanitize_for_log(text: str, max_len: int = 120) -> str:
    """
    为日志清洗字符串：移除控制字符 + 截断
    不用于业务逻辑，仅供日志展示
    """
    if not text:
        return ""
    cleaned = _CONTROL_CHARS_RE.sub("", text)
    return cleaned[:max_len]


def _strip_think_tags(content: str) -> str:
    """
    剥离 MiniMax 等 provider 在 content 字段中混入的 <think>...</think> 标签。

    背景:官方文档说传 extra_body={"reasoning_split": True} 会把思考分离到
    reasoning_details 字段,但实测 MiniMax-M3 仍然在 content 里带 <think> 标签;
    此外某些 provider 可能用 <|think|> 变体。本函数对两种都兼容。

    行为:删除所有 <think>...</think> 块(包括首尾空白),保留其余内容;
    如果剥离后为空(纯思考模型无正文),返回原始字符串(由上层决定如何处理)。

    注意:仅用于业务解析路径(JSON 解析前的清洗),不会修改日志/调试用的原始 content。
    """
    if not content:
        return content
    if not _THINK_TAG_PROBE_RE.search(content):
        return content
    cleaned = _THINK_TAG_RE.sub("", content)
    # 去掉因剥标签产生的连续空行
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned or content  # 兜底:若清洗后为空,保留原文(避免误清空)


def _strip_code_fence(content: str) -> str:
    """
    去掉 LLM 输出外围的 Markdown 代码围栏（```json ... ``` / ``` ... ```）。
    json.loads 不接受围栏；旧实现靠 r"\\{.*\\}" 正则绕过，但截断输出（无尾部围栏）
    时该正则可能捕到错误范围，解析前先显式剥离更稳。
    """
    s = content.strip()
    if s.startswith("```"):
        first_nl = s.find("\n")
        head = s[:first_nl].strip() if first_nl != -1 else s
        if head.lstrip("`").strip().lower() in ("", "json"):
            s = s[first_nl + 1:] if first_nl != -1 else ""
    if s.rstrip().endswith("```"):
        s = s.rstrip()[:-3]
    return s.strip()


# 标量字面量字符（JSON number / true / false / null）
_SCALAR_CHARS = set("0123456789+-.eEtfanl")


def _repair_truncated_json(text: str) -> Optional[str]:
    """
    修复被截断的 JSON 输出（finish_reason=length 时 LLM 常在字符串/对象中途被截）。

    策略：单遍扫描，记录字符串/转义/括号栈/是否处于"期望值"位；
    维护一个"安全切割点"——即已完成一个完整 VALUE 的位置（值字符串闭合、
    标量结束、括号闭合、或对象/数组内的逗号处）。截断发生后，回退到最后一个
    安全点、丢弃其后不完整片段、去尾逗号、按栈逆序补全闭合符。

    无法找到任何安全点时返回 None（调用方走重试或报错）。
    只做结构级修复，不校验业务字段（交给上层 response_model 校验）。
    """
    s = _strip_code_fence(text)
    stack: list = []                 # 未闭合的 '{' / '['
    expect_value_stack: list = []    # 与栈对应的期望值标志（'{' 开: False 等 key；'[' 开: True）
    in_string = False
    escaped = False
    pending_key = False              # 当前字符串是否为对象的 key（位于 '{' / ',' 之后、':' 之前）
    scalar_active = False            # 标量（number/true/false/null）扫描中
    best_prefix: Optional[str] = None
    best_stack: Optional[list] = None
    buf: list = []

    def _mark_clean() -> None:
        nonlocal best_prefix, best_stack
        best_prefix = "".join(buf)
        best_stack = stack.copy()

    for ch in s:
        if in_string:
            buf.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
                # 只有"值字符串"闭合才是安全点；key 字符串闭合后还差冒号和值
                if not pending_key:
                    _mark_clean()
            continue
        if ch == '"':
            in_string = True
            escaped = False
            buf.append(ch)
            continue
        if scalar_active and ch not in _SCALAR_CHARS:
            scalar_active = False
            if expect_value_stack and expect_value_stack[-1]:
                _mark_clean()
        if ch in "{[":
            stack.append(ch)
            expect_value_stack.append(ch == "[")
            pending_key = ch == "{"
            buf.append(ch)
        elif ch in "}]":
            if not stack:
                return None  # 前缀本身非法（多余闭括号），交给上层报错
            expected_open = "{" if ch == "}" else "["
            if stack[-1] != expected_open:
                return None  # 交叉闭合，前缀非法
            stack.pop()
            expect_value_stack.pop()
            buf.append(ch)
            _mark_clean()
        elif ch == ":":
            pending_key = False
            if expect_value_stack:
                expect_value_stack[-1] = True
            buf.append(ch)
        elif ch == ",":
            # 逗号永远是安全点：丢弃其后的不完整片段后仍可闭合
            buf.append(ch)
            _mark_clean()
            # 逗号后：对象等 key（expect_value=False），数组等 value（True）
            if expect_value_stack:
                expect_value_stack[-1] = stack[-1] == "["
            scalar_active = False
        else:
            if ch in _SCALAR_CHARS:
                scalar_active = True
            buf.append(ch)

    # 输入在标量中途结束：最后一段标量本身是完整值（截断恰好落在值之后）
    if scalar_active and expect_value_stack and expect_value_stack[-1]:
        _mark_clean()

    if best_prefix is None or best_stack is None:
        return None
    out = best_prefix.rstrip()
    if out.endswith(","):
        out = out[:-1].rstrip()
    closers = {"{": "}", "[": "]"}
    for open_ch in reversed(best_stack):
        out += closers[open_ch]
    return out


def _parse_json_lenient(content: str) -> Optional[Dict[str, Any]]:
    """
    宽松 JSON 解析：剥离围栏 → 直接 loads → 贪婪提取 → 截断修复后 loads。
    成功返回 dict，失败返回 None（不抛异常，由调用方决定重试/报错）。

    每步 loads 都先 strict=True、失败再 strict=False：
    DeepSeek/MiniMax 处理中文长摘要时常在字符串值里输出裸换行/Tab 等
    控制字符（finish_reason=stop 但 JSON 非法），strict=False 允许字符串
    内的控制字符，是这类"看起来完整却解析不了"输出的兜底。
    """
    candidates = [content]
    fenced = _strip_code_fence(content)
    if fenced != content:
        candidates.insert(0, fenced)
    for cand in candidates:
        for strict in (True, False):
            try:
                parsed = json.loads(cand, strict=strict)
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                continue
    # LLM 可能在闭合围栏后追加说明文字（```json...``` + Markdown 散文）：
    # 此时尾围栏不在字符串末尾，_strip_code_fence 剥不掉，json.loads 报
    # "Extra data"。恢复旧实现的贪婪提取兜底（首 { 到末 }）——正文后 prose
    # 不含大括号时可完整恢复；提取失败则继续走截断修复。
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if m:
        for strict in (True, False):
            try:
                parsed = json.loads(m.group(0), strict=strict)
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                pass
    repaired = _repair_truncated_json(content)
    if repaired is not None:
        for strict in (True, False):
            try:
                parsed = json.loads(repaired, strict=strict)
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                continue
    return None


def _is_retryable(exc: BaseException) -> bool:
    """判断异常是否值得重试（429 / 5xx / 超时 / 网络错误）"""
    if isinstance(exc, APITimeoutError):
        return True
    if isinstance(exc, APIConnectionError):
        return True
    if isinstance(exc, RateLimitError):
        return True
    if isinstance(exc, APIStatusError) and exc.status_code >= 500:
        return True
    return False


def _unwrap_optional(ann: Any) -> Any:
    """剥掉 Optional[X] / X | None，返回实际类型"""
    if get_origin(ann) in (Union, Union.__class__):
        args = [a for a in get_args(ann) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return ann


def _to_int(val: Any) -> int:
    """把任意值容错转 int（"3" / 3.7 / True → int；失败给 0）"""
    if isinstance(val, bool):
        return int(val)
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    if isinstance(val, str):
        s = val.strip()
        try:
            return int(float(s))
        except ValueError:
            return 0
    return 0


def _normalize_value(ann: Any, val: Any) -> Any:
    """按类型注解容错归一化单个值（不校验，只做类型贴合）"""
    if val is None:
        return None
    ann = _unwrap_optional(ann)
    if ann is int:
        return _to_int(val)
    if ann is str:
        return str(val)
    if ann is float:
        try:
            return float(val)
        except (TypeError, ValueError):
            return 0.0
    if ann is bool:
        if isinstance(val, bool):
            return val
        return str(val).lower() in ("true", "1", "yes")
    origin = get_origin(ann)
    if origin is list:
        (item_ann,) = get_args(ann) or (Any,)
        if not isinstance(val, list):
            return []
        items = []
        for v in val:
            # List[Model] 里的非对象元素直接丢弃（避免垃圾混入结构）
            if isinstance(item_ann, type) and issubclass(item_ann, BaseModel) and not isinstance(v, dict):
                continue
            items.append(_normalize_value(item_ann, v))
        return items
    if origin is dict:
        return val if isinstance(val, dict) else {}
    if isinstance(ann, type) and issubclass(ann, BaseModel):
        if isinstance(val, dict):
            return _normalize_for_model(ann, val)
        return val
    return val


def _normalize_for_model(model: type[BaseModel], raw: dict) -> dict:
    """按模型字段注解把 LLM 输出归一化（字段缺失保留，由校验器补默认值）"""
    if not isinstance(raw, dict):
        return raw
    hints = get_type_hints(model, include_extras=True)
    out = {}
    for name, field_info in model.model_fields.items():
        if name not in raw:
            continue
        ann = hints.get(name, field_info.annotation)
        out[name] = _normalize_value(ann, raw[name])
    return out


def _validate_with_model(model: type[BaseModel], raw: Any) -> dict:
    """
    用 Pydantic 校验 LLM 输出并返回 dict。

    保证：返回的 dict 字段与模型字段一一对应（与旧 raw dict 字段名完全一致），
    字段缺失给默认值、字符串数字转 int。校验失败时做容错降级，不抛异常
    （除非 raw 根本不是 dict —— 那属于上层无法恢复的情况）。
    """
    if not isinstance(raw, dict):
        raise ValueError(f"LLM 返回不是对象（{type(raw).__name__}），无法按 {model.__name__} 校验")
    try:
        return model.model_validate(raw).model_dump(exclude_none=True)
    except ValidationError as e:
        # 第一道校验失败：记录错误摘要（不写原文），再尝试容错归一化
        err_summary = "; ".join(str(x.get("loc")) for x in e.errors())[:200]
        logger.warning(
            "LLM 结构化校验失败（%s），尝试容错归一化: %s",
            model.__name__, err_summary or type(e).__name__,
        )
        normalized = _normalize_for_model(model, raw)
        try:
            return model.model_validate(normalized).model_dump(exclude_none=True)
        except ValidationError:
            # 兜底：返回容错归一化后的 dict（等价于"跳过校验返回 raw"），保证接口不崩
            logger.warning("LLM 结构化校验仍失败（%s），返回容错归一化结果", model.__name__)
            return normalized


class LLMClient:
    """LLM 客户端（OpenAI 兼容 chat.completions 协议，支持 MiniMax / DeepSeek / OpenAI 等）

    配置来源：传入 config（网页端设置 / 连接测试）或缺省取 runtime_settings
    合并后的生效配置（.env 兜底 + data/settings.json 覆盖）。
    """

    def __init__(self, config: Optional[LLMConnConfig] = None):
        if config is None:
            config = runtime_settings.effective_llm()
        if not config.api_key:
            logger.warning("LLM_API_KEY 未配置，LLM 调用将失败")

        # 配置在构造时快照为实例属性（_chat_content 不再读全局 settings，
        # 网页端改配置后由 get_llm_client() 按指纹重建整个客户端）
        self._api_key = config.api_key
        self._base_url = config.base_url
        self._reasoning_effort = config.reasoning_effort
        self._reasoning_split = config.reasoning_split

        self.client = AsyncOpenAI(
            api_key=config.api_key or "EMPTY",
            base_url=config.base_url,
            # 单次 HTTP 请求超时（可配）。注意与 llm_timeout_seconds（阶段整体超时）
            # 是两层：SDK 层管单次请求，整体超时管"含重试的全部耗时"。
            timeout=config.request_timeout_seconds,
        )
        self.model = config.model
        # 单次 chat 最大输出 tokens(0 = 用 chat/chat_json 形参默认 4000)
        self.max_tokens_override = max(0, int(config.max_tokens or 0))

        # P0-0: capability check —— reasoning_effort 只在底层 SDK 支持时才透传。
        # 背景: mimo-v2.5-free / opencode.ai/zen 等第三方 provider 不支持该参数，
        # 不分青红皂白透传会导致 TypeError,所有 LLM 调用 100% 失败。
        # 用 inspect 检查 SDK 真实签名,而非依赖文档约定。
        try:
            sig_params = inspect.signature(
                self.client.chat.completions.create
            ).parameters
            self._supports_reasoning_effort = "reasoning_effort" in sig_params
        except (TypeError, ValueError):
            # 部分 mock / 包装类没有 inspect 签名,保守按"不支持"处理
            self._supports_reasoning_effort = False

        if self._reasoning_effort and not self._supports_reasoning_effort:
            logger.warning(
                "当前 LLM SDK 不支持 reasoning_effort 参数(忽略配置值 %r),"
                "若确实需要推理强度控制,请升级 openai SDK 或换 provider",
                self._reasoning_effort,
            )
        logger.info(
            f"LLM 客户端初始化: {self.model} @ {self._base_url} "
            f"(reasoning_effort supported={self._supports_reasoning_effort}, "
            f"reasoning_split={self._reasoning_split}, "
            f"max_tokens_override={self.max_tokens_override or 'default'})"
        )

    async def test_connection(self) -> Dict[str, Any]:
        """轻量连通性探测：一次 1-token 的 chat 调用（验证 base_url / key / model）。

        不重试、不抛异常，结果以 {"ok": bool, "message": str} 返回，
        供 POST /api/settings/test 使用。
        """
        if not self._api_key:
            return {"ok": False, "message": "API Key 未配置"}
        try:
            await asyncio.wait_for(
                self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=1,
                    stream=False,
                ),
                timeout=30.0,
            )
            return {"ok": True, "message": f"连接成功（{self.model} @ {self._base_url}）"}
        except Exception as e:
            # 错误信息经 _sanitize_for_log 截断去控制字符（provider 报错里可能回显 URL/key 片段）
            return {
                "ok": False,
                "message": f"{type(e).__name__}: {_sanitize_for_log(str(e), 160)}",
            }

    async def _create_with_retry(self, **kwargs) -> Any:
        """
        带指数退避的 chat.completions.create（P1-P0）
        429 / 5xx / 超时 / 网络错误重试最多 3 次，退避 1s/2s/4s + jitter。
        其余异常（编程错误、4xx 业务错误）直接抛，不重试。
        """
        last_exc: Optional[BaseException] = None
        for attempt in range(RETRY_MAX_RETRIES + 1):
            try:
                return await self.client.chat.completions.create(**kwargs)
            except APIError as e:
                last_exc = e
                if not _is_retryable(e):
                    raise
                if attempt >= RETRY_MAX_RETRIES:
                    break
                backoff = RETRY_BACKOFF_BASE * (RETRY_BACKOFF_FACTOR ** attempt)
                backoff += random.uniform(0, RETRY_JITTER_MAX)
                logger.warning(
                    "LLM 调用失败，%.1fs 后重试（第 %d/%d 次）: %s",
                    backoff, attempt + 1, RETRY_MAX_RETRIES, type(e).__name__,
                )
                await asyncio.sleep(backoff)
        # 到这里说明重试已耗尽
        raise last_exc if last_exc else RuntimeError("LLM 调用重试逻辑异常")

    # P3-2: 删除无调用方的 chat()（历史遗留的非 JSON 文本对话接口；
    # 全项目所有 LLM 调用均走 chat_json()，见 Grep 确认）

    async def _chat_content(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_format: Optional[Dict[str, str]],
    ) -> tuple:
        """
        chat.completions 的实现体，返回 (content, finish_reason)。
        finish_reason 供 chat_json 判断输出是否因长度截断（"length"），
        以决定是否加倍 max_tokens 重试。带 <think> 标签的原样返回
        （由 chat_json() 在 JSON 解析前统一剥离）。
        """
        if not self._api_key:
            # 缺 key 立即抛明确异常（测试环境 mock 了 chat_json，不会走到这里）
            raise LLMConfigError(MISSING_KEY_MESSAGE)

        try:
            effective_max_tokens = max(max_tokens, self.max_tokens_override) if self.max_tokens_override else max_tokens
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": effective_max_tokens,
                "stream": False,
            }
            if self._reasoning_effort and self._supports_reasoning_effort:
                kwargs["reasoning_effort"] = self._reasoning_effort
            if response_format:
                kwargs["response_format"] = response_format
            # P-MiniMax-1: 让 MiniMax 尽量把思考分离(实测仍会混入 content,后端 chat_json 兜底剥离)
            if self._reasoning_split:
                kwargs["extra_body"] = {"reasoning_split": True}

            response = await self._create_with_retry(**kwargs)
            choices = getattr(response, "choices", None)
            content = choices[0].message.content if choices else None
            if not content:
                # P1-Low: 判空给友好报错（不要从 None 上取方法）
                raise ValueError("LLM 返回内容为空（choices 为空或 content 为空）")
            finish_reason = getattr(choices[0], "finish_reason", None)
            # P1-10: 不再记录完整响应内容（可能含用户上传的论文原文）
            # P2-2: 连截断 preview 也一并移除 —— 响应正文即使只留前 80 字也属
            # 论文内容（_sanitize_for_log 只去控制字符不去内容），多用户部署
            # 开 debug 日志同样有隐私合规风险；只记录长度 + finish_reason 元信息
            logger.debug(
                "LLM 响应: length=%d finish_reason=%s",
                len(content), finish_reason,
            )
            return content, finish_reason

        except Exception as e:
            logger.error(f"LLM 调用失败: {type(e).__name__}: {_sanitize_for_log(str(e), 160)}")
            raise

    async def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 4000,
        response_model: Optional[type[BaseModel]] = None,
    ) -> Dict[str, Any]:
        """
        JSON 模式对话：要求 LLM 返回 JSON，并按需用 Pydantic 结构化校验。

        :param response_model: 可选。传入时，json.loads 后会用该模型校验并返回
              其 model_dump() 结果（字段名与模型一致，缺失补默认值、字符串数字转 int）。
              不传则行为与旧版完全一致（直接返回 raw dict）。
        """
        # 确保 system prompt 强调 JSON
        # 先浅拷贝一份再改：避免原地修改调用方传入的 messages（若调用方复用/重试同一列表，
        # 旧实现会重复追加 JSON 指令）
        messages = [dict(m) for m in messages]
        if messages and messages[0].get("role") == "system":
            if "json" not in messages[0]["content"].lower():
                messages[0]["content"] += "\n\n请严格以 JSON 格式输出，不要包含任何其他内容。"

        async def _call(max_tokens: int, use_response_format: bool) -> tuple:
            try:
                return await self._chat_content(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"} if use_response_format else None,
                )
            except APIStatusError as e:
                # 部分自建/第三方 OpenAI 兼容网关不支持 response_format 参数，返回 400。
                # 去掉该参数重试一次（system prompt 已强调 JSON 输出），而不是让所有 JSON 调用全灭。
                if e.status_code != 400 or not use_response_format:
                    raise
                logger.warning(
                    "LLM 网关拒绝 response_format=json_object（400），去掉该参数重试一次: %s",
                    _sanitize_for_log(str(e), 120),
                )
                return await self._chat_content(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format=None,
                )

        async def _sample(budget: int) -> tuple:
            """调用一次并剥离 <think> 标签，返回 (content, finish_reason)"""
            c, fr = await _call(budget, True)
            s = _strip_think_tags(c)
            if s != c and s:
                logger.debug(
                    "chat_json: stripped <think> tags (orig_len=%d stripped_len=%d)",
                    len(c), len(s),
                )
                c = s
            return c, fr

        content, finish_reason = await _sample(max_tokens)
        raw = _parse_json_lenient(content)

        # 解析失败的修复路径（每条至多触发一次，合计最多再调 2 次 LLM）：
        # ① finish_reason=length：输出预算加倍完整重试（BUG-2 修复，见下）；
        # ② finish_reason=stop 但内容仍非法（围栏/裸换行/坏样本）：同参数
        #    重新采样一次——LLM 偶发输出坏 JSON，换个样本通常就好了；
        #    重采样后若变为 length 截断，仍允许走一次 ①。
        # 此前只有 length 会重试，stop+非法 JSON 会直接让整个分析链失败
        # （2026-09-06 GUI 实测：Map/Reduce 各因该原因失败一次，需手动点重试）。
        doubled = False
        resampled = False
        while raw is None:
            if finish_reason == "length" and not doubled:
                # BUG-2 修复：MiniMax-M3 等推理模型会把大量 token 花在 <think> 上，
                # max_tokens 预算耗尽后 JSON 在中途被截断（finish_reason=length）。
                # 宽松解析/结构修复只是"能解析"，会丢尾部数据——这里加倍输出预算
                # 完整重试一次，拿到未截断的结果。
                doubled = True
                effective = max(max_tokens, self.max_tokens_override) if self.max_tokens_override else max_tokens
                if effective >= TRUNCATION_RETRY_MAX_TOKENS:
                    break
                retry_tokens = min(effective * 2, TRUNCATION_RETRY_MAX_TOKENS)
                logger.warning(
                    "JSON 输出疑似因长度截断（finish_reason=length，len=%d），"
                    "max_tokens 加倍至 %d 重试一次",
                    len(content), retry_tokens,
                )
                content, finish_reason = await _sample(retry_tokens)
            elif not resampled:
                resampled = True
                logger.warning(
                    "chat_json: JSON 解析失败（finish_reason=%s，len=%d），重新采样重试一次",
                    finish_reason, len(content or ""),
                )
                content, finish_reason = await _sample(max_tokens)
            else:
                break
            raw = _parse_json_lenient(content)

        if raw is not None:
            if response_model is not None:
                return _validate_with_model(response_model, raw)
            return raw

        # 降噪（P-日志）：解析失败最终告警只打这一条 WARNING；
        # 旧实现每次中间失败都打 ERROR（成功恢复的请求也刷 ERROR 日志）
        # P2-2: 不再输出"前 120 字"正文 —— 响应正文含用户上传的论文内容，
        # 多用户部署写入 WARNING 日志有隐私合规风险；只留元信息（长度/finish_reason）
        logger.warning(
            "JSON 解析失败: finish_reason=%s（长度=%d）",
            finish_reason, len(content or ""),
        )
        raise ValueError("LLM 返回的不是有效 JSON（可能因输出被长度截断或含非法字符）")


# 全局单例（按当前生效配置缓存：网页端保存设置后指纹变化，自动重建）
_client: Optional[LLMClient] = None
_client_fingerprint: Optional[tuple] = None


def get_llm_client() -> LLMClient:
    """获取 LLM 客户端单例（配置指纹变化时自动重建）"""
    global _client, _client_fingerprint
    config = runtime_settings.effective_llm()
    fingerprint = config.fingerprint()
    if _client is None or fingerprint != _client_fingerprint:
        _client = LLMClient(config)
        _client_fingerprint = fingerprint
    return _client
