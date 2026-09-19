"""
鉴权 + 限流中间件测试

不依赖 LLM / 业务路由，只测中间件本身。用最小 FastAPI app 跑 TestClient。

用法：
    cd backend
    pytest tests/test_auth_ratelimit.py -v
    # 或
    python -m tests.test_auth_ratelimit
"""
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# pytest 模式下 env 由 conftest.py 统一注入（先于本模块 import 生效，见 conftest.py），
# 这里仅兜底脚本模式（python -m tests.test_auth_ratelimit，不经过 conftest）。
# setdefault 不会覆盖 conftest 已注入的值。
os.environ.setdefault("APP_API_KEY", "e2e-test-api-key-2026")
os.environ.setdefault("RATE_LIMIT_GENERAL_PER_MIN", "5")   # 测试用小值
os.environ.setdefault("RATE_LIMIT_EXPENSIVE_PER_MIN", "3")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.config import settings
from app.utils.auth import APIKeyAuthMiddleware
from app.utils.ratelimit import RateLimitMiddleware

# pytest 模式下的"钉回限流值"fixture；pytest 可能没装在脚本模式环境里，故 try 导入
try:
    import pytest
except ImportError:
    pytest = None

if pytest is not None:
    @pytest.fixture(autouse=True)
    def _pin_rate_limits():
        """每个测试前把 settings 钉回限流小值（5/3）。

        限流中间件每次请求实时读 settings（见 app/utils/ratelimit.py:128-132），
        改属性即生效。e2e 测试（test_e2e.py 的 setUpClass）会把全局 settings 调高
        到 10000 以撑住生命周期请求量；本模块的 429 断言依赖 5/3，必须在自己的
        测试前钉回，否则 "e2e 先跑、本模块后跑" 的收集顺序下断言会挂。
        脚本模式（不经过 pytest）下进程是全新的，模块顶部 setdefault 已注入 5/3，
        无需此 fixture。
        """
        old_general = settings.rate_limit_general_per_min
        old_expensive = settings.rate_limit_expensive_per_min
        settings.rate_limit_general_per_min = 5
        settings.rate_limit_expensive_per_min = 3
        yield
        settings.rate_limit_general_per_min = old_general
        settings.rate_limit_expensive_per_min = old_expensive


# 构造最小测试 app（不依赖业务路由）
test_app = FastAPI()

@test_app.get("/")
async def root():
    return {"name": "test"}

@test_app.get("/api/health")
async def health():
    return {"code": 0, "data": {"status": "ok"}}

@test_app.get("/api/papers")
async def papers():
    return {"code": 0, "data": []}

@test_app.post("/api/analyze")
async def analyze():
    return {"code": 0, "data": {"type": "breakdown"}}

@test_app.post("/api/compare")
async def compare():
    return {"code": 0, "data": {}}

@test_app.post("/api/generate-ppt")
async def ppt():
    return {"code": 0, "data": {}}

# 挂中间件：顺序与生产一致
test_app.add_middleware(RateLimitMiddleware)   # 内层
test_app.add_middleware(APIKeyAuthMiddleware)  # 外层


def _make_client():
    """重置限流桶 + 构造新 client"""
    RateLimitMiddleware._buckets.clear()
    return TestClient(test_app)


def test_config_loaded():
    """确认 env var 真的注入了"""
    assert settings.app_api_key == "e2e-test-api-key-2026"
    assert settings.auth_enabled is True
    assert settings.rate_limit_general_per_min == 5
    assert settings.rate_limit_expensive_per_min == 3
    print("✅ 配置加载: api_key=***, general=5/min, expensive=3/min")


def test_health_is_public():
    """/api/health 不需要鉴权"""
    client = _make_client()
    res = client.get("/api/health")
    assert res.status_code == 200, f"健康检查应可访问，实际 {res.status_code}"
    body = res.json()
    assert body["code"] == 0
    print("✅ /api/health 公开访问（无 key → 200）")


def test_root_is_public():
    """/ 也公开"""
    client = _make_client()
    res = client.get("/")
    assert res.status_code == 200
    print("✅ / 公开访问")


def test_missing_api_key_returns_401():
    """没带 X-API-Key 应返回 401"""
    client = _make_client()
    res = client.get("/api/papers")
    assert res.status_code == 401, f"无 key 应被拒，实际 {res.status_code}"
    body = res.json()
    assert body["code"] == 401
    assert "API Key" in body["message"]
    print(f"✅ 无 X-API-Key → 401，message: {body['message']}")


def test_wrong_api_key_returns_401():
    """错误 key 应返回 401"""
    client = _make_client()
    res = client.get("/api/papers", headers={"X-API-Key": "wrong-key"})
    assert res.status_code == 401, f"错 key 应被拒，实际 {res.status_code}"
    print("✅ 错误 X-API-Key → 401")


def test_correct_api_key_passes_auth():
    """正确 key 通过鉴权（限流未到也通过）"""
    client = _make_client()
    res = client.get("/api/papers", headers={"X-API-Key": "e2e-test-api-key-2026"})
    assert res.status_code != 401, f"正确 key 不应被鉴权拒，实际 {res.status_code}"
    assert res.status_code != 429, f"不应被限流（首次），实际 {res.status_code}"
    print(f"✅ 正确 X-API-Key → {res.status_code}")


