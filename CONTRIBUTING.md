# 贡献指南

感谢关注 PaperPilot！欢迎通过 Issue / Pull Request 参与贡献。

## 开发环境搭建

```bash
# 后端：Python 3.11+（运行依赖 + 开发/测试依赖）
cd backend
python -m venv venv
source venv/bin/activate        # Windows: .\venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env            # 按需填写 LLM_API_KEY（也可启动后在网页设置界面填写）
uvicorn app.main:app --reload

# 前端：Node.js 20+
cd frontend
npm install
cp .env.local.example .env.local
npm run dev                     # http://localhost:3000
```

也可以直接用仓库根目录的 `start_dev.sh` / `start_dev.ps1` 一键启动。

## 提交前请跑测试

```bash
# 后端（pytest + ruff）
cd backend && python -m pytest tests/ -v
ruff check app tests

# 前端（vitest + tsc + eslint + build）
cd frontend && npm test
npx tsc --noEmit -p tsconfig.json
npx eslint src
npm run build
```

CI（`.github/workflows/ci.yml`）会在 push / PR 时执行以上全部检查，请确保本地通过后再提交。

## PR 约定

- 一个 PR 聚焦一件事；较大的功能请先开 Issue 讨论。
- 新功能请附带测试；修 bug 请先写一个能复现的失败测试。
- 提交信息用中文或英文均可，但请说清楚「改了什么、为什么」。
- 涉及界面改动请附截图；涉及 API 改动请同步更新 `docs/api-spec.md`。

## 安全相关

请不要在 Issue / PR / 代码中提交任何真实 API Key 或个人隐私信息。发现问题请参阅 [SECURITY.md](./SECURITY.md)。
