# PaperPilot — 接口文档（W1-03）

> 文档版本：v0.2 · 2026-07-29（已与代码同步）
> 配套项目：AI 论文/文献伴读 Agent
> 基础路径：`http://localhost:8000`（开发） / `https://api.paperpilot.com`（生产）

---

## 一、API 总览

| 方法 | 路径 | 说明 | 阶段 |
|------|------|------|------|
| GET | `/api/health` | 健康检查 | W2 |
| POST | `/api/upload` | 上传 PDF / DOCX（≤50MB） | W2-W8 |
| GET | `/api/papers` | 获取论文库列表 | W3 |
| GET | `/api/papers/{id}` | 获取论文详情 | W3 |
| DELETE | `/api/papers/{id}` | 删除论文（联动清理 PPT） | W7 |
| GET | `/api/papers/{id}/file` | 下载论文文件 | W7 |
| POST | `/api/analyze` | 单篇分析（拆解/创新/漏洞） | W2-W5 |
| POST | `/api/analyze/stream` | **SSE 流式版**（仅 breakdown，带章节进度） | W7 |
| GET | `/api/analyze/{paper_id}/{type}` | 获取缓存分析结果 | W7 |
| POST | `/api/search-related` | 联网搜相关工作 | W4 |
| POST | `/api/compare` | **单论文 + 联网**对比 | W4-W5 |
| POST | `/api/compare-papers` | **多篇库内**对比 | W5 |
| POST | `/api/generate-ppt` | 生成汇报 PPT（同步返回） | W6 |
| GET | `/api/download-ppt/{filename}` | 下载 PPT | W6 |

---

## 二、通用约定

### 2.1 请求/响应格式
- Content-Type: `application/json`（文件上传用 `multipart/form-data`）
- 编码：UTF-8
- 时间格式：ISO 8601

### 2.2 统一响应结构

```json
{
  "code": 0,
  "message": "ok",
  "data": { ... }
}
```

- `code = 0`：成功
- `code != 0`：失败，message 含错误说明

### 2.3 错误码

> **实际实现说明（2026-08 同步）**：业务错误码体系未按最初设计落地。
> 当前实现：所有错误响应的 `code` 字段 = HTTP 状态码（400/404/413/422/429/401/500/502），
> 唯一例外是 `4001`（联网搜索无结果/供应商未配置），以 **HTTP 200 + code=4001 + 空数据** 返回（前端据此渲染空态而非报错）。
> 下表为原始设计，仅作历史参考，不再实现。

| code | 含义 | HTTP |
|------|------|------|
| 0 | 成功 | 200 |
| 1001 | 参数错误 | 400 |
| 1002 | 文件格式错误 | 400 |
| 1003 | 文件过大（>50MB） | 413 |
| 1004 | PDF 加密 | 400 |
| 2001 | 论文不存在 | 404 |
| 3001 | LLM 调用失败 | 502 |
| 3002 | LLM 超时 | 504 |
| 4001 | 联网搜索失败（Tavily 未配置或无结果） | 200（HTTP 200 + 空数据） |
| 5001 | 内部错误 | 500 |
| 429 | 速率限制（IP 桶满） | 429 |
| 401 | 未授权（X-API-Key 缺失或错误） | 401 |
| 422 | 请求体验证失败 | 422 |

### 2.4 通用 Header

| Header | 说明 |
|--------|------|
| `X-API-Key` | **鉴权 header**（部署后必填，未配 APP_API_KEY 则不校验） |
| `X-Request-Id` | 请求 ID（用于日志追踪） |
| `X-Response-Time-ms` | 响应时间 |
| `Retry-After` | 限流响应头（秒数） |

---

## 三、详细接口

### 3.1 POST /api/upload

**说明**：上传一个 PDF / DOCX 文件，返回 paper_id。

**请求**：`multipart/form-data`
- `file`: PDF 或 DOCX 文件（必填，≤50MB）

**支持的后缀**：`.pdf`, `.docx`

**校验**：
- 后缀白名单（仅 `.pdf` / `.docx`）
- Magic Number 校验（PDF `%PDF-` / DOCX `PK\x03\x04`），防止扩展名伪装
- 文件大小 ≤ 50MB（流式检查 + Content-Length 预检）
- 文件 ≥ 100 bytes（拒绝空文件）