def test_non_ascii_api_key_no_type_error():
    """B8 回归：非 ASCII key 比较不应抛 TypeError（两侧编码 utf-8 后比较）

    HTTP header 实际按字节传输，starlette 以 latin-1 解码 —— 客户端发送 UTF-8
    字节的中文 key 时，服务端拿到的是非 ASCII str；旧实现 compare_digest
    对非 ASCII str 直接抛 TypeError → 500。修复后应正常走 401/200。
    """
    raw_key = "密钥-key".encode("utf-8")   # 客户端实际发送的字节
    wire_key = raw_key.decode("latin-1")   # starlette 解码后的服务端视角 str（非 ASCII）
    old_key = settings.app_api_key
    try:
        # 1) expected 为 ASCII、请求 key 为非 ASCII → 401（旧实现这里 500）
        settings.app_api_key = "e2e-test-api-key-2026"
        client = _make_client()
        res = client.get("/api/papers", headers={"X-API-Key": raw_key})
        assert res.status_code == 401, f"非 ASCII 错 key 应 401，实际 {res.status_code}"

        # 2) 两侧一致（同为非 ASCII）→ 通过鉴权
        settings.app_api_key = wire_key
        client = _make_client()
        res = client.get("/api/papers", headers={"X-API-Key": raw_key})
        assert res.status_code == 200, f"非 ASCII 正确 key 应通过，实际 {res.status_code}"
        print("✅ 非 ASCII X-API-Key 比较无 TypeError（一致→200，不一致→401）")
    finally:
        settings.app_api_key = old_key


def test_general_rate_limit():
    """通用接口触发限流（5/min 配置）"""
    client = _make_client()
    headers = {"X-API-Key": "e2e-test-api-key-2026"}

    # 5 次应全过
    for i in range(5):
        res = client.get("/api/papers", headers=headers)
        assert res.status_code != 429, f"第 {i+1} 次不应被限流，实际 {res.status_code}"
        assert res.status_code != 401, f"第 {i+1} 次鉴权应通过"

    # 第 6 次应被限流
    res = client.get("/api/papers", headers=headers)
    assert res.status_code == 429, f"第 6 次应被限流，实际 {res.status_code}"
    body = res.json()
    assert body["code"] == 429
    assert "general" in body["message"]
    assert "Retry-After" in res.headers
    retry_after = int(res.headers["Retry-After"])
    # 1 < retry_after <= 61（实现加了 +1 余量）
    assert 1 <= retry_after <= 65, f"Retry-After={retry_after} 异常"
    print(f"✅ 通用接口 6 次触发限流，Retry-After: {retry_after}s")


def test_expensive_rate_limit():
    """昂贵接口触发限流（3/min 配置）"""
    client = _make_client()
    headers = {"X-API-Key": "e2e-test-api-key-2026"}

    # 3 次应全过
    for i in range(3):
        res = client.post("/api/analyze", headers=headers)
        assert res.status_code != 429, f"第 {i+1} 次不应被限流，实际 {res.status_code}"
        assert res.status_code != 401, f"第 {i+1} 次鉴权应通过"

    # 第 4 次应被限流
    res = client.post("/api/analyze", headers=headers)
    assert res.status_code == 429, f"第 4 次应被限流，实际 {res.status_code}"
    body = res.json()
    assert "expensive" in body["message"]
    print("✅ 昂贵接口 4 次触发限流（/api/analyze）")


def test_separate_buckets():
    """通用和昂贵的桶互不影响"""
    client = _make_client()
    headers = {"X-API-Key": "e2e-test-api-key-2026"}

    # 用满通用接口
    for _ in range(5):
        client.get("/api/papers", headers=headers)

    # 通用被限流
    res = client.get("/api/papers", headers=headers)
    assert res.status_code == 429

    # 昂贵接口仍可用
    res = client.post("/api/analyze", headers=headers)
    assert res.status_code != 429, f"昂贵接口不应受通用限流影响，实际 {res.status_code}"
    print("✅ 通用和昂贵接口限流桶独立（互不影响）")


def test_health_not_rate_limited():
    """/api/health 不参与限流"""
    client = _make_client()
    headers = {"X-API-Key": "e2e-test-api-key-2026"}

    # 连刷 20 次
    for i in range(20):
        res = client.get("/api/health", headers=headers)
        assert res.status_code == 200, f"健康检查第 {i+1} 次失败: {res.status_code}"
    print("✅ /api/health 不参与限流（20 次全过）")


def test_invalid_key_does_not_consume_quota():
    """错 key 的请求不消耗限流配额"""
    client = _make_client()
    good_headers = {"X-API-Key": "e2e-test-api-key-2026"}
    bad_headers = {"X-API-Key": "wrong-key"}

    # 刷 10 次错 key（应该全 401，不消耗通用桶）
    for _ in range(10):
        res = client.get("/api/papers", headers=bad_headers)
        assert res.status_code == 401

    # 正确 key 仍有 5 次机会
    for i in range(5):
        res = client.get("/api/papers", headers=good_headers)
        assert res.status_code != 429, f"第 {i+1} 次正确 key 不应被限流"

    print("✅ 错 key 请求不消耗限流配额（鉴权先于限流生效）")


def main():
    """手动运行入口"""
    print("\n" + "=" * 60)
    print("🧪 鉴权 + 限流中间件测试")
    print("=" * 60 + "\n")

    tests = [
        test_config_loaded,
        test_health_is_public,
        test_root_is_public,
        test_missing_api_key_returns_401,
        test_wrong_api_key_returns_401,
        test_correct_api_key_passes_auth,
        test_general_rate_limit,
        test_expensive_rate_limit,
        test_separate_buckets,
        test_health_not_rate_limited,
        test_invalid_key_does_not_consume_quota,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"❌ {t.__name__} 失败: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {t.__name__} 异常: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"📊 结果: {passed} 通过 / {failed} 失败 / 共 {passed+failed}")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
