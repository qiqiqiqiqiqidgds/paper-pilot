"""
E2E 鉴权 + 限流 + 基础路径（Sprint 4 / R2 拆分）
- test_01 ~ test_07：根路径、健康检查、鉴权、限流
"""
from app.config import settings
from test_e2e import (
    E2ETestBase, HEADERS, create_sample_pdf, upload_via_client,
    MOCK_INNOVATION,
)


class TestAuth(E2ETestBase):
    """鉴权 + 限流 + 基础路径测试"""

    def test_01_root_endpoint(self):
        """GET / - 根路径（公开）"""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200, f"根路径应 200，实际 {res.status_code}: {res.text}")
        body = res.json()
        self.assertIn("name", body)
        self.assertEqual(body["name"], "PaperPilot API")
        self.assertIn("version", body)
        print(f"✅ GET / → 200, name={body['name']}, v={body['version']}")

    def test_02_health_no_auth(self):
        """GET /api/health - 公开，无需 API Key"""
        res = self.client.get("/api/health")
        self.assertEqual(res.status_code, 200, f"健康检查应 200，实际 {res.status_code}")
        body = res.json()
        self.assertEqual(body["code"], 0)
        self.assertIn("data", body)
        self.assertEqual(body["data"]["status"], "ok")
        # 显式置空 key 后应为 missing_key
        self.assertEqual(body["data"]["llm"], "missing_key")
        self.assertEqual(body["data"]["tavily"], "missing_key")
        print(f"✅ GET /api/health (无 key) → 200, llm={body['data']['llm']}, tavily={body['data']['tavily']}")

    def test_03_health_with_auth(self):
        """GET /api/health - 带 key 也应 200（公开）"""
        res = self.client.get("/api/health", headers=HEADERS)
        self.assertEqual(res.status_code, 200)
        print("✅ GET /api/health (带 key) → 200")

    def test_04_auth_missing_key(self):
        """GET /api/papers 不带 X-API-Key → 401"""
        res = self.client.get("/api/papers")
        self.assertEqual(res.status_code, 401, f"无 key 应 401，实际 {res.status_code}")
        body = res.json()
        self.assertEqual(body["code"], 401)
        self.assertIn("API Key", body["message"])
        print(f"✅ 无 X-API-Key → 401, msg: {body['message'][:50]}")

    def test_05_auth_wrong_key(self):
        """带错误 X-API-Key → 401"""
        res = self.client.get("/api/papers", headers={"X-API-Key": "wrong-key-xxx"})
        self.assertEqual(res.status_code, 401, f"错 key 应 401，实际 {res.status_code}")
        body = res.json()
        self.assertEqual(body["code"], 401)
        print("✅ 错误 X-API-Key → 401")

    def test_06_auth_correct_key(self):
        """带正确 X-API-Key → 200"""
        res = self.client.get("/api/papers", headers=HEADERS)
        self.assertEqual(res.status_code, 200, f"正确 key 应 200，实际 {res.status_code}: {res.text}")
        body = res.json()
        self.assertEqual(body["code"], 0)
        self.assertIn("data", body)
        self.assertEqual(body["data"]["total"], 0)
        print("✅ 正确 X-API-Key → 200, papers=0 (空库)")

    def test_07_rate_limit_429(self):
        """触发 429 响应（昂贵接口限流）"""
        # test_e2e.py 为 e2e 生命周期把全局限流调高到 10000，这里临时调小以触发 429。
        # 限流中间件每次请求实时读 settings（见 app/utils/ratelimit.py:128-132），改属性即生效。
        old_expensive = settings.rate_limit_expensive_per_min
        # B17: /api/upload 现在也计入 expensive 桶（占 1 个名额），limit 相应调到 4
        settings.rate_limit_expensive_per_min = 4
        try:
            # 先上传一个文件（B17 起归入 expensive 桶，占用 1 个限额）
            pdf_bytes = create_sample_pdf()
            upload_res = upload_via_client(self.client, pdf_bytes, "rl_test.pdf")
            self.assertEqual(upload_res.status_code, 200, f"上传失败: {upload_res.text}")
            paper_id = upload_res.json()["data"]["paper_id"]

            with self.mocks.patch_llm(MOCK_INNOVATION):
                # 前 3 次应都通过（临时 limit=4，上传已占 1 个）
                for i in range(3):
                    res = self.client.post(
                        "/api/analyze",
                        json={"paper_id": paper_id, "type": "innovation"},
                        headers=HEADERS,
                    )
                    self.assertNotEqual(
                        res.status_code, 429,
                        f"第 {i+1} 次不应被限流，实际 {res.status_code}: {res.text}"
                    )
                    self.assertNotEqual(res.status_code, 401, f"第 {i+1} 次鉴权应通过")

                # 第 4 次 analyze 应触发 429
                res = self.client.post(
                    "/api/analyze",
                    json={"paper_id": paper_id, "type": "innovation"},
                    headers=HEADERS,
                )
                self.assertEqual(res.status_code, 429, f"第 4 次应 429，实际 {res.status_code}: {res.text}")
                body = res.json()
                self.assertEqual(body["code"], 429)
                self.assertIn("expensive", body["message"])
                self.assertIn("Retry-After", res.headers)
                retry = int(res.headers["Retry-After"])
                self.assertGreaterEqual(retry, 1)
                self.assertLessEqual(retry, 65, f"Retry-After={retry} 异常")
                print(f"✅ 昂贵接口 4 次触发 429, Retry-After={retry}s")
        finally:
            settings.rate_limit_expensive_per_min = old_expensive