**响应**：
```json
{
  "code": 0,
  "data": {
    "paper_id": "p_2026_07_29_abc123",
    "filename": "transformer_2017.pdf",
    "size": 2156789,
    "pages": 12,
    "file_type": "pdf",
    "title": "Attention Is All You Need",
    "authors": ["Vaswani A", "Shazeer N", ...],
    "abstract": "We propose a new simple network architecture...",
    "uploaded_at": "2026-07-29T15:30:00Z"
  }
}
```

**错误码**：
- 400：`不支持的文件后缀` / `文件内容与扩展名不匹配` / `文件过小`
- 413：`文件过大`
- 500：`保存文件失败`

**实现细节**：
- PDF 用 PyMuPDF 解析首页提取标题、作者、年份、摘要、关键词
- DOCX 用 python-docx 解析 Heading 1 + 第一段（非空）作为标题
- 全文存入 `data/papers/{paper_id}/raw.{pdf,docx}`
- 解析后的文本存 `data/papers/{paper_id}/text.json`

---

### 3.2 GET /api/papers

**说明**：获取论文库列表（按上传时间倒序）。

**请求参数**：无（分页 `limit`/`offset`、搜索 `keyword` 尚未实现，返回全量列表）

**响应**：
```json
{
  "code": 0,
  "data": {
    "total": 5,
    "items": [
      {
        "paper_id": "p_2026_07_16_abc123",
        "filename": "transformer_2017.pdf",
        "size": 1048576,
        "file_type": "pdf",
        "title": "Attention Is All You Need",
        "authors": ["Vaswani, Ashish"],
        "pages": 12,
        "uploaded_at": "2026-07-16T17:30:00",
        "has_breakdown": true,
        "has_innovation": true,
        "has_compare": false,
        "has_flaws": false
      }
    ]
  }
}
```

---

### 3.3 GET /api/papers/{id}

**说明**：获取单篇论文数据（**不含分析结果**，分析结果走 `GET /api/analyze/{id}/{type}`）。
**实际返回结构（2026-08 同步）**：
```json
{
  "code": 0,
  "data": {
    "paper_id": "p_xxx",
    "filename": "...",
    "size": 1048576,
    "file_type": "pdf",
    "meta": { "title": "...", "authors": [...], "abstract": "...", "year": 2017, "keywords": [...] },
    "page_count": 12,
    "full_text_length": 123456
  }
}
```
> 注：原设计承诺内嵌 breakdown/innovation/compare/flaws 与顶层 title/authors/abstract/pages，**未实现**；前端按上述实际结构消费（详情见 `backend/app/api/upload.py:get_paper`）。

---

### 3.4 POST /api/analyze

**说明**：对一篇论文执行指定类型的分析。

**请求**：
```json
{
  "paper_id": "p_xxx",
  "type": "breakdown",       // breakdown / innovation / flaws
  "paper_language": "中文"   // 可选：中文 / English / 日本語
}
```

**响应（普通模式）**：
```json
{
  "code": 0,
  "data": {
    "type": "breakdown",
    "result": {
      "summary": "本文提出 Transformer...",
      "background": "传统的 RNN/CNN 在序列建模上存在...",
      "goal": "解决长序列依赖和并行训练问题",
      "method": "基于自注意力机制...",
      "experiment": "在 WMT 翻译任务上达到 SOTA...",
      "conclusion": "Transformer 在多个任务上超越 RNN/CNN",
      "key_points": ["...", "..."],
      "quotes": [
        { "section": "摘要", "text": "Attention Is All You Need", "page": 1 }
      ]
    },
    "elapsed_ms": 8234
  }
}
```

### 3.5 POST /api/analyze/stream

**说明**：SSE 流式分析端点（仅 breakdown），带 Map-Reduce 章节进度。

**请求**：同 `/api/analyze`

**响应**：Server-Sent Events 流

