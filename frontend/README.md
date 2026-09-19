# PaperPilot Frontend

AI 论文/文献伴读 Agent 的前端（Next.js 14）。

## 技术栈

- **框架**：Next.js 14 (App Router) + TypeScript
- **样式**：Tailwind CSS + shadcn/ui 风格
- **PDF 渲染**：react-pdf + pdfjs-dist（worker 本地化）
- **DOCX**：不支持在线预览，提供下载
- **Markdown 渲染**：CSS `.markdown` 样式类（react-markdown 未安装）
- **布局**：固定三栏（侧栏 + PDF + AI 面板）
- **状态**：Zustand（含 ObjectURL 清理 + isStale 竞态防护）
- **图标**：lucide-react
- **响应式**：lg 以下抽屉化（lg:hidden + MobilePanel）

## 启动

```bash
cd frontend
cp .env.local.example .env.local  # 可选：填 BACKEND_URL / BACKEND_API_KEY
npm install
npm run dev
```

访问 http://localhost:3000

### 环境变量

```bash
# 后端地址（默认 http://localhost:8000），由 Next.js BFF 代理（/api/proxy）转发
BACKEND_URL=http://localhost:8000

# API Key（与后端 APP_API_KEY 保持一致；留空 = 不鉴权）
# 浏览器 bundle 不包含任何密钥：X-API-Key 由 BFF 代理在服务端附加
BACKEND_API_KEY=
```

## 目录结构

```
frontend/
├── src/
│   ├── app/                   # Next.js App Router
│   │   ├── layout.tsx         # 根布局 + Toaster
│   │   ├── page.tsx           # 主页（三栏布局 + ErrorBoundary + MobilePanel）
│   │   └── globals.css
│   │
│   ├── components/
│   │   ├── ui/                # shadcn 风格组件
│   │   │   ├── button.tsx     # 默认 type="button"
│   │   │   ├── tabs.tsx
│   │   │   ├── progress.tsx
│   │   │   ├── scroll-area.tsx
│   │   │   ├── alert-dialog.tsx
│   │   │   └── card.tsx
│   │   │
│   │   ├── top-bar.tsx        # 顶部导航（上传/PPT/导出/暗色切换）
│   │   ├── file-sidebar.tsx   # 论文库侧栏（a11y + 多选对比）
│   │   ├── upload-button.tsx  # 上传按钮（防双触发 + XHR 进度）
│   │   ├── pdf-viewer.tsx     # PDF 阅读器（Worker 本地化 + 联动高亮 3s 渐隐）
│   │   ├── ai-analysis-panel.tsx  # AI 分析面板（5 Tab + 快捷键切 Tab）
│   │   ├── error-boundary.tsx # 全局错误边界
│   │   ├── mobile-toggle.tsx  # 移动端侧栏抽屉
│   │   └── resizable-pane.tsx # PDF|AI 面板可拖拽分割条（30:70 ~ 70:30）
│   │
│   ├── lib/
│   │   ├── api.ts             # API 客户端（AbortController + XHR + SSE）
│   │   ├── export.ts          # 分析报告导出（Markdown）
│   │   └── utils.ts
│   │
│   ├── hooks/
│   │   └── use-keyboard-shortcuts.ts  # 全局快捷键（←/→ 翻页、1-5 切 Tab）
│   │
│   ├── stores/
│   │   └── paper-store.ts     # Zustand（results 按 paper_id 分组 + isStale）
│   │
│   └── types/index.ts         # TypeScript 类型
│
├── tests/                     # vitest 单元测试（jsdom + @/ alias）
└── public/
```

## 已实现功能（W1-W8）

### 核心
- [x] 三栏布局（论文库 + PDF + AI 面板）
- [x] PDF 上传 + 列表 + 删除
- [x] PDF 渲染（react-pdf + 文本高亮）
- [x] DOCX 标识 + 下载引导（不支持在线预览）
- [x] AI 五段拆解 Tab（结构化总结 + 原文引用跳转）
- [x] 创新点 Tab（核心创新 + 等级评估 + 跳转 PDF）
- [x] 对比 Tab（联网搜 + 多篇对比）
- [x] 漏洞 Tab（方法/实验/写作三层 + 跳转 PDF）
- [x] PPT Tab（生成 + 下载 + 进度反馈）
- [x] AI 引用 → PDF 联动高亮（点击跳转到页 + 文本高亮）

### 工程化（W7-W8）
- [x] 全局 ErrorBoundary（三大区域隔离崩溃）
- [x] AbortController + 超时（普通 30s / SSE 10min / 上传 5min）
- [x] XHR onprogress 真实上传进度
- [x] Store 竞态防护（results 按 paper_id + isStale）
- [x] 移动端响应式（< lg 抽屉化）
- [x] 完整 a11y（aria-label / role / 键盘导航 / focus-visible）
- [x] PDF Worker 本地化（无 CDN 依赖）

## 与后端的 API 对接

所有请求经 Next.js BFF 代理（`/api/proxy/[...path]`）转发到后端，`X-API-Key` 由代理在服务端统一附加（浏览器 bundle 不包含密钥）。超时和取消通过 AbortController：

```typescript
import { api, API_BASE } from "@/lib/api";

// 普通请求（30s 超时）
const papers = await api.listPapers();

// 流式分析（SSE，10min 超时）
for await (const ev of consumeSSE("/api/analyze/stream", body)) {
  // ...
}

// 上传（XHR onprogress，5min 超时）
await api.upload(file, {
  onProgress: (loaded, total) => setProgress(loaded / total),
});
```

## 类型检查 & Lint

```bash
# TypeScript 类型检查
npx tsc --noEmit -p tsconfig.json

# ESLint（待配置）
npm run lint
```

## 变更日志

最近的代码审查与修复见 [`CHANGELOG.md`](../CHANGELOG.md)。

## 下一步（建议）

- W9: 引入 Vitest 单元测试 + Playwright E2E
- W10: 增加论文笔记 / 收藏夹 / 标签
- W11: 论文库语义搜索
- W12: 浏览器插件版（在新标签页打开论文）