"""
运行期设置：网页端「设置」界面写入的 LLM / 搜索供应商配置。

与 config.py 的关系：
- config.py 的 Settings（.env）是启动期兜底默认值，进程内不可变；
- 本模块把网页端保存的覆盖值持久化到 data_dir/settings.json，
  字段级可选，未覆盖的字段继续沿用 .env / 默认值；
- effective_llm() / effective_search() 输出合并后的连接配置，
  llm_client / search_client 的工厂按配置指纹决定是否重建客户端。

安全：
- settings.json 含 API Key 明文，已被根 .gitignore 排除（backend/data/settings.json），
  严禁入库；对外（GET /api/settings）一律经 mask_secret() 脱敏回显，绝不返回完整 Key。
"""
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.config import settings
from app.utils.logger import logger


# ===== 覆盖值模型（PUT /api/settings 请求体，也是 settings.json 的存储结构）=====

class LLMOverrides(BaseModel):
    """LLM 覆盖项。None / 空串 = 不覆盖（沿用 .env/默认值）。"""
    model_config = ConfigDict(extra="forbid")

    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    max_tokens: Optional[int] = Field(default=None, ge=0, le=200_000)
    reasoning_split: Optional[bool] = None
    reasoning_effort: Optional[str] = None


class SearchOverrides(BaseModel):
    """搜索覆盖项。None / 空串 = 不覆盖。"""
    model_config = ConfigDict(extra="forbid")

    provider: Optional[Literal["arxiv", "tavily"]] = None
    tavily_api_key: Optional[str] = None
    tavily_base_url: Optional[str] = None


# ===== 合并后的连接配置（不可变值对象，fingerprint 供工厂判重建）=====

@dataclass(frozen=True)
class LLMConnConfig:
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    max_tokens: int = 0
    reasoning_split: bool = True
    reasoning_effort: str = ""
    request_timeout_seconds: float = 120.0

    def fingerprint(self) -> tuple:
        return (
            self.api_key, self.base_url, self.model, self.max_tokens,
            self.reasoning_split, self.reasoning_effort,
            self.request_timeout_seconds,
        )


@dataclass(frozen=True)
class SearchConnConfig:
    provider: str = "arxiv"
    tavily_api_key: str = ""
    tavily_base_url: str = "https://api.tavily.com"
    tavily_timeout_seconds: float = 60.0

    def fingerprint(self) -> tuple:
        return (self.provider, self.tavily_api_key, self.tavily_base_url)


def mask_secret(value: str) -> Optional[str]:
    """脱敏：保留头 3 + 尾 4 位，中间打码；空值返回 None"""
    if not value:
        return None
    if len(value) <= 8:
        return "***"
    return f"{value[:3]}***{value[-4:]}"


