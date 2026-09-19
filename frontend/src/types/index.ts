// 论文相关类型定义

export interface PaperMeta {
  title: string;
  authors: string[];
  abstract: string;
  keywords: string[];
  year?: number;
  venue?: string;
}

export interface PaperInfo {
  paper_id: string;
  filename: string;
  size: number;
  pages: number;
  file_type: "pdf" | "docx";
  title: string;
  authors: string[];
  uploaded_at: string;
  // 注意：后端 /api/papers 列表项不含 abstract（列表不返回摘要），UploadResponse 才有
  abstract?: string;
  has_breakdown?: boolean;
  has_innovation?: boolean;
  has_compare?: boolean;
  has_flaws?: boolean;
}

/**
 * GET /api/papers/{id} 的返回结构（与后端 upload.py get_paper 对齐）
 * 注意：与 PaperInfo（列表项）字段不同，这是"论文数据"视图：
 * 不含 title/pages 顶层字段，元数据在 meta 下，页数在 page_count。
 */
export interface PaperDetail {
  paper_id: string;
  filename: string;
  size: number;
  file_type: "pdf" | "docx";
  meta: PaperMeta;
  page_count: number;
  full_text_length: number;
}

export interface Quote {
  section: string;
  text: string;
  page: number;
}

export interface BreakdownResult {
  summary: string;
  background: string;
  goal: string;
  method: string;
  experiment: string;
  conclusion: string;
  key_points: string[];
  quotes: Quote[];
}

export interface InnovationItem {
  title: string;
  description: string;
  evidence: string;
  page_ref: number;
}

export interface InnovationResult {
  core_innovations: InnovationItem[];
  innovation_level: string;
  level_reasoning: string;
  applicable_scenarios: string[];
  quotes: Quote[];
}

export interface FlawItem {
  description: string;
  evidence: string;
  page_ref: number;
  severity: string;
}

export interface FlawsResult {
  method_level: FlawItem[];
  experiment_level: FlawItem[];
  writing_level: FlawItem[];
  improvements: { flaw_ref: number; suggestion: string; feasibility: string }[];
  overall_assessment: string;
  quotes: Quote[];
}

export type AnalysisType = "breakdown" | "innovation" | "flaws";
export type AnalysisResult = BreakdownResult | InnovationResult | FlawsResult;

/**
 * 论文全部分析结果（含对比）：store 中 results[paper_id] 的 value 类型
 * compare 不经过 /api/analyze，由 /api/compare 或 /api/compare-papers 生成并缓存
 */
export interface PaperResults {
  breakdown?: BreakdownResult;
  innovation?: InnovationResult;
  flaws?: FlawsResult;
  compare?: CompareResponse;
}

// ====== W4 联网搜 / W5 多篇对比 共用类型 ======

/**
 * 单条相关论文（联网搜 / 多篇库内对比共用）
 * - paper_id: 仅多篇库内对比时存在（联网搜时为 undefined）
 */
export interface RelatedPaper {
  title: string;
  year?: number | string;
  url?: string;
  method?: string;
  dataset?: string;
  result?: string;
  pros?: string;
  cons?: string;
  relation_to_main?: string;
  paper_id?: string;
}

export interface CompareMainPaper {
  title: string;
  year?: number | string;
  method_summary?: string;
}

/**
 * 对比接口统一响应（compare / compare-papers 共用）
 * - compare_table 行为 Markdown 表格的二维字符串数组
 */
export interface CompareResponse {
  main_paper?: CompareMainPaper;
  related_papers: RelatedPaper[];
  compare_table?: string[][];
  summary?: string;
  main_advantages?: string[];
  main_disadvantages?: string[];
}

/**
 * PPT 生成选项（对应后端 /api/generate-ppt 入参）
 */
export interface PPTGenerateOptions {
  include_flaws?: boolean;
  include_compare?: boolean;
}

/**
 * 章节拆分事件章节（来自 SSE chapters_detected）
 */
export interface ChapterInfo {
  name: string;
  page_start: number;
  page_end: number;
}

/**
 * AnalysisView 组件 props（ai-analysis-panel.tsx 内部使用）
 * - progress: 可选，仅 breakdown Tab 用 SSE 进度；innovation/flaws 不需要
 * - hasResult: 可选（F7），为 true 时按钮文案变"重新分析"，调用方在 onAnalyze 里带 force 重跑
 * - onCancel:   可选，仅 breakdown SSE 进度 note 显示「取消」按钮（store.cancelAnalysis）
 * - costHint:   可选，空态 note 的耗时提示文案（如「需要 约 10–25 秒」）
 * - runLabel:   可选，空态按钮文案（默认「开始分析」；对比 Tab 用「联网对比」）
 * - emptyLabel: 可选，空态标题短名（如「拆解」→「拆解还没做」）
 * - rerunLabel: 可选，结果态紧凑头的重跑按钮文案（默认「重新分析」）
 * - progressTitle: 可选，进度 note 标题（默认按是否流式取「正在拆解」/「分析中」）
 */
export interface AnalysisViewProps {
  children?: React.ReactNode;
  title: string;
  description: string;
  analyzing: boolean;
  onAnalyze: () => void;
  error: string | null;
  disabled: boolean;
  hasResult?: boolean;
  progress?: import("@/stores/paper-store").StreamProgress | null;
  onCancel?: () => void;
  costHint?: string;
  runLabel?: string;
  emptyLabel?: string;
  rerunLabel?: string;
  progressTitle?: string;
}

// ===== 设置（网页端供应商配置，GET/PUT /api/settings） =====

export interface LLMSettingsView {
  base_url: string;
  model: string;
  api_key_configured: boolean;
  api_key_masked: string | null;
  max_tokens: number;
  reasoning_split: boolean;
  reasoning_effort: string;
  source: { api_key: string; base_url: string; model: string };
}

export interface SearchSettingsView {
  provider: "arxiv" | "tavily";
  tavily_base_url: string;
  tavily_api_key_configured: boolean;
  tavily_api_key_masked: string | null;
  source: { provider: string; tavily_api_key: string };
}

export interface SettingsView {
  llm: LLMSettingsView;
  search: SearchSettingsView;
}

export interface SettingsTestResultItem {
  ok: boolean;
  message: string;
}

export interface SettingsTestResult {
  llm?: SettingsTestResultItem;
  search?: SettingsTestResultItem;
}

/** PUT 载荷：字段级覆盖；api_key 留空 = 保持已保存值不变 */
export interface SettingsUpdatePayload {
  llm?: {
    api_key?: string;
    base_url?: string;
    model?: string;
  };
  search?: {
    provider?: "arxiv" | "tavily";
    tavily_api_key?: string;
    tavily_base_url?: string;
  };
  reset_llm?: boolean;
  reset_search?: boolean;
}

export interface SettingsTestPayload {
  llm?: {
    api_key?: string;
    base_url?: string;
    model?: string;
  };
  search?: boolean;
}
