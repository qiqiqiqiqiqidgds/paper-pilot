# PaperPilot — 技术架构（W1-02）

> 文档版本：v0.1 · 2026-07-16
> 配套项目：AI 论文/文献伴读 Agent

---

## 一、整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│ 浏览器                                                          │
│ ┌───────────────────────────────────────────────────────────┐  │
│ │ Next.js 14 (App Router)                                    │  │
│ │  ┌─────────┐ ┌─────────┐ ┌──────────┐ ┌────────────┐    │  │
│ │  │ 上传组件 │ │ PDF 渲染│ │  AI 展示 │ │  PPT 下载  │    │  │
│ │  └────┬────┘ └────┬────┘ └─────┬────┘ └──────┬─────┘    │  │
│ │       └────────────┴───────────┴─────────────┘           │  │
│ │                      ↕ 状态管理 (Zustand)                  │  │
│ └───────────────────────────┬─────────────────────────────────┘  │
└─────────────────────────────┼───────────────────────────────────┘
                              ↕ HTTP / SSE（WebSocket 已废弃，见 W1-03 3.8）
┌─────────────────────────────┴───────────────────────────────────┐
│ FastAPI 后端                                                     │
│ ┌────────────────────────────────────────────────────────────┐  │
│ │  API Layer                                                 │  │
│ │  /api/upload · /api/analyze · /api/compare                 │  │
│ │  /api/search-related · /api/compare-papers · /api/ppt      │  │
│ └──────────────────────┬─────────────────────────────────────┘  │
│ ┌──────────────────────┴─────────────────────────────────────┐  │
│ │  Service Layer（手写 Map-Reduce pipeline）                 │  │
│ │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │  │
│ │  │ PDF Parser│  │ Chapter  │  │   LLM    │  │  Search  │  │  │
│ │  │ (PyMuPDF)│→ │ Splitter │→ │  Client  │  │  Client  │  │  │
│ │  └──────────┘  └────┬─────┘  │(DeepSeek)│  │ (Tavily) │  │  │
│ │                       │        └────┬─────┘  └─────┬────┘  │  │
│ │                       ↓             ↓              ↓        │  │
│ │              asyncio.gather + Semaphore(3)                 │  │
│ │              Map: 每章并发 → Reduce: 汇总                  │  │
│ │                       ↓                                    │  │
│ │                 ┌──────────┐                                │  │
│ │                 │   PPT    │                                │  │
│ │                 │Generator │                                │  │
│ │                 └──────────┘                                │  │
│ └────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              ↕
┌─────────────────────────────┴───────────────────────────────────┐
│ 外部服务                                                          │
│  DeepSeek API · Tavily Search · (PPT 模板本地)                 │
└─────────────────────────────────────────────────────────────────┘
```

> **注**：当前实现是**手写 Map-Reduce 异步 pipeline**，不是状态机。
> 每种分析类型（拆解 / 创新 / 漏洞 / 对比）在 `app/api/` 下是**独立函数**，
> 通过 `asyncio.gather + Semaphore` 并发，无任何状态机框架依赖。

---

## 二、前端组件树

```
<App>
├── <TopBar>                              # 顶部栏
│   ├── <Logo />
│   ├── <UploadButton />
│   ├── <PaperLibraryButton />
│   ├── <SettingsButton />
│   └── <GeneratePPTButton />
│
├── <ThreeColumnLayout>                   # 三栏布局
│   │
│   ├── <FileSidebar>                     # 左：文件库
│   │   ├── <FileList>
│   │   │   └── <FileItem />              # 单个 PDF 条目
│   │   └── <UploadDropzone />
│   │
│   ├── <PDFViewer>                       # 中：PDF 渲染
│   │   ├── <PDFToolbar>
│   │   │   ├── <PageNav />               # 翻页
│   │   │   ├── <ZoomControl />           # 缩放
│   │   │   └── <SearchInPDF />           # 内部搜索
│   │   ├── <PDFCanvas>                   # pdf.js canvas
│   │   └── <HighlightLayer>              # 高亮覆盖层
│   │
│   └── <AIAnalysisPanel>                 # 右：AI 分析
│       ├── <TabBar>
│       │   ├── <Tab id="breakdown" />    # 拆解
│       │   ├── <Tab id="innovation" />   # 创新点
│       │   ├── <Tab id="compare" />      # 对比
│       │   ├── <Tab id="flaws" />        # 漏洞
│       │   └── <Tab id="ppt" />          # PPT
│       │
│       ├── <TabContent>                  # 内容区
│       │   ├── <BreakdownView />         # 五段拆解
│       │   ├── <InnovationView />        # 创新点
│       │   ├── <CompareView>             # 对比表
│       │   │   ├── <RelatedPaperList />
│       │   │   └── <CompareTable />
│       │   ├── <FlawsView />             # 漏洞
│       │   └── <PPTGeneratorView />      # PPT 配置 + 生成
│       │
│       └── <QuoteActions>                # 每段引用的操作
│           └── <JumpToPDFButton />       # 联动高亮
│
└── <ResizeHandle />                      # 中右分割条
```

### 2.1 关键组件依赖

| 组件 | 依赖库 | 说明 |
|------|--------|------|
| `<UploadButton>` | `react-dropzone` | 拖拽上传 |
| `<PDFCanvas>` | `react-pdf` + `pdfjs-dist` | PDF 渲染 |
| `<PDFCanvas>` | `pdfjs-dist` | pdf.js worker |
| `<HighlightLayer>` | 自研 SVG 覆盖层 | 联动高亮 |
| `<ResizeHandle>` | `react-resizable-panels` | 可拖拽分割 |
| `<TabContent>` | `react-markdown` + `remark-gfm` | Markdown 渲染 |
| `<CompareTable>` | `@tanstack/react-table` | 对比表 |
| `<PPTGeneratorView>` | 自研 + 后端 .pptx 模板 | PPT 预览 |

### 2.2 状态管理（Zustand）

```typescript
// stores/paperStore.ts
interface PaperState {
  papers: PaperMeta[];                   // 文件库
  currentPaperId: string | null;          // 当前论文
  pdfDoc: PDFDocumentProxy | null;        // pdf.js 文档
  currentPage: number;
  