class RuntimeSettingsStore:
    """网页端覆盖值的内存态 + settings.json 持久化（进程内单例 runtime_settings）"""

    def __init__(self) -> None:
        self._llm = LLMOverrides()
        self._search = SearchOverrides()
        self._loaded = False
        self._lock = threading.Lock()

    # ----- 持久化 -----

    @property
    def path(self) -> Path:
        return Path(settings.data_dir) / "settings.json"

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                self._llm = LLMOverrides(**(raw.get("llm") or {}))
                self._search = SearchOverrides(**(raw.get("search") or {}))
            except FileNotFoundError:
                pass
            except Exception as e:
                # 损坏的 settings.json 不应阻断启动：忽略覆盖值，沿用 .env
                logger.warning("settings.json 解析失败（忽略网页端覆盖值）: %s", e)
            self._loaded = True

    def _persist_locked(self) -> None:
        """原子写（先写 .tmp 再 replace）。调用方必须已持有 self._lock"""
        payload = {
            "llm": self._llm.model_dump(),
            "search": self._search.model_dump(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(self.path)

    # ----- 读写接口 -----

    def update(
        self,
        llm: Optional[LLMOverrides] = None,
        search: Optional[SearchOverrides] = None,
        reset_llm: bool = False,
        reset_search: bool = False,
    ) -> None:
        """字段级合并覆盖值并落盘。reset_* 为 True 时整体清除该组覆盖（回到 .env）。

        :raises OSError: 磁盘写入失败（内存值仍已更新，下次成功的 update 会重写全量）
        """
        self._ensure_loaded()
        with self._lock:
            if reset_llm:
                self._llm = LLMOverrides()
            elif llm is not None:
                self._llm = self._merge(self._llm, llm)
            if reset_search:
                self._search = SearchOverrides()
            elif search is not None:
                self._search = self._merge(self._search, search)
            self._persist_locked()

    @staticmethod
    def _merge(current: BaseModel, incoming: BaseModel) -> BaseModel:
        """字段级合并：incoming 中非 None 的字段生效（空串视为「清除覆盖」）"""
        merged = current.model_dump()
        for key, value in incoming.model_dump().items():
            if value is not None:
                merged[key] = value
        return type(current)(**merged)

    # ----- 生效配置 -----

    def effective_llm(self) -> LLMConnConfig:
        self._ensure_loaded()
        o = self._llm
        api_key = (o.api_key or "").strip()
        base_url = (o.base_url or "").strip()
        # Key 归属校验（防 Key 外带）：env 的 Key 与 base_url 视为一对。
        # 网页端只换了 base_url 却没提供新 Key 时，不把 env Key 发往新地址
        # ——否则 PUT /api/settings 可被用来把真实 Key 持久化地重定向到
        # 任意 base_url。覆盖 Key 与覆盖 base_url 一起提供则视为新配对，正常使用。
        if not api_key and base_url and base_url != settings.llm_base_url:
            api_key = ""
        else:
            api_key = api_key or settings.llm_api_key
        return LLMConnConfig(
            api_key=api_key,
            base_url=base_url or settings.llm_base_url,
            model=(o.model or "").strip() or settings.llm_model,
            max_tokens=o.max_tokens if o.max_tokens is not None else settings.llm_max_tokens,
            reasoning_split=(
                o.reasoning_split if o.reasoning_split is not None
                else settings.llm_reasoning_split
            ),
            reasoning_effort=(
                (o.reasoning_effort or "").strip() or settings.llm_reasoning_effort
            ),
            request_timeout_seconds=settings.llm_request_timeout_seconds,
        )

    def effective_search(self) -> SearchConnConfig:
        self._ensure_loaded()
        o = self._search
        return SearchConnConfig(
            provider=o.provider or settings.search_provider,
            tavily_api_key=(o.tavily_api_key or "").strip() or settings.tavily_api_key,
            tavily_base_url=(o.tavily_base_url or "").strip() or settings.tavily_base_url,
            tavily_timeout_seconds=settings.tavily_timeout_seconds,
        )

    def llm_config_with(self, overrides: "LLMOverrides") -> LLMConnConfig:
        """当前生效配置 + 表单临时覆盖（供「测试连接」探测，不落盘不动单例）。

        表单里的空串/None 表示「沿用已保存的值」。
        例外（Key 归属校验）：表单换了 base_url 却没填新 Key 时，不把已保存
        的 Key 附上——否则 POST /api/settings/test 一条请求就能把真实 Key
        以 Bearer 形式发到任意指定地址。
        """
        base = self.effective_llm()
        api_key = (overrides.api_key or "").strip()
        base_url = (overrides.base_url or "").strip() or base.base_url
        if not api_key and base_url != base.base_url:
            api_key = ""  # 换地址测试但不带新 Key：不外带旧 Key
        else:
            api_key = api_key or base.api_key
        model = (overrides.model or "").strip() or base.model
        return LLMConnConfig(
            api_key=api_key,
            base_url=base_url,
            model=model,
            max_tokens=base.max_tokens,
            reasoning_split=base.reasoning_split,
            reasoning_effort=base.reasoning_effort,
            request_timeout_seconds=min(base.request_timeout_seconds, 30.0),
        )

    # ----- 脱敏视图 -----

    def masked_view(self) -> Dict[str, Any]:
        llm = self.effective_llm()
        search = self.effective_search()
        o_llm, o_search = self._llm, self._search
        return {
            "llm": {
                "base_url": llm.base_url,
                "model": llm.model,
                "api_key_configured": bool(llm.api_key),
                "api_key_masked": mask_secret(llm.api_key),
                "max_tokens": llm.max_tokens,
                "reasoning_split": llm.reasoning_split,
                "reasoning_effort": llm.reasoning_effort,
                "source": {
                    "api_key": "web" if o_llm.api_key else "env",
                    "base_url": "web" if o_llm.base_url else "env",
                    "model": "web" if o_llm.model else "env",
                },
            },
            "search": {
                "provider": search.provider,
                "tavily_base_url": search.tavily_base_url,
                "tavily_api_key_configured": bool(search.tavily_api_key),
                "tavily_api_key_masked": mask_secret(search.tavily_api_key),
                "source": {
                    "provider": "web" if o_search.provider else "env",
                    "tavily_api_key": "web" if o_search.tavily_api_key else "env",
                },
            },
        }

    def reset(self) -> None:
        """测试隔离用：丢弃内存覆盖值与加载标记（不删磁盘文件）"""
        with self._lock:
            self._llm = LLMOverrides()
            self._search = SearchOverrides()
            self._loaded = False


# 进程内单例
runtime_settings = RuntimeSettingsStore()