```
event: started
data: {"paper_id":"p_xxx","type":"breakdown"}

event: chapters_detected
data: {"count":5,"chapters":[{"name":"Introduction","page_start":1,"page_end":2},...]}

event: map_started
data: {"chapter":"Introduction"}

event: map_completed
data: {"chapter":"Introduction","summary_preview":"..."}

event: map_failed
data: {"chapter":"Method","error":"LLM timeout"}

event: progress
data: {"stage":"map","completed":2,"total":5}

event: maps_completed
data: {"success":4,"total":5}

event: reduce_started
data: {"chapter_count":4}

event: reduce_completed
data: {"result":{"summary":"...","background":"...","goal":"...","method":"...","experiment":"...","conclusion":"...","key_points":[...],"quotes":[...]}}

event: done
data: {"elapsed_ms":23456,"result":{...}}

event: error
data: {"message":"...","code":500}
```

**注意**：SSE 期间 HTTP 状态码始终是 200（即使 paper 不存在），错误通过 `error` 事件传递。

---

### 3.5 POST /api/compare

**说明**：对**单篇论文 + 联网搜相关工作**做对比分析。

**请求**：
```json
{
  "paper_id": "p_main",           // 主论文（必填）
  "max_results": 5,               // 默认 5，范围 1-10
  "paper_language": "中文"        // 可选：中文 / English / 日本語
}
```

**响应**：
```json
{
  "code": 0,
  "data": {
    "main_paper": {
      "title": "Attention Is All You Need",
      "year": 2017,
      "method_summary": "..."
    },
    "related_papers": [
      {
        "title": "BERT: Pre-training of Deep Bidirectional Transformers",
        "url": "https://arxiv.org/abs/1810.04805",
        "method": "双向 Transformer 预训练",
        "dataset": "GLUE / SQuAD",
        "result": "GLUE 80.5%",
        "pros": "双向注意力、预训练范式",
        "cons": "参数量大、推理慢",
        "year": 2018,
        "relation_to_main": "基于 Transformer 架构"
      }
    ],
    "compare_table": [
      ["维度", "Transformer (2017)", "BERT (2018)"],
      ["方法", "自注意力", "双向自注意力+预训练"],
      ["参数量", "65M", "340M"],
      ["应用", "翻译", "通用 NLP"]
    ],
    "summary": "相比 Transformer，BERT 通过双向预训练..."
  }
}
```

### 3.6 POST /api/compare-papers

**说明**：对**多篇已上传的论文**做对比分析（区别于联网搜对比）。

**请求**：
```json
{
  "paper_ids": ["p_main", "p_1", "p_2"],   // 2-5 篇，去重
  "main_id": "p_main",                       // 主论文（必须在 paper_ids 中）
  "paper_language": "中文"
}
```

**校验**：
- `paper_ids` 长度 2-5，元素必须符合 `^[A-Za-z0-9_-]{1,64}$`
- `main_id` 必须匹配相同正则
- `main_id` 必须在 `paper_ids` 中
- `paper_ids` 不能重复

---

### 3.7 POST /api/search-related

**说明**：联网搜索与某论文相关的工作。

**请求**：
```json
{
  "paper_id": "p_xxx",
  "max_results": 5           // 默认 5，范围 1-10
}
```

**响应**：
```json
{
  "code": 0,
  "data": {
    "related": [
      {
        "title": "BERT: Pre-training of Deep Bidirectional Transformers",
        "url": "https://arxiv.org/abs/1810.04805",
        "content": "We introduce a new language representation model...",
        "score": 0.92
      }
    ]
  }
}
```

**实现细节**：
- 用论文标题 + "related work" 调 Tavily 搜索
- 限定学术域：arxiv.org / aclanthology.org / ieee.org / acm.org / openreview.net 等
- 失败时返回 `code=4001, message="Tavily API Key 未配置"`
- 实际由 TavilyClient 调用，带指数退避重试（429/5xx/Timeout 重试 3 次）
- Tavily Key 走 Bearer Header，不放在 body（防日志泄露）

### 3.8 POST /api/generate-ppt

**说明**：基于论文已有分析结果生成 PPT（同步返回）。

**请求**：
```json
{
  "paper_id": "p_xxx",
  "include_flaws": false,    // 是否包含漏洞页
  "include_compare": false,  // 是否包含对比页
  "template": "default"       // 当前仅支持 "default"
}
```

**校验**：
- paper_id 必须符合 `^[A-Za-z0-9_-]{1,64}$`（防路径穿越）
- 必须已有 breakdown 或 innovation 分析结果