  // 分析结果
  breakdown: Breakdown | null;
  innovation: Innovation | null;
  compare: Compare | null;
  flaws: Flaws | null;
  
  // 动作
  uploadPaper(file: File): Promise<void>;
  loadPaper(id: string): Promise<void>;
  setAnalysis(type: AnalysisType, data: any): void;
  jumpToPdf(quote: string): void;         // 联动核心
}
```

---

## 三、后端架构

### 3.1 目录结构

```
backend/
├── app/
│   ├── main.py                # FastAPI 入口
│   ├── api/
│   │   ├── upload.py          # 上传接口
│   │   ├── analyze.py         # 分析接口（Map-Reduce 五段拆解）
│   │   ├── compare_papers.py  # 多篇论文对比接口
│   │   ├── search.py          # 联网搜 + 主论文 vs 相关工作对比
│   │   ├── ppt.py             # PPT 生成接口
│   │   └── health.py          # 健康检查
│   ├── agent/
│   │   ├── chapter_splitter.py    # 章节识别（3 级 fallback）
│   │   └── prompts/
│   │       ├── breakdown.py   # 五段拆解 + 创新点 + 漏洞提示词
│   │       └── compare.py     # 对比提示词
│   ├── services/
│   │   ├── pdf_parser.py      # PyMuPDF 封装
│   │   ├── docx_parser.py     # python-docx 封装
│   │   ├── llm_client.py      # DeepSeek 封装（兼容 OpenAI SDK）
│   │   ├── search_client.py   # 搜索客户端（Tavily / arXiv 统一接口）
│   │   └── ppt_generator.py   # python-pptx
│   ├── models/
│   │   └── schemas.py         # Pydantic
│   └── utils/
│       ├── storage.py         # 本地存储
│       ├── auth.py
│       ├── ratelimit.py
│       └── logger.py
├── tests/
├── requirements.txt
└── .env
```

### 3.2 技术栈

| 模块 | 选型 | 理由 |
|------|------|------|
| Web 框架 | FastAPI | 异步、自动文档、类型提示 |
| Agent 编排 | **手写 Map-Reduce + asyncio.gather** | 简单可控、零依赖、易调试 |
| LLM | DeepSeek（兼容 OpenAI SDK）| 128K 上下文、便宜、中文好 |
| 章节识别 | 正则 + PDF 大纲（PyMuPDF `doc.get_toc()`）| 3 级 fallback |
| 并发限流 | `asyncio.Semaphore(3)` | 防止 LLM API 限流 |
| PDF 解析 | PyMuPDF (fitz) | 快、保留坐标、支持表格 |
| DOCX 解析 | python-docx | Word 论文支持 |
| 联网搜索 | Tavily API / arXiv API | 默认 **arXiv**（免费无需 key，学术论文搜索）；Tavily 为可选供应商（SEARCH_PROVIDER=tavily） |
| PPT | python-pptx | 纯 Python、模板丰富 |
| 数据存储 | 本地文件系统 | `data/papers/{paper_id}/`，无数据库 |
| 任务队列 | 暂不需要 | MVP 同步即可 |

---

## 四、核心算法：Map-Reduce 五段拆解

> 当前实现是**手写 Map-Reduce pipeline**，不是状态机。  
> 核心代码在 `backend/app/api/analyze.py::_analyze_breakdown()`。

### 4.1 整体流程

```
                  ┌──────────────────────────────────────┐
                  │ POST /api/analyze {type: breakdown}  │
                  └─────────────────┬────────────────────┘
                                    ↓
                  ┌──────────────────────────────────────┐
                  │ Step 1: 章节识别                     │
                  │ chapter_splitter.split()             │
                  │  - PDF 大纲 (doc.get_toc)            │
                  │  - 文本正则匹配 (SECTION_PATTERNS)   │
                  │  - 兜底：整篇作为 1 章                │
                  └─────────────────┬────────────────────┘
                                    ↓
              ┌─────────────────────┴─────────────────────┐
              │  ≥ 3 章？                                │
              │  ┌──── Yes ────┐    ┌──── No ────┐       │
              │  │ Map-Reduce  │    │ Legacy     │       │
              │  │ 走下面 4.2  │    │ 整篇一次    │       │
              │  └─────────────┘    └─────────────┘       │
              └─────────────────────┬─────────────────────┘
                                    ↓
                  ┌──────────────────────────────────────┐
                  │ 返回 {summary/background/goal/...}   │
                  └──────────────────────────────────────┘
