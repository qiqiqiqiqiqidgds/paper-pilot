/**
 * 拆解五段 ↔ 原文引用 对照匹配测试
 */
import { describe, expect, it } from "vitest";
import { matchQuotesForSection } from "@/lib/section-quotes";

const QUOTES = [
  { section: "Abstract", text: "We propose Transformer.", page: 1 },
  { section: "1 Introduction", text: "RNNs suffer from sequential computation.", page: 2 },
  { section: "Method", text: "We use multi-head self-attention.", page: 3 },
  { section: "Experiments", text: "Our model achieves 28.4 BLEU.", page: 4 },
  { section: "Conclusion", text: "The first transduction model based on attention.", page: 5 },
  { section: "Discussion", text: "Future work directions.", page: 6 },
];

describe("matchQuotesForSection", () => {
  it("summary 匹配 Abstract 章节引用", () => {
    const matched = matchQuotesForSection(QUOTES, "summary");
    expect(matched).toHaveLength(1);
    expect(matched[0].section).toBe("Abstract");
  });

  it("background 匹配 Introduction/Related Work", () => {
    const matched = matchQuotesForSection(QUOTES, "background");
    expect(matched.some((q) => q.section === "1 Introduction")).toBe(true);
  });

  it("method 匹配 Method 章节引用", () => {
    const matched = matchQuotesForSection(QUOTES, "method");
    expect(matched.some((q) => q.section === "Method")).toBe(true);
  });

  it("experiment 匹配 Experiments/Results", () => {
    const matched = matchQuotesForSection(QUOTES, "experiment");
    expect(matched.some((q) => q.section === "Experiments")).toBe(true);
  });

  it("conclusion 匹配 Conclusion/Discussion", () => {
    const matched = matchQuotesForSection(QUOTES, "conclusion");
    expect(matched.length).toBeGreaterThanOrEqual(2);
  });

  it("中文 section 名也能匹配", () => {
    const zhQuotes = [
      { section: "摘要", text: "中文摘要引用", page: 1 },
      { section: "方法", text: "中文方法引用", page: 3 },
      { section: "结论", text: "中文结论引用", page: 5 },
    ];
    expect(matchQuotesForSection(zhQuotes, "summary")).toHaveLength(1);
    expect(matchQuotesForSection(zhQuotes, "method")).toHaveLength(1);
    expect(matchQuotesForSection(zhQuotes, "conclusion")).toHaveLength(1);
  });

  it("无匹配或空输入返回空数组", () => {
    expect(matchQuotesForSection([], "method")).toEqual([]);
    expect(matchQuotesForSection([{ section: "References", text: "x", page: 8 }], "method")).toEqual([]);
    expect(matchQuotesForSection(QUOTES, "unknown_section")).toEqual([]);
  });
});
