# PaperPilot Backend

AI 论文/文献伴读 Agent 的后端服务（FastAPI）。

## ⚠️ 生产环境警告

**当前为 MVP 部署，仅适合个人/小团队使用**。上线前必须补齐：

1. ✅ **认证授权** — API Key + `X-API-Key` header，启动时设 `APP_API_KEY` 即可启用
2. ✅ **速率限制** — 按 IP，通用 60/min + 昂贵接口 10/min，可通过环境变量调
3. ✅ **路径穿越防护** — paper_id 正则白名单 + `resolve()` 二次防线
4. ✅ **Magic Number 校验** — 拒绝扩展名伪装（HTML/EXE 不能伪装 PDF/DOCX）
5. ✅ **全局异常处理** — 统一响应格式 + 错误脱敏（dev 返回详细，生产返回通用消息）
6. ✅ **Tavily 重试 + 连接池** — 指数退避（429/5xx/Timeout 自动重试 3 次）
7. ✅ **日志脱敏** — 不记录 LLM 完整响应，只记录长度 + 摘要
8. ✅ **prod 启动强校验** — `APP_ENV=prod` 但未配 `APP_API_KEY` 直接 fail
9. ✅ **孤儿文件清理** — 启动 + 每 6 小时后台清理过期/孤儿 PPT
10. **HTTPS** — 当前是 HTTP，生产必须上 TLS
11. **对象存储** — 当前用本地文件系统，建议改用 S3/OSS
12. **数据库** — 论文元数据在文件系统，建议改 SQLite/PostgreSQL
13. **多 worker 部署** — 内存限流为进程内字典，多 worker 翻倍；建议反代层限流

> 单 worker 部署（`uvicorn --workers 1`）行为正确。

### 启用鉴权（部署前必做）

```bash
# 生成一个强随机 key
APP_API_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
```

`.env` 里设置 `APP_API_KEY=<key>` 即启用。生产环境（`APP_ENV=prod`）下**不设置会启动失败**。

前端需在 `frontend/.env.local` 同步设置 `BACKEND_API_KEY=<同一个 key>`（由 BFF 代理服务端附加）。

不设置 `APP_API_KEY` = 不鉴权（仅本地 dev 环境）。

### 调整限流阈值

```bash
RATE_LIMIT_GENERAL_PER_MIN=60      # 通用接口
RATE_LIMIT_EXPENSIVE_PER_MIN=10    # 分析/对比/PPT
APP_WORKERS=1                      # 必须 ≤1 否则限流翻倍
```

### 反代白名单（X-Forwarded-For）

仅来自 `TRUSTED_HOSTS` 的反代 XFF 头会被信任（防 IP 伪造）：

```bash
# JSON 数组格式
TRUSTED_HOSTS=["10.0.0.1","nginx.example.com"]
# 或逗号分隔（旧格式，向后兼容）
TRUSTED_HOSTS=10.0.0.1,nginx.example.com
```

## 技术栈

- **Web 框架**：FastAPI（requirements.txt 锁定版本）
- **PDF 解析**：PyMuPDF（pymupdf）
- **DOCX 解析**：python-docx
- **LLM**：任意 OpenAI 兼容 API（MiniMax / DeepSeek / OpenAI / 自建网关，网页设置界面可配置）
- **联网搜索**：默认 **arXiv**（免费无需 key）+ 可选 Tavily（httpx + 指数退避 + 连接池复用）
- **PPT 生成**：python-pptx
- **数据校验**：Pydantic v2
- **异步**：asyncio

## 快速开始

### 1. 安装依赖

> **环境要求**：需要 **Python 3.11+**（分析接口使用了 `asyncio.timeout`，为 3.11+ API）。

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 可选：编辑 .env 填入 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL（也可启动后在网页设置界面填写）
```

> 🔑 **LLM API Key**：支持任意 OpenAI 兼容平台（MiniMax / DeepSeek / OpenAI 等），注册地址与 base_url 对照见 `.env.example`
>
> 🔑 **联网搜索**：默认走 arXiv（免费无需 key）；若改用 Tavily 需在 https://tavily.com/ 注册并把 `SEARCH_PROVIDER=tavily`

### 3. 启动服务

```bash
# 开发模式（自动重载）
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 生产模式（单 worker）
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

服务启动后访问：
- API 文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/api/health

### 4. 测试

```bash
# 端到端文件读取（PDF + DOCX）
python -m tests.test_file_reading_e2e
python -m tests.test_docx_reading_e2e

# 鉴权 + 限流中间件
python -m pytest tests/test_auth_ratelimit.py -v

# 完整 pytest 套件
python -m pytest tests/ -v
```

## 目录结构