```

### 4.2 Map-Reduce 实现（核心代码）

```python
# backend/app/api/analyze.py
async def _analyze_breakdown(data: dict, paper_language: str) -> dict:
    pages   = data.get("pages", [])
    full_text = data.get("full_text", "")
    paper_meta = data.get("meta", {})
    toc = data.get("toc", [])

    # Step 1: 章节识别
    chapters = split_chapters(pages=pages, toc=toc, full_text=full_text)

    # 兜底：少于 3 章走整篇模式（split_chapters 内部阈值同为 ≥3）
    if len(chapters) < 2:
        return await _analyze_with_legacy(
            full_text, paper_meta, paper_language, build_breakdown_messages
        )

    # Step 2: Map —— 并发分析每章
    llm = get_llm_client()
    semaphore = asyncio.Semaphore(3)  # 同时最多 3 个 LLM 调用

    async def map_one(ch):
        async with semaphore:
            return await llm.chat_json(
                messages=build_chapter_map_messages(ch, paper_meta, paper_language)
            )

    map_results_raw = await asyncio.gather(
        *[map_one(ch) for ch in chapters],
        return_exceptions=True
    )

    # Step 3: 收集成功结果
    successful_maps = []
    for ch, raw in zip(chapters, map_results_raw):
        if isinstance(raw, Exception):
            logger.warning(f"章节 [{ch.name}] Map 失败: {raw}")
            continue
        if not isinstance(raw, dict):
            continue
        raw.setdefault("chapter_name", ch.name)
        successful_maps.append(raw)

    if not successful_maps:
        raise HTTPException(status_code=502, detail="所有章节 Map 都失败了")

    # Step 4: Reduce —— 汇总成五段拆解
    final = await llm.chat_json(
        messages=build_reduce_messages(successful_maps, paper_meta, paper_language)
    )
    return final