**响应（同步）**：
```json
{
  "code": 0,
  "data": {
    "download_url": "/api/download-ppt/p_xxx_xxx_汇报.pptx",
    "filename": "p_xxx_xxx_汇报.pptx",
    "size": 256789,
    "pages": 12
  }
}
```

**实现细节**：
- LLM 输出 bullet 单条 ≤ 200 字符（防撑爆文本框）
- 控制字符过滤（保留 `\t \n`）
- 作者列表 ≤ 80 字符（防解析错误撑爆标题页）
- 原子写（tmp + rename）
- 启动 + 每 6 小时后台清理过期 PPT（>7 天的）

### 3.9 GET /api/download-ppt/{filename}

**说明**：下载 PPT 文件。

**校验**：
- filename 不含 `..` / `/` / `\` / 不以 `.` 开头
- 长度 ≤ 128 字符

**响应**：binary file stream（Content-Disposition 包含原文件名 RFC 5987 编码）

---

### 3.10 GET /api/analyze/{paper_id}/{analysis_type}

**说明**：获取已保存的分析结果（缓存读）。

**参数**：
- `paper_id`：必须匹配 `^[A-Za-z0-9_-]{1,64}$`
- `analysis_type`：必须为 `breakdown` / `innovation` / `flaws` / `compare`

**响应**：
```json
{
  "code": 0,
  "data": {
    "type": "breakdown",
    "result": { /* Breakdown 对象 */ }
  }
}
```

---

---

### 3.7 POST /api/generate-ppt

**说明**：基于分析结果生成汇报 PPT。

**请求**：
```json
{
  "paper_id": "p_xxx",
  "style": "academic",        // academic / popular
  "template": "default",      // default / ieee / cas
  "include_compare": true,
  "include_flaws": false,
  "page_count": 10            // 目标页数，默认 8-12
}
```

**响应**：
```json
{
  "code": 0,
  "data": {
    "task_id": "ppt_2026_07_16_xyz",
    "status": "processing",   // processing / done / failed
    "download_url": null
  }
}
```

**轮询 / WebSocket**：
- ~~简单方案：前端每 2 秒 GET `/api/ppt-status/{task_id}`~~
- ~~推荐方案：WebSocket `/ws/ppt/{task_id}` 实时推送进度~~

> ⚠️ **已废弃（2026-08 同步）**：异步 PPT 方案（task_id/轮询/WebSocket/style/page_count）**从未实现**。
> 当前为**同步方案**：`POST /api/generate-ppt` 直接返回 `download_url/filename/size/pages`（见下文 3.9），
> 前端 `ppt-view.tsx` 即按此契约消费。本节 3.7 仅作历史参考。

**完成时**：
```json
{
  "code": 0,
  "data": {
    "task_id": "ppt_xxx",
    "status": "done",
    "download_url": "/files/ppt/transformer_2017.pptx",
    "expires_at": "2026-07-17T17:30:00Z"
  }
}
```

---

### 3.8 WS /ws/analyze

> ⚠️ **已废弃**：原计划 WebSocket 接口未实现，改用 **SSE**（详见 3.5 `/api/analyze/stream`）

---

### 3.11 GET /api/health

**说明**：健康检查（K8s/容器探针用）。

**响应**：
```json
{
  "code": 0,
  "data": {
    "status": "ok",
    "version": "0.1.0",
    "llm": "configured",   // 实际值: configured / missing_key
    "search": "arxiv"      // 实际值: arxiv / tavily / missing_key
  }
}
```

**鉴权**：免鉴权、免限流（公开端点）

> 注：原设计 `llm:"connected"/search:"connected"` 未采用，语义更丰富但值不同（2026-08 同步）。

---

## 四、数据结构定义（核心模型）

### 4.1 Breakdown（五段拆解）

```typescript
interface Breakdown {
  summary: string;          // 摘要
  background: string;       // 研究背景
  goal: string;             // 研究目标
  method: string;           // 方法
  experiment: string;       // 实验
  conclusion: string;       // 结论
  quotes: Quote[];          // 原文引用
}

interface Quote {
  section: string;          // 章节名
  text: string;             // 引用文本
  page: number;             // 页码
  bbox?: BBox;              // PDF 坐标（联动高亮用）
}
```

### 4.2 Innovation（创新点）

```typescript
interface Innovation {
  core_innovations: InnovationItem[];
  innovation_level: 'incremental' | 'significant' | 'disruptive';
  applicable_scenarios: string[];
  quotes: Quote[];
}

