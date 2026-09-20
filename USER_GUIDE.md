# PaperPilot 用户使用文档

> AI 论文/文献伴读 Agent · 用户手册

---

## 一、这是什么？

PaperPilot 是一款**论文伴读 AI 智能体**。上传任意英文/中文 **PDF 或 Word** 论文，AI 自动帮你：
- 📌 **拆解**：5 段结构化总结（摘要/背景/目标/方法/实验/结论）
- 💡 **创新**：识别核心创新点 + 评估创新等级
- 🔍 **对比**：联网搜相关工作 + 自动生成对比表 / 多篇库内对比
- ⚠️ **漏洞**：方法/实验/写作三层局限性 + 改进建议
- 📑 **PPT**：一键生成 8-15 页汇报 PPT

**核心特性**：
- 对开视图：左边 PDF 原文，右边 AI 分析，点击引用自动跳转到原文位置
- 多步 Agent：不只是聊天，会自动规划任务、调用工具、记忆状态
- 完全本地化：论文数据存你电脑上，隐私安全
- 移动端友好：手机/平板自动切换为抽屉式布局

---

## 二、30 秒快速上手

> 假设你已在项目根目录（`paper-pilot/`）下。

**macOS / Linux（bash）：**
```bash
# 1. 启动后端
cd backend
source venv/bin/activate   # 第一次运行：python3 -m venv venv && source venv/bin/activate
uvicorn app.main:app --reload

# 2. 启动前端（再开一个终端）
cd frontend
npm run dev

# 3. 浏览器打开
# http://localhost:3000
```

**Windows（PowerShell）：**
```powershell
# 1. 启动后端（新开一个 PowerShell）
cd backend
.\venv\Scripts\Activate.ps1
uvicorn app.main:app --reload

# 2. 启动前端（再开一个 PowerShell）
cd frontend
npm run dev

# 3. 浏览器打开
# http://localhost:3000
```

**懒人方案**：macOS / Linux 可直接跑 `bash start_dev.sh`（一键启动后端 + 前端，日志在 `backend.log` / `frontend.log`）。Windows 在 PowerShell 中跑：
```powershell
powershell -ExecutionPolicy Bypass -File .\start_dev.ps1
```
（脚本会开两个新 PowerShell 窗口分别跑后端 / 前端，关闭主窗口不影响。）

**桌面版（免环境）**：如果你拿到了 `PaperPilot Setup x.x.x.exe` 安装包（或按 [`README.md`](./README.md)「桌面版」一节自行打包），双击安装后从桌面图标启动即可——无需安装 Python / Node，后端已内嵌。启动后在「设置」里填 API Key 的流程与本节一致。

---

## 三、详细使用流程

### Step 1：上传论文

点击右上角「上传文件」按钮，拖拽文件到窗口（支持拖拽区域）。

- 支持格式：`.pdf`、`.docx`（Word）
- 大小限制：≤ 50MB
- 多文件：可以连续上传多个，自动加入论文库
- 上传期间按钮变灰、不可重复点击；进度条显示真实百分比

### Step 2：选择论文

在左侧「论文库」中点击任意论文，对开视图自动加载。

### Step 3：跑分析

右栏 5 个 Tab，每个都有「开始分析」按钮：

| Tab | 做什么 | 大概要多久 |
|-----|--------|-----------|
| 📌 拆解 | 五段结构化总结 | 10-15 秒 |
| 💡 创新 | 创新点 + 创新等级 | 8-12 秒 |
| 🔍 对比 | 联网搜相关工作 + 对比表 | 15-25 秒 |
| ⚠️ 漏洞 | 三层局限性 + 改进建议 | 10-15 秒 |
| 📑 PPT | 生成汇报 PPT | 10-30 秒 |

### Step 4：联动高亮

拆解/创新 Tab 的引用块都可点击。点「📍 点此跳转到 PDF」，左栏 PDF 自动跳到对应页并高亮文本。

### Step 5：多篇对比

文件库多选 2-5 篇论文（勾选框），点击「对比选中 (N)」。系统自动生成多论文对比表。

### Step 6：下载 PPT

「📑 PPT」Tab → 勾选要包含的内容 → 「生成 PPT」→ 「下载 .pptx」。下载的文件可用 PowerPoint/Keynote/WPS 打开。

---

## 四、API Key 配置

### 4.1 LLM 提供商（必须）

支持任意 OpenAI 兼容 API：MiniMax / DeepSeek / OpenAI / 自建网关（Ollama、vLLM 等）。