```

### 4.3 关键模块说明

#### Chapter Splitter（章节识别）
- **文件**：`app/agent/chapter_splitter.py`
- **策略**（3 级 fallback）：
  1. **PDF 大纲**（`doc.get_toc()`）—— 100% 准，依赖 PDF 自带结构
  2. **文本模式匹配**（`SECTION_PATTERNS` 正则）—— 80% 准，覆盖标准章节标题
  3. **整篇兜底** —— 退回 legacy 整篇分析
- **关键配置**：`SECTION_KEYWORDS`（Abstract/Introduction/Method/Experiment/Conclusion…）

#### Map 阶段（单章分析）
- **提示词**：`app/agent/prompts/breakdown.py::build_chapter_map_messages`
- **输入**：单章文本（>20K 字符自动截断 head + tail）
- **输出 JSON**：`{chapter_name, summary, key_points, key_quote, page_ref, section_type}`
- **并发控制**：`asyncio.Semaphore(3)` 防止 DeepSeek 限流
- **失败容忍**：`return_exceptions=True` + 收集阶段过滤，单章失败不影响全局

#### Reduce 阶段（汇总五段）
- **提示词**：`app/agent/prompts/breakdown.py::build_reduce_messages`
- **输入**：所有成功章节的 Map 结果（JSON 数组）
- **输出 JSON**：`{summary, background, goal, method, experiment, conclusion, key_points, quotes}`
- **作用**：把 N 个章节分析合并、去重、逻辑连贯成最终五段

#### Legacy 模式（兜底）
- **用途**：章节数 <2 时（短论文 / 无章节），或创新点 / 漏洞分析
- **实现**：整篇文本一次性塞给 LLM
- **截断策略**：>60K 字符取 head + tail

### 4.4 为什么这够用？

> **当前实现没有 LLM 任务自动规划 / 状态机 / 长期记忆**，
> 但通过**分章 Map-Reduce + 模块化 API**已经能覆盖核心场景。

| 能力 | 实现 | 说明 |
|------|------|------|
| 长文分析 | ✅ Map-Reduce 分章 | 单章 ≤ 20K 字符，避开 LLM 上下文瓶颈 |
| 并发提速 | ✅ `asyncio.gather` | 5 章论文：串行 ~25s → 并发 ~8s |
| 失败容忍 | ✅ `return_exceptions=True` | 单章失败不阻塞整篇 |
| 任务分发 | ✅ 4 个独立 API | breakdown / innovation / flaws / compare 互不耦合 |
| 工具调用 | ✅ LLM 调 PDF/搜索/PPT | 通过 `services/` 层封装 |
| 状态记忆 | ❌ 当前不实现 | MVP 阶段不必要，论文库靠文件系统 |
| 自主规划 | ❌ 当前不实现 | 4 种分析类型写死路径，不做 LLM 自动拆任务 |

---

## 五、数据流图

### 5.1 单篇论文"拆解"流程（Map-Reduce）

```
用户上传 PDF
    ↓
POST /api/upload
    ↓
PyMuPDF 解析：提取全文 + pages + toc
    ↓
