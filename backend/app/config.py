"""
应用配置：从环境变量加载
"""
import json
import os
from pathlib import Path
from typing import List, Literal

from pydantic import Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ 目录绝对路径（config.py 位于 backend/app/config.py）
# env_file 与相对 DATA_DIR 一律锚定到这里，与"启动时的工作目录"解耦：
# 修复前 env_file=".env" 按 cwd 解析，从项目根目录启动会静默丢掉整个 .env
_BACKEND_DIR = Path(__file__).resolve().parent.parent

_DEFAULT_LLM_BASE_URL = "https://api.minimaxi.com/v1"
_DEFAULT_LLM_MODEL = "MiniMax-M3"


class Settings(BaseSettings):
    """应用配置"""
    model_config = SettingsConfigDict(
        env_file=str(_BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ===== 环境 =====
    # dev / staging / prod；prod 下启动会强制要求 APP_API_KEY
    app_env: Literal["dev", "staging", "prod"] = Field(default="dev")

    # ===== LLM（OpenAI 兼容 chat.completions,支持 MiniMax/DeepSeek/OpenAI 等）=====
    # 新统一变量名:LLM_API_KEY / LLM_BASE_URL / LLM_MODEL
    # 旧变量名 DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL / DEEPSEEK_MODEL 仍可识别（兼容老 .env）,
    # 但新值优先（仅当新变量为空时才回退到旧变量）。
    llm_api_key: str = Field(default="", description="LLM API Key(新统一名,旧名 DEEPSEEK_API_KEY)")
    llm_base_url: str = Field(default=_DEFAULT_LLM_BASE_URL, description="LLM base_url(OpenAI 兼容)")
    llm_model: str = Field(default=_DEFAULT_LLM_MODEL, description="LLM 模型名")
    # 单次 chat 最大输出 tokens。留空则用代码默认(chat=4000, chat_json=4000)。
    # MiniMax-M3 等长上下文模型可调高（如 8000）以应对长论文 Map 阶段。
    llm_max_tokens: int = Field(default=0, description="单次 chat 最大输出 tokens(0=用代码默认)")
    # 是否在 chat 调用里通过 extra_body 传 reasoning_split。
    # ⚠️ MiniMax M3 实测该参数被静默忽略(content 仍含 <think> 标签),
    # 后端 chat_json() 用 _strip_think_tags 兜底剥离;本开关仅影响是否显式发请求。
    llm_reasoning_split: bool = Field(default=True, description="是否传 extra_body.reasoning_split")
    # 推理强度:none=关闭推理 / low / medium / high;留空则不传该参数。
    # ⚠️ OpenAI o1 专属参数;MiniMax/DeepSeek 都忽略;留空最稳。
    llm_reasoning_effort: str = Field(default="", description="LLM 推理强度(OAI o1 专属,MiniMax 忽略)")
    llm_timeout_seconds: float = Field(
        default=300.0,
        description="LLM 阶段整体超时（秒）;Map/Reduce/legacy 整篇分析共用,超时按失败处理",
    )
    # P3-5: breakdown Map 阶段的最大并发 LLM 调用数（此前硬编码 Semaphore(3)）。
    # 调小时更不容易撞 provider 的并发/Token Plan 限流,调大可加快多章节论文分析。
    llm_map_concurrency: int = Field(
        default=3,
        description="breakdown Map 阶段最大并发 LLM 调用数（正整数）",
    )
    llm_request_timeout_seconds: float = Field(
        default=120.0,
        description="单次 LLM HTTP 请求超时（秒）;SDK 层超时,与整体超时是两层",
    )

    # ===== 旧 DeepSeek 变量名（兼容老 .env;新 LLM_* 优先）=====
    # 这三个字段仅用于 _migrate_deepseek_aliases(),业务代码请读 llm_*
    deepseek_api_key: str = Field(default="", description="[旧名] DeepSeek API Key,被 LLM_API_KEY 取代")
    deepseek_base_url: str = Field(default="", description="[旧名] DeepSeek base_url")
    deepseek_model: str = Field(default="", description="[旧名] DeepSeek model")

    # ===== Tavily（可选搜索供应商）=====
    tavily_api_key: str = Field(default="")
    tavily_base_url: str = Field(default="https://api.tavily.com")
    tavily_timeout_seconds: float = Field(default=60.0, description="Tavily 高级搜索超时")

    # ===== 联网搜索供应商 =====
    # arxiv: 免费无需 key（默认，学术论文搜索，本项目默认方案）
    # tavily: 需 TAVILY_API_KEY（通用网页搜索）
    search_provider: Literal["arxiv", "tavily"] = Field(
        default="arxiv",
        description="联网搜索供应商：arxiv（免费无 key）/ tavily（需 key）",
    )

    # ===== App =====
    # 默认只监听回环（安全默认值）：0.0.0.0 会让局域网内任意设备访问本服务，
    # 在未配置 APP_API_KEY 的开发姿势下等于把 LLM Key / 论文库暴露出去。
    # 需要局域网访问时在 .env 显式设置 APP_HOST=0.0.0.0（并务必配好 APP_API_KEY）。
    app_host: str = Field(default="127.0.0.1")
    app_port: int = Field(default=8000)
    # 生产必须为 False（关闭 uvicorn --reload + 详细错误堆栈外泄）
    # 本地开发请在 .env 中显式设置 APP_DEBUG=true
    app_debug: bool = Field(default=False)

    # ===== 数据 =====
    data_dir: str = Field(default="./data")

    # ===== 日志 =====
    log_level: str = Field(default="INFO")

    # ===== CORS =====
    # 用 str 类型 + cors_origins_list property 解析（兼容 JSON 数组和逗号分隔字符串）
    # env 例子：
    #   逗号分隔（旧）：CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
    #   JSON 数组：    CORS_ORIGINS=["http://localhost:3000","http://127.0.0.1:3000"]
    cors_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        description="允许的跨域 origin 列表（逗号分隔或 JSON 数组）",
    )

    # ===== 反代可信主机（Uvicorn --forwarded-allow-ips）=====
    # ⚠️ 默认信任 127.0.0.1/localhost 是为单机反代场景；若反代暴露在公网且客户端可直连，
    # 攻击者可能伪造 X-Forwarded-For 绕过按 IP 限流。生产部署必须：① 把本项改成真实反代
    # IP（如 nginx/网关内网 IP）；② 反代层丢弃/覆写客户端传入的 X-Forwarded-For。
    trusted_hosts: str = Field(
        default="127.0.0.1,localhost",
        description="反代/负载均衡的 IP 或主机名（仅这些的 X-Forwarded-For 头会被信任）",
    )

    # ===== 鉴权 =====
    # 留空 = 不鉴权（仅本地开发）。部署前必须设置一个强随机串。
    app_api_key: str = Field(default="", description="API Key（X-API-Key），留空则不鉴权")

    # ===== 限流（按 IP，每分钟）=====
    rate_limit_general_per_min: int = Field(default=60, description="通用接口每分钟限流次数")
    rate_limit_expensive_per_min: int = Field(default=10, description="昂贵接口（分析/对比/PPT）每分钟限流次数")

    # ===== Worker =====
    # 用于启动时警告：>1 时内存限流会失效
    app_workers: int = Field(default=1, description="uvicorn worker 数；>1 时内存限流会按 worker 翻倍")

    # ===== 上传限制 =====
    max_upload_size_bytes: int = Field(default=50 * 1024 * 1024, description="上传文件最大字节")

    # ===== Validators =====
    @model_validator(mode="after")
    def _migrate_deepseek_aliases(self) -> "Settings":
        """
        向后兼容:把旧 DEEPSEEK_* 字段值迁移到新 LLM_* 字段（仅当 LLM_* 为空时）。

        背景:2026-08 重构 LLM 配置,统一改用 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL,
        但老 .env 里可能还有 DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL / DEEPSEEK_MODEL。
        本 validator 在 settings 实例化时把老值兜底到新值,避免破坏现有部署。
        """
        if not self.llm_api_key and self.deepseek_api_key:
            object.__setattr__(self, "llm_api_key", self.deepseek_api_key)
        # base_url：新值为空或仍为默认值时，回退旧 DEEPSEEK_BASE_URL（若有）。
        # 修复：旧逻辑漏了「LLM_BASE_URL 留空 + 旧值存在」的组合——空串不迁移，
        # 而 AsyncOpenAI(base_url="") 实测会让所有调用抛 APIConnectionError。
        if self.deepseek_base_url and self.llm_base_url in ("", _DEFAULT_LLM_BASE_URL):
            object.__setattr__(self, "llm_base_url", self.deepseek_base_url)
        # 空串兜底回默认值（LLM_BASE_URL= 留空视同未设置）
        if not self.llm_base_url:
            object.__setattr__(self, "llm_base_url", _DEFAULT_LLM_BASE_URL)
        if not self.llm_model and self.deepseek_model:
            object.__setattr__(self, "llm_model", self.deepseek_model)
        # model 空串同理兜底（空模型名只会得到 provider 报错）
        if not self.llm_model:
            object.__setattr__(self, "llm_model", _DEFAULT_LLM_MODEL)
        return self

    @model_validator(mode="after")
    def _guard_prod_bare(self) -> "Settings":
        """P1：prod 裸奔防线 —— 监听 0.0.0.0 且无 API Key 时直接拒绝启动"""
        if (
            self.app_env == "prod"
            and not self.auth_enabled
            and self.app_host == "0.0.0.0"
        ):
            raise ValueError(
                "APP_ENV=prod 且 APP_HOST=0.0.0.0 且 APP_API_KEY 未配置！"
                "生产环境必须启用 API Key 鉴权，且不建议监听 0.0.0.0（建议内网 IP / 127.0.0.1）。"
            )
        return self

    @model_validator(mode="after")
    def _anchor_relative_paths(self) -> "Settings":
        """相对 DATA_DIR 锚定到 backend/（与 env_file 同理，消除对 cwd 的依赖）"""
        if self.data_dir and not os.path.isabs(self.data_dir):
            object.__setattr__(
                self, "data_dir", str((_BACKEND_DIR / self.data_dir).resolve())
            )
        return self

    @field_validator("cors_origins", "trusted_hosts")
    @classmethod
    def _validate_no_wildcard(cls, v: str, info: ValidationInfo) -> str:
        """cors_origins / trusted_hosts 均不允许 '*'（整字段或列表中任意一项）"""
        if "*" in cls._parse_list_field(v):
            if info.field_name == "trusted_hosts":
                reason = (
                    "该字段按精确匹配使用，'*' 不会按通配符生效；"
                    "请显式列出真实反代 IP"
                )
            else:
                reason = "与 allow_credentials=True 冲突，请显式列出允许的 origin"
            raise ValueError(f"{info.field_name} 不允许包含 '*'（{reason}）")
        return v

    @staticmethod
    def _parse_list_field(v: str) -> List[str]:
        """解析 List 字段：支持 JSON 数组和逗号分隔字符串"""
        v = v.strip()
        if not v:
            return []
        if v.startswith("["):
            # JSON 数组
            try:
                arr = json.loads(v)
                if isinstance(arr, list):
                    return [str(o).strip() for o in arr if str(o).strip()]
            except json.JSONDecodeError:
                pass
        # 逗号分隔（默认）
        return [o.strip() for o in v.split(",") if o.strip()]

    @property
    def cors_origins_list(self) -> List[str]:
        result = self._parse_list_field(self.cors_origins)
        if "*" in result:
            raise ValueError("cors_origins 不允许 '*'（与 allow_credentials=True 冲突）")
        return result

    @property
    def trusted_hosts_list(self) -> List[str]:
        return self._parse_list_field(self.trusted_hosts)

    @property
    def papers_dir(self) -> str:
        return os.path.join(self.data_dir, "papers")

    @property
    def uploads_dir(self) -> str:
        return os.path.join(self.data_dir, "uploads")

    @property
    def auth_enabled(self) -> bool:
        """鉴权是否启用（API Key 非空即启用）"""
        return bool(self.app_api_key.strip())

    @property
    def is_production(self) -> bool:
        return self.app_env == "prod"


# 单例
settings = Settings()