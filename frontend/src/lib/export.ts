// 分析结果导出（Markdown 下载，纯前端实现，无需后端接口）
// W1-01 §2.2 顶栏「导出」：把当前论文的拆解/创新/漏洞/对比结果导出为 Markdown

import type { BreakdownResult, InnovationResult, FlawsResult, CompareResponse } from "@/types";

export interface ExportAnalysisParams {
  title: string;
  filename?: string;
  breakdown?: BreakdownResult;
  innovation?: InnovationResult;
  flaws?: FlawsResult;
  compare?: CompareResponse;
}

function section(title: string): string {
  return `\n## ${title}\n`;
}

/**
 * F16: 判断四个分析结果是否全为空（导出前的守卫用，单独导出便于单测）。
 * 参数用 Partial：调用方（top-bar）手里是 store 的 Partial<PaperResults>，没有 title。
 * 空 compare（4001 未搜到相关工作的空壳结果）不算"有结果"——否则会导出只有标题的报告。
 */
export function hasAnyAnalysisResult(p: Partial<ExportAnalysisParams>): boolean {
  const hasRealCompare = !!(
    p.compare && p.compare.related_papers && p.compare.related_papers.length > 0
  );
  return !!(p.breakdown || p.innovation || p.flaws || hasRealCompare);
}

/** Markdown 表格单元格转义："|" 转义成 "\|"；换行替换为空格（Markdown 表格单元格不允许换行） */
function escapeTableCell(text: string): string {
  return text.replace(/\|/g, "\\|").replace(/\r\n|\r|\n/g, " ");
}

function quoteBlock(q: { section?: string; text?: string; page?: number }): string {
  const page = q.page ? ` [P${q.page}]` : "";
  return `- (${q.section || "原文"}${page}) ${q.text || ""}`;
}

/** 组装 Markdown 文本（纯函数，便于单测） */
export function buildAnalysisMarkdown(p: ExportAnalysisParams): string {
  const lines: string[] = [`# ${p.title} — AI 分析报告`, "", "> 由 PaperPilot 生成 · AI 辅助阅读，请以原文为准", ""];

  if (p.breakdown) {
    lines.push(section("五段拆解"));
    const b = p.breakdown;
    if (b.summary) lines.push("**摘要**", b.summary, "");
    if (b.background) lines.push("**背景**", b.background, "");
    if (b.goal) lines.push("**目标**", b.goal, "");
    if (b.method) lines.push("**方法**", b.method, "");
    if (b.experiment) lines.push("**实验**", b.experiment, "");
    if (b.conclusion) lines.push("**结论**", b.conclusion, "");
    if (b.key_points?.length) {
      lines.push("**核心要点**");
      b.key_points.forEach((k) => lines.push(`- ${k}`));
      lines.push("");
    }
    if (b.quotes?.length) {
      lines.push("**原文引用**");
      b.quotes.forEach((q) => lines.push(quoteBlock(q)));
      lines.push("");
    }
  }

  if (p.innovation) {
    lines.push(section("创新点分析"));
    const i = p.innovation;
    if (i.innovation_level) lines.push(`**创新等级**：${i.innovation_level}`, "");
    if (i.level_reasoning) lines.push(`**等级依据**：${i.level_reasoning}`, "");
    i.core_innovations?.forEach((c, idx) => {
      lines.push(`### ${idx + 1}. ${c.title}`, "", c.description, "");
      if (c.evidence) lines.push(`证据：${c.evidence}`, "");
    });
    if (i.applicable_scenarios?.length) {
      lines.push("**适用场景**");
      i.applicable_scenarios.forEach((s) => lines.push(`- ${s}`));
      lines.push("");
    }
  }

  if (p.flaws) {
    lines.push(section("局限性分析"));
    const f = p.flaws;
    for (const [level, label] of [
      ["method_level", "方法层面"],
      ["experiment_level", "实验层面"],
      ["writing_level", "写作层面"],
    ] as const) {
      const items = f[level] || [];
      if (items.length) {
        lines.push(`**${label}**`);
        items.forEach((it) => lines.push(`- ${it.description}${it.severity ? `（${it.severity}）` : ""}`));
        lines.push("");
      }
    }
    if (f.improvements?.length) {
      lines.push("**改进建议**");
      f.improvements.forEach((imp) => lines.push(`- ${imp.suggestion}`));
      lines.push("");
    }
    if (f.overall_assessment) lines.push(`**整体评价**：${f.overall_assessment}`, "");
  }

  if (p.compare) {
    lines.push(section("相关工作对比"));
    const c = p.compare;
    if (c.compare_table?.length) {
      c.compare_table.forEach((row, i) => {
        // F16: 单元格内的 "|" 转义为 "\|"，否则会把一个单元格拆成两列
        lines.push(`| ${row.map(escapeTableCell).join(" | ")} |`);
        if (i === 0) lines.push(`| ${row.map(() => "---").join(" | ")} |`);
      });
      lines.push("");
    }
    if (c.summary) lines.push(`**对比总结**：${c.summary}`, "");
    if (c.main_advantages?.length) {
      lines.push("**主论文优势**");
      c.main_advantages.forEach((a) => lines.push(`- ${a}`));
      lines.push("");
    }
    if (c.main_disadvantages?.length) {
      lines.push("**主论文劣势**");
      c.main_disadvantages.forEach((a) => lines.push(`- ${a}`));
      lines.push("");
    }
  }

  return lines.join("\n");
}

/** 导出为 .md 文件下载 */
export function downloadMarkdown(params: ExportAnalysisParams): void {
  const md = buildAnalysisMarkdown(params);
  const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${(params.title || "paper").replace(/[\\/:*?"<>|\s]+/g, "_").slice(0, 60)}-分析报告.md`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