存到 data/papers/{paper_id}/text.json
    ↓
返回 paper_id
    ↓
前端请求 POST /api/analyze (paper_id, type=breakdown)
    ↓
analyze._analyze_breakdown() 启动：
  ┌─ Step 1: chapter_splitter.split()
  │    → 识别出 N 个章节（PDF 大纲 / 文本模式 / 兜底）
  ├─ Step 2: Map 阶段
  │    → asyncio.gather([map_one(ch) for ch in chapters])
  │    → Semaphore(3) 限流，每章一次 DeepSeek 调用
  │    → 收集成功的章节分析
  └─ Step 3: Reduce 阶段
       → 1 次 DeepSeek 调用，汇总成五段
    ↓
保存到 data/papers/{paper_id}/analysis_breakdown.json
    ↓
返回 JSON 给前端
    ↓
前端 Markdown 渲染 + 联动高亮
```

### 5.2 对比流程

**联网对比**（POST /api/compare）：
```
用户上传 1 篇论文
    ↓
POST /api/search-related → 搜索供应商（默认 arXiv）搜 3-5 篇相关工作
    ↓
POST /api/compare → 1 次 DeepSeek 调用生成对比表
    ↓
返回主论文 vs 相关工作 的对比 JSON
```

**多篇论文对比**（POST /api/compare-papers）：
```
用户上传 N 篇论文（N≥2）
    ↓
每篇都已 parse 完毕，存了 full_text / abstract
    ↓
POST /api/compare-papers (paper_ids, main_id)
    ↓
1 次 DeepSeek 调用，生成多维对比表
    ↓
返回对比 JSON
```

---

## 六、部署架构

### 6.1 MVP（本地开发 + 演示）

```
本地：
  后端：http://localhost:8000  (uvicorn)
  前端：http://localhost:3000  (next dev)
  数据：./data/papers/{paper_id}/  (raw.pdf + text.json + analysis_*.json)
```

### 6.2 比赛展示版本

```
云端：
  前端：Vercel 免费版（Next.js 静态 + API routes）
  后端：Railway / Render 免费额度
  数据：同本地，绑定 volume
  域名：paperpilot.vercel.app（可选）
```

### 6.3 答辩演示版本

- 提前上传 3 篇目标领域的论文
- 现场只跑"对比"功能
- 录屏备份（防网崩）

---

## 七、关键技术决策记录

| 决策 | 选项 | 最终选择 | 理由 |
|------|------|----------|------|
| Agent 编排 | 状态机框架 / 串行调用 / 手写 | **手写 Map-Reduce** | 简单可控、零依赖、5 章论文并发 ~8s 完事 |
| LLM | GPT-4 / Claude / DeepSeek / Qwen | DeepSeek | 便宜、128K、中文好 |
| 章节识别 | 整篇一次 / PDF 大纲 / 文本模式 / 整篇兜底 | **3 级 fallback** | 无大纲时仍能拆，准确率 80%+ |
| 并发限流 | 串行 / 队列 / Semaphore | `asyncio.Semaphore(3)` | 够用，不超 DeepSeek 限流 |
| 数据存储 | SQLite / 向量库 / 本地文件 | **本地文件系统** | MVP 阶段无关系查询需求 |
| 前端框架 | Next.js / Vite+React / Vue | Next.js 14 | SSR、生态、答辩稳 |
| UI 库 | shadcn/ui / Ant Design / MUI | shadcn/ui | 轻、好看、可改 |
| 状态管理 | Redux / Zustand / Jotai | Zustand | 简单、够用 |
| PDF 渲染 | iframe / pdf.js / pdf.js-dist | pdf.js-dist | 可控、可编程 |
| PPT 模板 | 自研 / 抄模板 / LLM 生成 | 抄模板 + 简单排版 | 答辩够用 |

---

> 状态：✅ W1-02 完成
> 下一步：W1-03 接口文档
