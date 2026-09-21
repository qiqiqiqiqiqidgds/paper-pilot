# PaperPilot · AI 论文伴读智能体

> 让你 5 分钟读懂一篇论文，把 5 小时的活压到 5 分钟
> AI 智能体作品 · 8 周从 0 到 MVP

[![Status](https://img.shields.io/badge/status-MVP-green)]()
[![License](https://img.shields.io/badge/license-MIT-blue)](./LICENSE)

---

## ✨ 这是什么？

PaperPilot 是一款基于**手写 Map-Reduce pipeline + 大模型**的论文伴读工具，LLM 通过任意 **OpenAI 兼容 API** 接入（DeepSeek / MiniMax / OpenAI / 自建网关均可，**在网页设置界面里直接填写，无需改代码**）。上传任意 PDF 或 Word 论文，AI 自动：

- 📌 **五段拆解**：摘要 / 背景 / 目标 / 方法 / 实验 / 结论
- 💡 **创新点**：识别核心创新 + 评估创新等级
- 🔍 **对比**：联网搜相关工作 + 自动生成对比表
- ⚠️ **漏洞**：方法 / 实验 / 写作三层局限性 + 改进建议
- 📑 **PPT**：一键生成 8-15 页汇报 PPT

**核心特性**：
- 🪟 **对开视图**：左边 PDF 原文，右边 AI 分析，点击引用自动跳转并高亮
- 🧠 **Map-Reduce 拆解**：长论文自动按章节切分并发分析，再 Reduce 汇总成五段拆解，比一次性塞给 LLM 准得多
- ⚙️ **提供商可配**：网页右上角「设置」里填写 base_url / API Key / 模型名，即填即用，支持连接测试
- 🖥️ **桌面版**：Electron 一键打包成 Windows 安装包（内嵌后端，双击即用，无需装 Python / Node）
- 🔒 **本地化**：论文存你电脑上，API Key 只存本地，隐私安全
- 📱 **移动端**：< lg 自动切换为抽屉式布局

---

## 🚀 30 秒启动

> **路径说明**：以下命令假设你已在项目根目录（`paper-pilot/`）下。macOS / Linux 用 `cd backend` / `cd frontend`；Windows PowerShell 同理（也可直接用仓库根的 [`start_dev.sh`](./start_dev.sh) 跨平台启动）。
>
> **环境要求**：后端需要 **Python 3.11+**（分析接口使用了 `asyncio.timeout`，为 3.11+ API）；前端需要 **Node.js 20+**。

**macOS / Linux（bash）：**
```bash
# 1. 启动后端
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload

# 2. 启动前端（新开一个终端）
cd frontend
cp .env.local.example .env.local
npm install
npm run dev

# 3. 打开浏览器
# http://localhost:3000
```

**Windows（PowerShell）：**
```powershell
# 1. 启动后端
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload

# 2. 启动前端（新开一个 PowerShell）
cd frontend
copy .env.local.example .env.local
npm install
npm run dev
```

详细文档：[`USER_GUIDE.md`](./USER_GUIDE.md)

### 🖥️ 桌面版（Electron，可选）

不想装 Python / Node？可以把前后端打包成一个 Windows 安装包（约 120 MB，双击即用）：

```powershell
# 后端 PyInstaller onedir（约 20 秒）
cd backend
py -3.12 -m venv venv
.\venv\Scripts\pip install -r requirements.txt pyinstaller
.\venv\Scripts\pyinstaller paperpilot-backend.spec --noconfirm --clean

# 前端静态导出 + 组装 + 冒烟
cd ..\frontend
npm install
npm run build:desktop
cd ..\desktop
npm install
npm run assemble
npm run smoke      # 冒烟：健康检查 + 首页可达 → exit 0

# 产出安装包（NSIS）
npm run dist       # → desktop/release/PaperPilot Setup 1.0.0.exe
```

架构与完整说明见 [`desktop/README.md`](./desktop/README.md)：FastAPI 同源托管静态前端，数据落在 `%APPDATA%\paperpilot-desktop\`，LLM Key 仍在应用内「设置」里填。

---

## ⚙️ 配置 LLM 提供商（两种方式）

1. **网页设置界面（推荐）**：启动后在页面右上角点「设置」，填写 base_url / API Key / 模型名，可先「测试连接」再保存，保存即生效（无需重启）。
2. **环境变量（兜底默认值）**：编辑 `backend/.env` 填入 `LLM_API_KEY / LLM_BASE_URL / LLM_MODEL`（参考 [`backend/.env.example`](./backend/.env.example)）。任何 OpenAI 兼容端点都可以，例如：
   - MiniMax：`https://api.minimaxi.com/v1` + `MiniMax-M3`
   - DeepSeek：`https://api.deepseek.com` + `deepseek-chat`
   - OpenAI：`https://api.openai.com/v1` + `gpt-4o`
   - 本地 Ollama / vLLM 等自建网关同样适用

联网搜索默认使用免费无需 Key 的 arXiv API；想换 Tavily 也在设置里填（`TAVILY_API_KEY`，见 `.env.example` 搜索一节）。

---

## 🏗️ 项目结构

```
paper-pilot/
├── .github/workflows/          # CI（pytest + ruff + tsc + eslint + vitest + build）
├── docs/
│   ├── design-prototype.md     # 原型与交互设计
│   ├── tech-architecture.md    # 技术架构
│   ├── api-spec.md             # 接口文档
│   └── audit/                  # 历次审查 / 测试 / 修复报告
│
├── backend/                    # 后端 (Python + FastAPI)
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── api/                # 路由（upload / analyze / search / ppt / settings …）
│   │   ├── services/           # PDF / LLM / Search / PPT
│   │   ├── agent/prompts/      # 提示词
│   │   ├── models/             # Pydantic
│   │   └── utils/
│   ├── tests/
│   ├── requirements.txt
│   └── README.md
│
├── frontend/                   # 前端 (Next.js 14)
│   ├── src/
│   │   ├── app/
│   │   ├── components/         # 对开视图 / 设置对话框等组件
│   │   ├── lib/                # API 客户端
│   │   ├── stores/             # Zustand
│   │   └── types/
│   ├── package.json
│   └── README.md
│
├── desktop/                    # 桌面版（Electron 壳，见 desktop/README.md）
│   ├── src/main.js             # 主进程：spawn 后端 / 健康检查 / 进程管理
│   ├── scripts/assemble.mjs    # 组装后端 onedir + 前端静态产物
│   └── package.json            # electron-builder 配置（NSIS）
│
├── USER_GUIDE.md               # 用户使用文档
├── CONTRIBUTING.md             # 贡献指南
├── CODE_OF_CONDUCT.md          # 行为准则
├── SECURITY.md                 # 安全策略
├── CHANGELOG.md                # 更新日志
├── start_dev.sh / start_dev.ps1# 一键启动脚本
└── README.md                   # 本文件
```

---

## 🛠️ 技术栈

| 层 | 技术 |
|----|------|
| 前端 | Next.js 14 + TypeScript + Tailwind + shadcn/ui |
| 前端渲染 | pdf.js + react-pdf |
| 前端状态 | Zustand |
| 后端 | FastAPI + Python 3.11+ |
| Agent 编排 | 手写 Map-Reduce（asyncio.gather + Semaphore）|
| LLM | 任意 OpenAI 兼容 API（DeepSeek / MiniMax / OpenAI / 自建，网页端可配置）|
| 联网搜索 | arXiv API（默认免费）/ Tavily API |
| PDF 解析 | PyMuPDF |
| PPT 生成 | python-pptx |
| 数据存储 | 本地文件系统（论文库） |
| 桌面打包 | Electron + electron-builder + PyInstaller（Windows） |

---

## 📅 开发历程（8 周）

| 周 | 内容 | 状态 |
|----|------|------|
| W1 | 原型设计 + 技术架构 + 接口文档 | ✅ |
| W2 | 后端核心（PDF 解析 + LLM + 五段拆解） | ✅ |
| W3 | 前端对开视图 + PDF 渲染 + AI 面板 | ✅ |
| W4 | 联网搜索 + 相关工作对比 | ✅ |
| W5 | 多篇上传论文对比 | ✅ |
| W6 | 一键 PPT 生成（python-pptx） | ✅ |
| W7 | 联动高亮 + 用户文档 | ✅ |
| W8 | 商业化探索 + 收尾 | ✅ |
| 开源化 | 代码审查修复 + 文档体系 + CI + 桌面版（Electron 打包） | ✅ |

---

## 🎯 适用场景

- 📚 **学生**：课程论文、毕业设计、文献综述
- 🎓 **研究生**：开题、组会、发论文
- 🔬 **科研人员**：跟踪前沿、做综述、写基金本子
- 📊 **教师**：快速 review 论文、做汇报材料

---

## 🔒 代码质量

最近完成了一轮全量代码审查与修复（2026-07-29），包括：

- ✅ **8 个 P0 Critical**：路径穿越 / API Key 泄露 / 竞态覆盖 / 上传双触发 / PPT 字段校验 / PDF Worker CDN 依赖等
- ✅ **11 个 P1 High**：全局异常 / Magic Number 校验 / Tavily 重试 / LLM 日志脱敏 / XFF 反代白名单 / prod 必填 APP_API_KEY 等
- ✅ **14 个 P2/P3**：移动端响应式 / a11y 完整化 / 派生状态 useMemo / PPT 进度反馈 / Flaws 跳转 PDF / CI workflow 等

详见 [`CHANGELOG.md`](./CHANGELOG.md) 与 [`docs/audit/`](./docs/audit/)。

### 测试

```bash
# 后端（含 SSE 流式 / 搜索重试 / PPT 页数下限）
cd backend && python -m pytest tests/ -v --cov=app

# 前端（vitest 单元测试 + 类型检查）
cd frontend && npm test
cd frontend && npx tsc --noEmit -p tsconfig.json
```

CI 在 `.github/workflows/ci.yml`（pytest + ruff + tsc + eslint + vitest + build）。

> macOS 上如 pip 安装依赖失败（Python 3.14 无预编译 wheel），可用 `backend/requirements-mac.txt`（版本放宽版，`start_dev.sh` 在 Darwin 下会自动选用）。

---

## 🤝 参与贡献

欢迎提 Issue / PR，流程见 [`CONTRIBUTING.md`](./CONTRIBUTING.md)，社区行为规范见 [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md)。

主要可改进方向：
- 支持更多 LLM 内置预设与模型能力探测
- 支持更多文件格式（Word、HTML、Markdown）
- 论文库语义搜索
- 浏览器插件版
- 论文笔记导出（Notion / Obsidian）
- 多人协作 + 评论

---

## 📜 License

MIT
