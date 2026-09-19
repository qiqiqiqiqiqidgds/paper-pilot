"""
config.py 加固回归测试（对应 2026-09-01 配置审查修复）

覆盖：
1. env_file 锚定 backend 绝对路径（不再随启动目录漂移）
2. 相对 DATA_DIR 锚定到 backend/（同上）
3. DEEPSEEK_* 旧别名迁移（含 LLM_BASE_URL 留空的缺口用例）
4. base_url / model 空串兜底默认值
5. trusted_hosts / cors_origins 通配符拒绝（整字段、列表项、JSON 数组）
"""
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import (
    _BACKEND_DIR,
    _DEFAULT_LLM_BASE_URL,
    Settings,
)


class TestEnvFileAnchor:
    def test_env_file_anchored_to_backend_dir(self):
        env_file = Settings.model_config["env_file"]
        assert Path(env_file).is_absolute()
        assert Path(env_file) == _BACKEND_DIR / ".env"

    def test_env_example_exists(self):
        # 全新 clone 没有 .env（含密钥，不入库），但必须有 .env.example 模板；
        # 开发机上 .env 由用户从模板复制而来
        assert (_BACKEND_DIR / ".env.example").exists()


class TestDataDirAnchor:
    def test_relative_data_dir_anchored_to_backend(self):
        s = Settings(data_dir="./data")
        assert Path(s.data_dir).is_absolute()
        assert Path(s.data_dir) == (_BACKEND_DIR / "data").resolve()

    def test_absolute_data_dir_untouched(self):
        abs_dir = str(Path(__file__).resolve().parent)
        s = Settings(data_dir=abs_dir)
        assert Path(s.data_dir) == Path(abs_dir)


class TestDeepSeekAliasMigration:
    def test_empty_llm_base_url_migrates_from_old_alias(self):
        """修复点：LLM_BASE_URL 留空 + DEEPSEEK_BASE_URL 有值 → 应迁移"""
        s = Settings(llm_base_url="", deepseek_base_url="https://api.deepseek.com")
        assert s.llm_base_url == "https://api.deepseek.com"

    def test_default_llm_base_url_migrates_from_old_alias(self):
        s = Settings(
            llm_base_url=_DEFAULT_LLM_BASE_URL,
            deepseek_base_url="https://api.deepseek.com",
        )
        assert s.llm_base_url == "https://api.deepseek.com"

    def test_explicit_llm_base_url_not_overridden(self):
        s = Settings(
            llm_base_url="https://api.other.com/v1",
            deepseek_base_url="https://api.deepseek.com",
        )
        assert s.llm_base_url == "https://api.other.com/v1"

    def test_empty_base_url_falls_back_to_default(self):
        s = Settings(llm_base_url="")
        assert s.llm_base_url == _DEFAULT_LLM_BASE_URL

    def test_api_key_and_model_migrate(self):
        s = Settings(
            llm_api_key="",
            deepseek_api_key="sk-old",
            llm_model="",
            deepseek_model="deepseek-chat",
        )
        assert s.llm_api_key == "sk-old"
        assert s.llm_model == "deepseek-chat"

    def test_empty_model_falls_back_to_default(self):
        s = Settings(llm_model="")
        assert s.llm_model  # 非空


class TestWildcardRejection:
    @pytest.mark.parametrize("field", ["cors_origins", "trusted_hosts"])
    def test_whole_field_wildcard_rejected(self, field):
        with pytest.raises(ValidationError):
            Settings(**{field: "*"})

    @pytest.mark.parametrize("field", ["cors_origins", "trusted_hosts"])
    def test_item_wildcard_rejected(self, field):
        """修复点：'127.0.0.1,*' 这类列表项通配符此前可绕过校验"""
        with pytest.raises(ValidationError):
            Settings(**{field: "127.0.0.1,*"})

    def test_json_array_item_wildcard_rejected(self):
        with pytest.raises(ValidationError):
            Settings(cors_origins='["http://a.com","*"]')

    def test_normal_values_accepted(self):
        s = Settings(
            trusted_hosts="127.0.0.1,localhost",
            cors_origins="http://localhost:3000,http://127.0.0.1:3000",
        )
        assert s.trusted_hosts_list == ["127.0.0.1", "localhost"]
        assert "http://localhost:3000" in s.cors_origins_list
