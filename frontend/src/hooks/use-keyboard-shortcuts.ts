"use client";
/**
 * 全局快捷键（USER_GUIDE 六：PDF 区域聚焦时 ←/→ 翻页、1-5 切 Tab）
 *
 * 实现方式：page.tsx 挂一个 window keydown 监听，把按键翻译成既有的事件驱动
 * 通道（与 paperpilot:jump-to-pdf / paperpilot:show-compare 同风格）：
 *   - ArrowLeft / ArrowRight → paperpilot:prev-page / paperpilot:next-page（PDFViewer 监听）
 *   - 1-5                     → paperpilot:set-tab（AIAnalysisPanel 监听）
 * handler 是导出纯函数（handleShortcutKey），便于 vitest 直接测。
 */
import { useEffect } from "react";

export const TAB_KEYS = ["breakdown", "innovation", "compare", "flaws", "ppt"] as const;

/** 是否应忽略本次按键（在输入框/可编辑区域内输入时不应触发快捷键） */
export function shouldIgnoreShortcut(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName.toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select") return true;
  // isContentEditable 部分环境（jsdom/旧浏览器）不实现，双保险查 attribute
  if (target.isContentEditable || target.getAttribute?.("contenteditable") === "true") return true;
  // 分割条自身用 ←/→ 调宽度（resizable-pane.tsx），全局翻页快捷键不应再响应
  if (target.getAttribute?.("role") === "separator") return true;
  return false;
}

/**
 * 处理单个快捷键。返回 true 表示按键已被消费。
 * 抽成纯函数：dispatch 注入，便于单测断言。
 */
export function handleShortcutKey(
  e: Pick<KeyboardEvent, "key" | "target" | "preventDefault" | "altKey" | "ctrlKey" | "metaKey">,
  dispatch: (eventName: string, detail: unknown) => void
): boolean {
  // F12: 修饰键组合不劫持——Alt+← 是浏览器历史后退、Ctrl/Cmd+数字是浏览器/系统快捷键
  if (e.altKey || e.ctrlKey || e.metaKey) return false;

  if (shouldIgnoreShortcut(e.target)) return false;

  if (e.key === "ArrowLeft") {
    e.preventDefault();
    dispatch("paperpilot:prev-page", {});
    return true;
  }
  if (e.key === "ArrowRight") {
    e.preventDefault();
    dispatch("paperpilot:next-page", {});
    return true;
  }

  const num = Number(e.key);
  if (Number.isInteger(num) && num >= 1 && num <= 5) {
    e.preventDefault();
    dispatch("paperpilot:set-tab", { tab: TAB_KEYS[num - 1] });
    return true;
  }

  return false;
}

/** React hook：挂载 window keydown 监听（page.tsx 使用） */
export function useKeyboardShortcuts(): void {
  useEffect(() => {
    const dispatch = (eventName: string, detail: unknown) =>
      window.dispatchEvent(new CustomEvent(eventName, { detail }));

    const onKeyDown = (e: KeyboardEvent) => {
      handleShortcutKey(e, dispatch);
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);
}
