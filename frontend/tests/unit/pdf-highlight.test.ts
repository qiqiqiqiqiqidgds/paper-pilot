/**
 * PDF 文本高亮搜索候选生成测试（创新 Tab 跳转修复）
 * buildSearchCandidates：剥离 LLM 页码标注 + 多窗口候选，提高 text layer 匹配命中率
 */
import { describe, expect, it } from "vitest";
import { buildSearchCandidates, stripPageAnnotations } from "@/lib/highlight-candidates";

describe("stripPageAnnotations", () => {
  // F10: 剥离规则收紧——只剥离带括号的页码标注，裸 "P数字"（如 "见 P2"）不再误删。
  // 旧断言期望 "见 P2" 也被剥离（旧行为会误伤 "P2P 网络" 这类正文），已同步更新。
  it("剥离 [P3] / [P 5] / （第 2 页）标注并归一化空白（裸 P数字 保留）", () => {
    expect(stripPageAnnotations("该模型 [P3] 性能提升，见 P2 详见 （第 4 页）讨论")).toBe(
      "该模型 性能提升，见 P2 详见 讨论"
    );
  });

  it("无标注文本原样返回（归一化空白）", () => {
    expect(stripPageAnnotations("Attention Is All You Need   proposes  novel")).toBe(
      "Attention Is All You Need proposes novel"
    );
  });

  it("纯标注文本返回空串", () => {
    expect(stripPageAnnotations("[P3] [P 5] （第 2 页）")).toBe("");
  });

  // F10: 裸 P数字 是正文的一部分，不再剥离
  it("裸 P数字（P2P 网络 / P95 延迟）不被误删", () => {
    expect(stripPageAnnotations("本文提出 P2P 网络架构，P95 延迟降低 30%")).toBe(
      "本文提出 P2P 网络架构，P95 延迟降低 30%"
    );
    expect(stripPageAnnotations("见 P2 中的 P100 GPU")).toBe("见 P2 中的 P100 GPU");
  });

  it("四种括号形式的页码标注均被剥离（全角/半角）", () => {
    expect(stripPageAnnotations("方法如下 [P3] 继续")).toBe("方法如下 继续");
    expect(stripPageAnnotations("方法如下 （P3） 继续")).toBe("方法如下 继续");
    expect(stripPageAnnotations("方法如下 (P 3) 继续")).toBe("方法如下 继续");
    expect(stripPageAnnotations("方法如下 【P3】 继续")).toBe("方法如下 继续");
  });
});

describe("buildSearchCandidates", () => {
  it("剥离 [P3] 类页码标注后生成候选", () => {
    const text = "该模型在训练效率上显著提升 [P3]，并行度大幅提高";
    const candidates = buildSearchCandidates(text);
    // 剥离标注后，前 30 字符不应含 [P3]
    expect(candidates[0]).not.toContain("[P3]");
    expect(candidates[0]).toContain("该模型在训练效率上显著提升");
    // 候选非空
    expect(candidates.length).toBeGreaterThan(0);
  });

  it("剥离中文页码标注（第 X 页）", () => {
    const text = "本文提出了多头注意力机制（第 4 页），并在多个任务上验证";
    const candidates = buildSearchCandidates(text);
    expect(candidates[0]).not.toContain("（第 4 页）");
    expect(candidates[0]).toContain("本文提出了多头注意力机制");
  });

  it("生成多窗口前缀候选（30/20/12）", () => {
    const long = "Attention Is All You Need proposes a novel architecture based solely on attention mechanisms without recurrence.";
    const candidates = buildSearchCandidates(long);
    // 30 字符窗口
    expect(candidates[0].length).toBe(30);
    // 20 字符窗口
    expect(candidates).toContain("Attention Is All You Need ".slice(0, 20));
    // 12 字符窗口
    expect(candidates).toContain("Attention Is All You Need ".slice(0, 12));
  });

  it("长文本包含尾部 30 字符兜底", () => {
    const long = "X".repeat(100) + "we evaluate on WMT 2014 English to German translation task";
    const candidates = buildSearchCandidates(long);
    expect(candidates.some((c) => c.endsWith("translation task"))).toBe(true);
  });

  it("短文本（<30 字）使用全量", () => {
    const short = "注意力机制是关键";
    const candidates = buildSearchCandidates(short);
    expect(candidates).toContain("注意力机制是关键");
  });

  it("候选去重且不过短（>=5 字符）", () => {
    const candidates = buildSearchCandidates("ab ".repeat(20));
    const unique = new Set(candidates);
    expect(unique.size).toBe(candidates.length);
    for (const c of candidates) expect(c.length).toBeGreaterThanOrEqual(5);
  });

  it("空输入返回空数组", () => {
    expect(buildSearchCandidates("")).toEqual([]);
    expect(buildSearchCandidates("   ")).toEqual([]);
  });

  it("纯页码标注文本返回空数组", () => {
    expect(buildSearchCandidates("[P3] [P 5] （第 2 页）")).toEqual([]);
  });
});