interface InnovationItem {
  title: string;
  description: string;
  page_ref: number;
}
```

### 4.3 Compare（对比）

```typescript
interface Compare {
  main: PaperRef;
  papers: ComparedPaper[];
  compare_table: string[][];   // 二维数组直接渲染表格
  summary: string;
}

interface PaperRef {
  paper_id: string;
  title: string;
  year: number;
}

interface ComparedPaper {
  paper_id?: string;           // 已上传的论文才有
  external?: ExternalPaper;    // 联网搜的相关工作
  method: string;
  dataset?: string;
  result?: string;
  pros: string;
  cons: string;
  relation: string;            // 与主论文的关系
}
```

### 4.4 Flaws（漏洞）

```typescript
interface Flaws {
  method_level: FlawItem[];
  experiment_level: FlawItem[];
  writing_level: FlawItem[];
  improvements: Improvement[];
}

interface FlawItem {
  description: string;
  evidence: string;            // 原文证据
  page_ref: number;
  severity: 'minor' | 'major';
}

interface Improvement {
  flaw_ref: number;            // 对应上面哪条
  suggestion: string;
  feasibility: 'low' | 'medium' | 'high';
}
```

---

## 五、性能与限制

| 指标 | MVP 目标 | 备注 |
|------|----------|------|
| 上传 + 解析 | < 30s | 12 页论文 |
| 单篇拆解 | < 15s | DeepSeek 流式 |
| 单篇创新 | < 12s | |
| 联网搜 | < 8s | Tavily |
| 多篇对比 | < 30s | 3 篇 + 3 篇相关 |
| PPT 生成 | < 60s | 10 页 |
| 并发 | 5 用户 | 个人演示足够 |

| 限制 | 值 | 说明 |
|------|------|------|
| 单 PDF 大小 | 50MB | 约 200 页 |
| 论文页数 | 200 页 | 超出需 chunking |
| 论文库容量 | 100 篇 | 演示场景够用 |
| 上下文长度 | 128K tokens | DeepSeek 上限 |

---

## 六、接口调用示例

### 6.1 前端完整调用流程

```typescript
// 1. 上传（带进度）
const form = new FormData();
form.append('file', file);
const uploadRes = await fetch('/api/upload', {
  method: 'POST',
  body: form,
  headers: API_KEY ? { 'X-API-Key': API_KEY } : {},
});
const { paper_id } = uploadRes.data;

// 2. 流式分析（SSE）
const sse = consumeSSE('/api/analyze/stream', { paper_id, type: 'breakdown' });
for await (const ev of sse) {
  switch (ev.event) {
    case 'chapters_detected': setTotalChapters(ev.data.count); break;
    case 'progress':          setProgress(ev.data.completed, ev.data.total); break;
    case 'reduce_completed':  setResult(ev.data.result); break;
    case 'error':             toast.error(ev.data.message); break;
  }
}

// 3. 搜相关工作
const searchRes = await fetch('/api/search-related', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', 'X-API-Key': API_KEY },
  body: JSON.stringify({ paper_id, max_results: 5 }),
});

// 4. 单论文 + 联网对比
const compareRes = await fetch('/api/compare', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', 'X-API-Key': API_KEY },
  body: JSON.stringify({ paper_id: mainId, max_results: 5 }),
});

// 5. 多篇库内对比
const comparePapersRes = await fetch('/api/compare-papers', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', 'X-API-Key': API_KEY },
  body: JSON.stringify({ paper_ids: ids, main_id: mainId }),
});

// 6. 生成 PPT
const pptRes = await fetch('/api/generate-ppt', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', 'X-API-Key': API_KEY },
  body: JSON.stringify({ paper_id: mainId, include_flaws: false, include_compare: false }),
});
// data: { download_url, filename, size, pages }
```

---

> 状态：✅ W1-W8 全部完成
> 文档版本：v0.2（2026-07-29，已与代码同步）
> 变更：拆分 `/api/compare` 和 `/api/compare-papers`，新增 `/api/analyze/stream` (SSE)、`/api/download-ppt/{filename}`、错误码 401/422/429
> 完整代码审查修复记录：[`CHANGELOG.md`](../CHANGELOG.md)
