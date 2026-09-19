// 拆解五段 → 原文引用 对照匹配（纯 TS，便于单测）
// 设计文档 W1-01 §2.4：每个段落都应能对照原文。五段拆解的段落没有自己的页码，
// 但 quotes 带 section（章节名），按章节关键词把引用归组到对应段落，实现"原文对照"。

export interface QuoteLike {
  section?: string;
  text?: string;
  page?: number;
}

/** 五段 → 章节关键词（大小写不敏感，包含匹配） */
const SECTION_KEYWORDS: Record<string, string[]> = {
  summary: ["abstract", "summary", "摘要", "概述"],
  background: ["background", "introduction", "related work", "backgrounds", "背景", "引言", "相关工作", "绪论"],
  goal: ["goal", "objective", "aim", "target", "purpose", "目标", "目的"],
  method: ["method", "methodology", "approach", "model", "framework", "methods", "architecture", "方法", "模型", "框架", "架构"],
  experiment: ["experiment", "experiments", "results", "result", "evaluation", "benchmark", "ablation", "case study", "实验", "结果", "评估", "评测"],
  conclusion: ["conclusion", "conclusions", "discussion", "concluding", "limitation", "结论", "讨论", "总结"],
};

/**
 * 把 quotes 归组到指定段落（五段：summary / background / goal / method / experiment / conclusion）。
 * 匹配依据：quote.section 包含该段任一关键词（子串匹配，兼容 "1 Introduction" 等编号前缀）。
 * 注意：一条引用可能同时匹配多个段落（如 "Results and Discussion"），属预期行为；
 * 关键词按章节常用名选取，误归组概率低（如 "Experimental Setup" 含 experiment 会归入实验段）。
 */
export function matchQuotesForSection(quotes: QuoteLike[], section: string): QuoteLike[] {
  const keywords = SECTION_KEYWORDS[section] || [];
  if (keywords.length === 0) return [];
  return quotes.filter((q) => {
    const sec = (q.section || "").toLowerCase();
    return keywords.some((kw) => sec.includes(kw));
  });
}
