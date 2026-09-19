/**
 * 快捷键纯函数测试（B1：←/→ 翻页、1-5 切 Tab，input 内忽略）
 */
import { describe, it, expect, vi } from "vitest";
import { handleShortcutKey, shouldIgnoreShortcut, TAB_KEYS } from "@/hooks/use-keyboard-shortcuts";

function makeEvent(
  key: string,
  target: unknown = document.body,
  mods: { altKey?: boolean; ctrlKey?: boolean; metaKey?: boolean } = {}
): KeyboardEvent {
  return { key, target, preventDefault: vi.fn(), altKey: false, ctrlKey: false, metaKey: false, ...mods } as unknown as KeyboardEvent;
}

function makeDispatch() {
  return vi.fn();
}

describe("handleShortcutKey", () => {
  it("ArrowLeft dispatches prev-page and prevents default", () => {
    const e = makeEvent("ArrowLeft");
    const dispatch = makeDispatch();
    const consumed = handleShortcutKey(e, dispatch);
    expect(consumed).toBe(true);
    expect(dispatch).toHaveBeenCalledWith("paperpilot:prev-page", {});
    expect(e.preventDefault).toHaveBeenCalled();
  });

  it("ArrowRight dispatches next-page", () => {
    const e = makeEvent("ArrowRight");
    const dispatch = makeDispatch();
    expect(handleShortcutKey(e, dispatch)).toBe(true);
    expect(dispatch).toHaveBeenCalledWith("paperpilot:next-page", {});
  });

  it.each(["1", "2", "3", "4", "5"])("key %s switches to tab %s", (key) => {
    const e = makeEvent(key);
    const dispatch = makeDispatch();
    expect(handleShortcutKey(e, dispatch)).toBe(true);
    expect(dispatch).toHaveBeenCalledWith("paperpilot:set-tab", { tab: TAB_KEYS[Number(key) - 1] });
  });

  it("ignores keys inside input elements (typing)", () => {
    const input = document.createElement("input");
    const e = makeEvent("1", input);
    const dispatch = makeDispatch();
    expect(handleShortcutKey(e, dispatch)).toBe(false);
    expect(dispatch).not.toHaveBeenCalled();
  });

  it("ignores keys inside contentEditable", () => {
    const editable = document.createElement("div");
    // jsdom 中 contentEditable 属性赋值不会写 attribute，用 setAttribute（与生产检测一致）
    editable.setAttribute("contenteditable", "true");
    document.body.appendChild(editable);
    try {
      const e = makeEvent("ArrowLeft", editable);
      const dispatch = makeDispatch();
      expect(handleShortcutKey(e, dispatch)).toBe(false);
    } finally {
      document.body.removeChild(editable);
    }
  });

  it("ignores unrelated keys", () => {
    const e = makeEvent("Escape");
    const dispatch = makeDispatch();
    expect(handleShortcutKey(e, dispatch)).toBe(false);
    expect(dispatch).not.toHaveBeenCalled();
  });

  it("ignores keys 6-9 and 0", () => {
    for (const key of ["0", "6", "7", "8", "9"]) {
      const e = makeEvent(key);
      expect(handleShortcutKey(e, makeDispatch())).toBe(false);
    }
  });

  // F12: 修饰键组合不劫持（Alt+← 浏览器后退、Ctrl/Cmd+数字系统快捷键）
  it("ignores Alt+Arrow (浏览器历史后退)", () => {
    const e = makeEvent("ArrowLeft", document.body, { altKey: true });
    const dispatch = makeDispatch();
    expect(handleShortcutKey(e, dispatch)).toBe(false);
    expect(dispatch).not.toHaveBeenCalled();
    expect(e.preventDefault).not.toHaveBeenCalled();
  });

  it("ignores Ctrl+1~5", () => {
    for (const key of ["1", "2", "3", "4", "5"]) {
      const e = makeEvent(key, document.body, { ctrlKey: true });
      expect(handleShortcutKey(e, makeDispatch())).toBe(false);
    }
  });

  it("ignores Meta+Arrow (Cmd)" , () => {
    const e = makeEvent("ArrowRight", document.body, { metaKey: true });
    expect(handleShortcutKey(e, makeDispatch())).toBe(false);
  });
});

describe("shouldIgnoreShortcut", () => {
  it("ignores input/textarea/select", () => {
    expect(shouldIgnoreShortcut(document.createElement("input"))).toBe(true);
    expect(shouldIgnoreShortcut(document.createElement("textarea"))).toBe(true);
    expect(shouldIgnoreShortcut(document.createElement("select"))).toBe(true);
  });

  it("does not ignore body/div", () => {
    expect(shouldIgnoreShortcut(document.body)).toBe(false);
    expect(shouldIgnoreShortcut(document.createElement("div"))).toBe(false);
  });

  it("ignores role=separator (分割条自身用方向键调宽度)", () => {
    const separator = document.createElement("div");
    separator.setAttribute("role", "separator");
    expect(shouldIgnoreShortcut(separator)).toBe(true);
  });
});