```
backend/
├── app/
│   ├── main.py                # FastAPI 入口（lifespan + 中间件 + 路由 lazy 加载）
│   ├── config.py              # 配置加载（pydantic-settings + validators）
│   │
│   ├── api/                   # 路由（FastAPI Router）
│   │   ├── health.py          # 健康检查
│   │   ├── upload.py          # 上传 PDF/DOCX（流式大小限制 + Magic Number）
│   │   ├── analyze.py         # 单篇分析（同步 + SSE 流式版）
│   │   ├── compare_papers.py  # 多篇库内对比
│   │   ├── search.py          # 联网搜 + 单论文对比
│   │   └── ppt.py             # 生成 PPT + 下载
│   │
│   ├── services/              # 业务服务
│   │   ├── pdf_parser.py      # PDF 解析（PyMuPDF）
│   │   ├── docx_parser.py     # DOCX 解析（python-docx）
│   │   ├── llm_client.py      # LLM 客户端（重试 + 结构化校验 + 日志脱敏）
│   │   ├── search_client.py  # 搜索客户端（Tavily / arXiv 统一接口 + 重试）
│   │   └── ppt_generator.py   # PPT 生成（python-pptx + 长度保护）
│   │
│   ├── agent/                 # Agent 编排
│   │   ├── chapter_splitter.py  # 章节拆分（Map-Reduce）
│   │   └── prompts/             # 提示词模板
│   │
│   ├── models/                # Pydantic 模型
│   │   └── schemas.py
│   │
│   └── utils/                 # 工具
│       ├── logger.py          # 日志（结构化）
│       ├── storage.py         # 存储 + 孤儿清理 + 磁盘监控
│       ├── auth.py            # X-API-Key 中间件（XFF 白名单）
│       ├── ratelimit.py       # 限流中间件（按 IP + 桶清理）
│       ├── error_handler.py   # 全局异常处理
│       └── validators.py      # 共享验证（paper_id / type / filename / magic）
│
├── tests/                     # 测试
│   ├── test_pdf_parser.py     # PDF 解析脚本测试
│   ├── test_docx_parser.py    # DOCX 解析脚本测试
│   ├── test_chapter_splitter.py  # 章节拆分
│   ├── test_auth_ratelimit.py # 鉴权 + 限流中间件（pytest）
│   ├── test_e2e.py            # 端到端
│   ├── test_file_reading_e2e.py  # 文件读取端到端（pytest）
│   └── test_docx_reading_e2e.py  # DOCX 端到端（pytest）
│
├── data/                      # 数据存储
│   ├── papers/                # 论文库（每篇一个目录）
│   │   └── p_2026_07_29_xxx/
│   │       ├── raw.{pdf,docx}
│   │       ├── text.json     # 解析结果
│   │       ├── analysis_*.json  # 分析结果缓存
│   └── ppts/                   # 生成的 PPT（定期清理）
│
├── logs/                      # 日志目录
│   └── app.log
│
├── requirements.txt
├── .env.example
└── README.md
```

## 已实现功能（W1-W8）

### 核心功能
- [x] POST `/api/upload` — 上传 PDF / DOCX（流式大小限制 + Magic Number 校验）
- [x] GET `/api/papers` — 论文库列表
- [x] GET `/api/papers/{id}` — 论文详情
- [x] DELETE `/api/papers/{id}` — 删除论文（联动清理 PPT）
- [x] GET `/api/papers/{id}/file` — 下载论文文件
- [x] POST `/api/analyze` — 单篇分析（breakdown / innovation / flaws）
- [x] POST `/api/analyze/stream` — SSE 流式版（仅 breakdown，带章节进度）
- [x] GET `/api/analyze/{paper_id}/{type}` — 获取缓存分析结果
- [x] POST `/api/search-related` — 联网搜相关工作（默认 arXiv，可选 Tavily）
- [x] POST `/api/compare` — 单论文 + 联网对比
- [x] POST `/api/compare-papers` — 多篇库内对比
- [x] POST `/api/generate-ppt` — 生成 PPT（含长度保护 + 路径穿越防护）
- [x] GET `/api/download-ppt/{filename}` — 下载 PPT
- [x] GET `/api/health` — 健康检查

### 安全
- [x] X-API-Key 鉴权（`APP_API_KEY` 配置）
- [x] 速率限制（IP + 桶，固定窗口）
- [x] 路径参数白名单（`validators.py`）
- [x] Magic Number 校验（防扩展名伪装）
- [x] 全局异常处理 + 错误脱敏
- [x] X-Forwarded-For 仅信任白名单反代
- [x] prod 模式强制要求 APP_API_KEY
- [x] Tavily API Key 走 Bearer Header
- [x] 孤儿/过期 PPT 自动清理

## 接口文档

完整接口定义、请求/响应示例见 [`docs/api-spec.md`](../docs/api-spec.md)。

## 变更日志

最近的代码审查与修复见 [`CHANGELOG.md`](../CHANGELOG.md)。

## 桌面版打包

把后端打成独立 exe（Electron 桌面版的一环）见 [`desktop/README.md`](../desktop/README.md)。
- W10: Redis 替换内存限流（支持多 worker）
- W11: 论文语义检索（向量化 + 全文检索）
- W12: 对象存储（S3/OSS）替换本地文件系统