**方式一（推荐）：网页设置界面。** 启动应用后，点页面右上角「设置」图标，填写 base_url / API Key / 模型名，可先「测试连接」再保存，保存即生效。

**方式二：环境变量。** 编辑 `backend/.env`：
```
LLM_API_KEY=sk-你的密钥
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
```

> 提示：各平台的注册地址与 base_url 对照见 `backend/.env.example`。

### 4.2 Tavily（联网搜索可选）

默认使用 arXiv 搜索（免费、无需 Key）。若想改用 Tavily 通用网页搜索：

注册：https://tavily.com/，在网页设置界面或 `backend/.env` 中填入：
```
SEARCH_PROVIDER=tavily
TAVILY_API_KEY=tvly-你的密钥
```

> 提示：免费 1000 次/月。论文搜索一般 1 次对应 1 篇文章。

---

## 五、常见问题

### Q1: 报错 "LLM_API_KEY 未配置"

在网页「设置」界面填写 API Key 并保存，或在 `backend/.env` 里填 `LLM_API_KEY`。改 `.env` 后需**重启后端服务**，网页设置则即时生效。

### Q2: PDF 解析乱码/失败

- 确保 PDF 不是扫描版（图片型 PDF）
- 确保不是加密 PDF
- 尝试用其他 PDF 阅读器打开看看是否正常

### Q3: 联网搜不到结果

- 检查 `TAVILY_API_KEY` 是否配置
- 论文太新/太冷门可能搜不到，可以手动换关键词

### Q4: PPT 生成后页面太多/太少

W6 阶段是基础版，幻灯片数量根据内容自动调整。如需定制，编辑 `backend/app/services/ppt_generator.py`。

### Q5: 前端连不上后端

检查：
- 后端是否在 8000 端口运行（`http://localhost:8000/docs` 能打开说明后端 OK）
- 前端 `.env.local` 中 `NEXT_PUBLIC_API_BASE` 是否正确
- 浏览器控制台是否有 CORS 错误

### Q6: 怎么清空论文库？

进入 `backend/data/papers/` 目录，删除对应论文 ID 的文件夹。

### Q7: 桌面版（exe）的数据存在哪？

桌面版的论文库、上传文件、设置（含 API Key）和日志都在用户数据目录，卸载重装不丢失：

- Windows：`%APPDATA%\paperpilot-desktop\`（`data\` 为论文库与设置，`logs\` 为日志）
- 开发模式（Web 版）则在仓库的 `backend/data/` 下

### Q8: 桌面版首次运行提示"Windows 已保护你的电脑"？

安装包未做代码签名，SmartScreen 会弹一次警告：点「更多信息」→「仍要运行」即可。这是未签名开源软件的正常现象。

---

## 六、快捷键

| 快捷键 | 功能 |
|--------|------|
| `←` / `→` | 切换 PDF 上一页/下一页 |
| `1` / `2` / `3` / `4` / `5` | 切换右栏 5 个 Tab |
| 拖拽文件 | 上传 PDF |

> 提示：快捷键在 PDF 区域聚焦时生效。

---

## 七、技术架构

```
┌──────────────────────────────────────────┐
│  浏览器 (Next.js 14)                      │
│  - 对开视图布局                           │
│  - pdf.js 渲染 + 联动高亮                 │
│  - React + Tailwind + Zustand             │
└────────────┬─────────────────────────────┘
             │ HTTP / WebSocket
┌────────────┴─────────────────────────────┐
│  FastAPI 后端 (Python)                    │
│  - Map-Reduce 拆解（asyncio.gather）     │
│  - 章节识别 3 级 fallback                │
│  - 服务: PDF 解析 / LLM / 联网 / PPT    │
└────────────┬─────────────────────────────┘
             │
┌────────────┴─────────────────────────────┐
│  外部服务                                  │
│  - LLM API（OpenAI 兼容，可配置）          │
│  - arXiv / Tavily (联网搜索)              │
└──────────────────────────────────────────┘
```

---

## 八、参与贡献

这是个学生项目，欢迎提 Issue / PR：
- 后端：FastAPI + 手写 Map-Reduce pipeline
- 前端：Next.js 14 + TypeScript
- 提示词：`backend/app/agent/prompts/`

主要可改进方向：
- 支持更多 LLM（GPT-4、Claude、Qwen）
- 支持更多文件格式（Word、HTML）
- 加论文库语义搜索
- 浏览器插件版

---

## 九、License

MIT
