/**
 * 工具函数单元测试（Sprint 4 / R3 示范用例）
 * - 选最简的纯函数（cn + formatTime）作为示范
 * - 不依赖 React 组件 / jsdom 细节
 * - 验证 vitest + @testing-library/jest-dom + @/ alias 全链路工作
 */
import { describe, it, expect } from "vitest";
import { cn, formatTime } from "@/lib/utils";

describe("cn", () => {
  it("merges multiple class strings", () => {
    expect(cn("foo", "bar")).toBe("foo bar");
  });

  it("filters out falsy values", () => {
    // clsx 会过滤 false / null / undefined
    expect(cn("a", false && "b", null, undefined, 0, "c")).toBe("a c");
  });

  it("deduplicates tailwind conflicts via twMerge", () => {
    // twMerge 让后面的 class 覆盖前面的同属性 class
    expect(cn("p-2", "p-4")).toBe("p-4");
    expect(cn("text-red-500", "text-blue-500")).toBe("text-blue-500");
  });

  it("accepts arrays and objects (clsx syntax)", () => {
    expect(cn(["a", "b"], { c: true, d: false })).toBe("a b c");
  });
});

describe("formatTime", () => {
  it("returns empty string for empty input", () => {
    expect(formatTime("")).toBe("");
  });

  it("formats ISO time to Chinese locale string", () => {
    const out = formatTime("2026-01-15T10:30:00");
    // zh-CN locale 输出含年份与时分
    expect(out).toContain("2026");
    // hour12: false 所以不会出现 AM/PM
    expect(out).not.toMatch(/AM|PM|上午|下午/);
  });

  it("handles invalid date gracefully (returns 'Invalid Date' string)", () => {
    // new Date("invalid") 返回 Invalid Date，toLocaleString 输出 "Invalid Date"
    // 这是显式行为，不抛错（避免 try/catch 噪音）
    const out = formatTime("not-a-date");
    expect(out).toBe("Invalid Date");
  });
});
