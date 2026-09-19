/**
 * 分析报告导出（Markdown）纯函数测试（C4）
 */
import { describe, it, expect } from "vitest";
import { buildAnalysisMarkdown, hasAnyAnalysisResult } from "@/lib/export";

describe("buildAnalysisMarkdown", () => {
  it("renders breakdown sections with quotes and page refs", () => {
    const md = buildAnalysisMarkdown({
      title: "Attention Is All You Need",
      breakdown: {
        summary: "基于纯注意力的架构",
        background: "RNN 并行性差",
        goal: "提升并行度",
        method: "多头注意力",
        experiment: "28.4 BLEU",
        conclusion: "优于 RNN",
        key_points: ["纯注意力", "高并行"],
        quotes: [{ section: "Abstract", text: "Attention is all you need.", page: 1 }],
      },
    });
    expect(md).toContain("# Attention Is All You Need");
    expect(md).toContain("## 五段拆解");
    expect(md).toContain("**方法**");
    expect(md).toContain("**核心要点**");
    expect(md).toContain("- 纯注意力");
    expect(md).toContain("(Abstract [P1]) Attention is all you need.");
  });

  it("renders innovation with level and scenarios", () => {
    const md = buildAnalysisMarkdown({
      title: "T",
      innovation: {
        core_innovations: [{ title: "多头注意力", description: "并行子空间", evidence: "[P4]", page_ref: 4 }],
        innovation_level: "disruptive",
        level_reasoning: "新范式",
        applicable_scenarios: ["翻译", "摘要"],
        quotes: [],
      },
    });
    expect(md).toContain("**创新等级**：disruptive");
    expect(md).toContain("### 1. 多头注意力");
    expect(md).toContain("**适用场景**");
  });

  it("renders flaws with three levels and improvements", () => {
    const md = buildAnalysisMarkdown({
      title: "T",
      flaws: {
        method_level: [{ description: "O(n²)", evidence: "[P5]", page_ref: 5, severity: "major" }],
        experiment_level: [],
        writing_level: [],
        improvements: [{ flaw_ref: 0, suggestion: "用稀疏注意力", feasibility: "high" }],
        overall_assessment: "贡献突出",
        quotes: [],
      },
    });
    expect(md).toContain("## 局限性分析");
    expect(md).toContain("**方法层面**");
    expect(md).toContain("O(n²)（major）");
    expect(md).toContain("- 用稀疏注意力");
    expect(md).toContain("**整体评价**：贡献突出");
  });

  it("renders compare table as markdown table", () => {
    const md = buildAnalysisMarkdown({
      title: "T",
      compare: {
        main_paper: { title: "M", year: 2017 },
        related_papers: [],
        compare_table: [["维度", "主论文"], ["方法", "Transformer"]],
        summary: "总体对比",
        main_advantages: ["高效"],
        main_disadvantages: ["O(n²)"],
      },
    });
    expect(md).toContain("| 维度 | 主论文 |");
    expect(md).toContain("| --- | --- |");
    expect(md).toContain("**主论文优势**");
    expect(md).toContain("**主论文劣势**");
  });

  it("handles empty params gracefully", () => {
    const md = buildAnalysisMarkdown({ title: "Empty" });
    expect(md).toContain("# Empty");
    expect(md).not.toContain("## 五段拆解");
  });

  // F16: 对比表单元格内的 "|" 转义为 "\|"，否则会破坏 Markdown 表格结构
  it("escapes pipes inside compare table cells", () => {
    const md = buildAnalysisMarkdown({
      title: "T",
      compare: {
        related_papers: [],
        compare_table: [["维度", "主论文"], ["效果", "A | B"]],
      },
    });
    expect(md).toContain("| 效果 | A \\| B |");
    // 每行单元格数量不因 "|" 被拆多
    expect(md).not.toContain("| 效果 | A | B |");
  });

  // F16: 四个结果全为空时导出守卫返回 false（top-bar 据此 toast「请先运行分析」并 return）
  describe("hasAnyAnalysisResult", () => {
    it("returns false when all four results are empty", () => {
      expect(hasAnyAnalysisResult({ title: "T" })).toBe(false);
      expect(hasAnyAnalysisResult({ title: "T", breakdown: undefined, innovation: undefined, flaws: undefined, compare: undefined })).toBe(false);
    });

    it("returns true when any result exists", () => {
      expect(hasAnyAnalysisResult({ title: "T", breakdown: { summary: "x" } as never })).toBe(true);
      expect(hasAnyAnalysisResult({ title: "T", innovation: {} as never })).toBe(true);
      expect(hasAnyAnalysisResult({ title: "T", flaws: {} as never })).toBe(true);
      // 有相关论文的 compare 才算"有结果"
      const compare = { related_papers: [{ title: "BERT" }] };
      expect(hasAnyAnalysisResult({ title: "T", compare })).toBe(true);
    });

    it("空 compare（4001 未搜到相关工作的空壳）不算有结果", () => {
      // 修复前：仅 compare(空) 存在时会导出只有标题 + 空"相关工作对比"节的报告
      const emptyCompare = { related_papers: [] };
      expect(hasAnyAnalysisResult({ title: "T", compare: emptyCompare })).toBe(false);
      expect(hasAnyAnalysisResult({ title: "T", compare: {} as never })).toBe(false);
    });
  });
});
