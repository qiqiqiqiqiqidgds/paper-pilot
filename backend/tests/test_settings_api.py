"""POST/GET/PUT /api/settings 与 RuntimeSettingsStore 的单元 + 接口测试。

覆盖：
- 脱敏回显（完整 Key 绝不出现在响应里）
- 字段级覆盖 / 整组 reset / settings.json 落盘
- get_llm_client() 按配置指纹自动重建
- 连接测试端点（mock LLMClient，验证表单值合并逻辑）
- 非法 base_url 422
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services import llm_client as llm_mod
from app.services.llm_client import get_llm_client
from app.services.runtime_settings import runtime_settings

API_KEY = "e2e-test-api-key-2026"  # conftest 注入的统一测试 key
HEADERS = {"X-API-Key": API_KEY}


@pytest.fixture(autouse=True)
def _isolated_runtime_settings():
    """每个测试前后：重置运行期设置单例 + 删除测试数据目录里的 settings.json。

    conftest 已把 DATA_DIR 指向进程级临时目录，这里的删除不会碰到真实数据。
    同时临时放宽限流（本文件请求量大），测试后恢复 conftest 注入的小值。
    """
    runtime_settings.reset()
    p = runtime_settings.path
    if p.exists():
        p.unlink()
    old_general, old_expensive = settings.rate_limit_general_per_min, settings.rate_limit_expensive_per_min
    settings.rate_limit_general_per_min = 10000
    settings.rate_limit_expensive_per_min = 10000
    yield
    settings.rate_limit_general_per_min = old_general
    settings.rate_limit_expensive_per_min = old_expensive
    runtime_settings.reset()
    if p.exists():
        p.unlink()


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


# ===== GET：脱敏回显 =====

def test_get_settings_default_masks_key(client):
    res = client.get("/api/settings", headers=HEADERS)
    assert res.status_code == 200
    body = res.json()
    assert body["code"] == 0
    llm = body["data"]["llm"]
    # conftest 注入 LLM_API_KEY=""，未配置时不应有任何掩码值
    assert llm["api_key_configured"] is False
    assert llm["api_key_masked"] is None
    assert llm["source"] == {"api_key": "env", "base_url": "env", "model": "env"}
    # conftest 注入 SEARCH_PROVIDER=tavily
    assert body["data"]["search"]["provider"] == "tavily"


def test_get_settings_never_returns_full_key(client):
    secret = "sk-webtest-1234567890abcdef"
    res = client.put(
        "/api/settings",
        json={"llm": {"api_key": secret, "base_url": "https://example.com/v1", "model": "test-model"}},
        headers=HEADERS,
    )
    assert res.status_code == 200
    res = client.get("/api/settings", headers=HEADERS)
    assert secret not in res.text, "完整 Key 不得出现在任何响应里"
    llm = res.json()["data"]["llm"]
    assert llm["api_key_configured"] is True
    assert llm["api_key_masked"] == "sk-***cdef"
    assert llm["base_url"] == "https://example.com/v1"
    assert llm["model"] == "test-model"
    assert llm["source"] == {"api_key": "web", "base_url": "web", "model": "web"}


# ===== PUT：字段级覆盖 + 落盘 =====

def test_put_settings_persists_to_disk(client):
    res = client.put(
        "/api/settings",
        json={"llm": {"api_key": "sk-disk-987654321", "model": "m-disk"}},
        headers=HEADERS,
    )
    assert res.status_code == 200
    path: Path = runtime_settings.path
    assert path.exists(), "覆盖值应落盘 settings.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["llm"]["api_key"] == "sk-disk-987654321"
    assert raw["llm"]["model"] == "m-disk"


def test_put_settings_partial_and_reset(client):
    # 先覆盖 model
    client.put("/api/settings", json={"llm": {"model": "web-model"}}, headers=HEADERS)
    view = runtime_settings.masked_view()
    assert view["llm"]["model"] == "web-model"
    assert view["llm"]["source"]["model"] == "web"
    # 再只覆盖 api_key：model 覆盖应保留（字段级合并）
    client.put("/api/settings", json={"llm": {"api_key": "sk-second-000111"}}, headers=HEADERS)
    view = runtime_settings.masked_view()
    assert view["llm"]["model"] == "web-model"
    assert view["llm"]["api_key_configured"] is True
    # 空串 = 清除该字段覆盖（回到 .env/默认）
    client.put("/api/settings", json={"llm": {"model": ""}}, headers=HEADERS)
    view = runtime_settings.masked_view()
    assert view["llm"]["source"]["model"] == "env"
    # reset_llm 整组清除
    client.put("/api/settings", json={"reset_llm": True}, headers=HEADERS)
    view = runtime_settings.masked_view()
    assert view["llm"]["source"] == {"api_key": "env", "base_url": "env", "model": "env"}


def test_put_settings_rejects_bad_base_url(client):
    res = client.put(
        "/api/settings",
        json={"llm": {"base_url": "ftp://not-http.example.com"}},
        headers=HEADERS,
    )
    assert res.status_code == 422


# ===== get_llm_client 按指纹重建 =====

def test_get_llm_client_rebuilds_on_config_change(client):
    before = get_llm_client()
    assert before.model != "web-model-x"
    client.put("/api/settings", json={"llm": {"model": "web-model-x", "api_key": "sk-rebuild-123456"}}, headers=HEADERS)
    after = get_llm_client()
    assert after is not before, "配置变化后应重建客户端"
    assert after.model == "web-model-x"
    assert after._api_key == "sk-rebuild-123456"
    # 未变化时复用
    assert get_llm_client() is after


def test_llm_client_direct_construction_with_config():
    """直接构造（连接测试路径）：传入 config 优先于全局设置"""
    from app.services.runtime_settings import LLMConnConfig

    cfg = LLMConnConfig(api_key="sk-direct", base_url="https://direct.example/v1", model="direct-m")
    c = llm_mod.LLMClient(cfg)
    assert c.model == "direct-m"
    assert c._api_key == "sk-direct"
    assert c._base_url == "https://direct.example/v1"


# ===== POST /test：表单值合并（mock 探测）=====

def test_test_connection_uses_form_values(client, monkeypatch):
    captured = {}

    class _FakeLLM:
        def __init__(self, config):
            captured["config"] = config

        async def test_connection(self):
            return {"ok": True, "message": "fake-ok"}

    monkeypatch.setattr(llm_mod, "LLMClient", _FakeLLM)
    res = client.post(
        "/api/settings/test",
        json={"llm": {"base_url": "https://form.example/v1", "model": "form-model"}},
        headers=HEADERS,
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["llm"] == {"ok": True, "message": "fake-ok"}
    cfg = captured["config"]
    assert cfg.base_url == "https://form.example/v1"
    assert cfg.model == "form-model"
    # 表单没填 key / 没保存过 key → 未配置
    assert cfg.api_key == ""


def test_test_connection_falls_back_to_saved_key(client, monkeypatch):
    captured = {}

    class _FakeLLM:
        def __init__(self, config):
            captured["config"] = config

        async def test_connection(self):
            return {"ok": True, "message": "fake-ok"}

    monkeypatch.setattr(llm_mod, "LLMClient", _FakeLLM)
    client.put("/api/settings", json={"llm": {"api_key": "sk-saved-abcdef"}}, headers=HEADERS)
    res = client.post(
        "/api/settings/test",
        json={"llm": {"model": "form-model"}},
        headers=HEADERS,
    )
    assert res.status_code == 200
    # 表单 key 留空 → 用已保存的 key
    assert captured["config"].api_key == "sk-saved-abcdef"
    assert captured["config"].model == "form-model"


def test_test_connection_empty_body_422(client):
    res = client.post("/api/settings/test", json={}, headers=HEADERS)
    assert res.status_code == 422


def test_test_connection_real_path_missing_key(client):
    """真实路径（不 mock）：key 未配置时返回 ok=False 而不是 500"""
    res = client.post("/api/settings/test", json={"llm": {}}, headers=HEADERS)
    assert res.status_code == 200
    assert res.json()["data"]["llm"]["ok"] is False


# ===== LLMClient.test_connection 异常兜底 =====

@pytest.mark.asyncio
async def test_llm_client_test_connection_swallows_errors(monkeypatch):
    from app.services.runtime_settings import LLMConnConfig

    async def _boom(**kwargs):
        raise llm_mod.APIConnectionError(request=None)  # type: ignore[arg-type]

    c = llm_mod.LLMClient(
        LLMConnConfig(api_key="sk-x", base_url="https://x.example/v1", model="m",
                      request_timeout_seconds=5.0)
    )
    monkeypatch.setattr(c.client.chat.completions, "create", _boom)
    result = await c.test_connection()
    assert result["ok"] is False
    assert "APIConnectionError" in result["message"]


# ===== Key 归属守卫（2026-09 审计修复：防 /api/settings 把已存 Key 外带到任意 base_url）=====

class TestKeyOwnershipGuard:
    """换 base_url 却不带新 Key 时，不允许沿用旧 Key。

    env 的 Key/base_url 视为一对；网页端覆盖 base_url 而不提供新 Key →
    生效 Key 置空（请求会因缺 Key 失败，而不是把旧 Key 发往新地址）。
    """

    def _save_env(self):
        return settings.llm_api_key, settings.llm_base_url

    def _restore_env(self, saved):
        settings.llm_api_key, settings.llm_base_url = saved

    def test_effective_llm_env_key_not_reused_for_new_base_url(self):
        saved = self._save_env()
        settings.llm_api_key = "env-secret-key"
        settings.llm_base_url = "https://api.deepseek.com"
        try:
            from app.services.runtime_settings import LLMOverrides

            runtime_settings.update(
                llm=LLMOverrides(base_url="https://evil.example/v1")
            )
            cfg = runtime_settings.effective_llm()
            assert cfg.base_url == "https://evil.example/v1"
            assert cfg.api_key == ""  # 旧 Key 不外带
        finally:
            self._restore_env(saved)

    def test_effective_llm_key_and_base_url_together_allowed(self):
        saved = self._save_env()
        settings.llm_api_key = "env-secret-key"
        settings.llm_base_url = "https://api.deepseek.com"
        try:
            from app.services.runtime_settings import LLMOverrides

            runtime_settings.update(
                llm=LLMOverrides(
                    api_key="new-key", base_url="https://new.example/v1"
                )
            )
            cfg = runtime_settings.effective_llm()
            assert cfg.base_url == "https://new.example/v1"
            assert cfg.api_key == "new-key"  # Key 与地址一起换：正常配对
        finally:
            self._restore_env(saved)

    def test_llm_config_with_form_changes_base_url_without_key(self):
        saved = self._save_env()
        settings.llm_api_key = "env-secret-key"
        settings.llm_base_url = "https://api.deepseek.com"
        try:
            from app.services.runtime_settings import LLMOverrides

            runtime_settings.update(
                llm=LLMOverrides(api_key="saved-key", base_url="https://saved.example/v1")
            )
            # 表单只换地址：不携带已存 Key 去测新地址
            cfg = runtime_settings.llm_config_with(
                LLMOverrides(base_url="https://evil.example/v1")
            )
            assert cfg.api_key == ""
            assert cfg.base_url == "https://evil.example/v1"
            # 空表单（沿用已保存配置）：Key 照常使用
            cfg2 = runtime_settings.llm_config_with(LLMOverrides())
            assert cfg2.api_key == "saved-key"
            assert cfg2.base_url == "https://saved.example/v1"
        finally:
            self._restore_env(saved)
