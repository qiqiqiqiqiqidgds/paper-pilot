"use client";
import { create } from "zustand";
import { useEffect } from "react";
import { Menu, X } from "lucide-react";
import { Button } from "./ui/button";
import { cn } from "@/lib/utils";

/**
 * 移动端侧栏开关（P2-10）
 *
 * - < lg (<1024px)：侧栏默认隐藏，通过顶栏按钮打开为全屏抽屉
 * - >= lg：按钮自动隐藏，原有侧栏照常显示
 *
 * 用一个轻量 store 跨组件共享"哪个侧栏打开"。
 */

type SidebarId = "left" | "right" | null;

interface MobileSidebarState {
  open: SidebarId;
  toggle: (id: "left" | "right") => void;
  close: () => void;
}

export const useMobileSidebar = create<MobileSidebarState>((set) => ({
  open: null,
  toggle: (id) => set((s) => ({ open: s.open === id ? null : id })),
  close: () => set({ open: null }),
}));

interface MobileToggleProps {
  side: "left" | "right";
  label: string;
}

export function MobileToggle({ side, label }: MobileToggleProps) {
  const open = useMobileSidebar((s) => s.open);
  const toggle = useMobileSidebar((s) => s.toggle);
  const isOpen = open === side;

  return (
    <Button
      size="sm"
      variant="ghost"
      className="lg:hidden"
      onClick={() => toggle(side)}
      aria-expanded={isOpen}
      aria-controls={`mobile-${side}-panel`}
      aria-label={isOpen ? `关闭${label}` : `打开${label}`}
    >
      {isOpen ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
    </Button>
  );
}

/**
 * 移动端侧栏容器包装：单一容器 + 响应式类，children 只实例化一份。
 *
 * - 桌面（>= lg）：静态参与 flex 布局，正常显示
 * - 移动（< lg）：侧栏默认隐藏，打开时变为全屏抽屉（fixed）
 * - children 始终只挂载一次，桌面/移动共享同一份 state，toast 只弹一次
 *
 * 用法：<MobilePanel side="left">...</MobilePanel>
 */
interface MobilePanelProps {
  side: "left" | "right";
  children: React.ReactNode;
  /**
   * 桌面端（>= lg）宽度 CSS 值（如 "480px" / "50%"）。
   * 不传时用默认值：左侧 w-60（240px，与设计稿 .rail 一致）、右侧 w-[480px]。
   * 右侧面板配合 ResizeHandle 实现可拖拽分割条（W1-01 §2.5）。
   */
  desktopWidth?: string;
}

export function MobilePanel({ side, children, desktopWidth }: MobilePanelProps) {
  const open = useMobileSidebar((s) => s.open);
  const close = useMobileSidebar((s) => s.close);
  const isOpen = open === side;
  const isLeft = side === "left";

  // ESC 关闭
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [isOpen, close]);

  return (
    <>
      {/* 单一实例：桌面静态，移动端抽屉；[&>*]:w-full 让子组件填满容器（抽屉 100vw / 桌面自定义宽度） */}
      <div
        id={`mobile-${side}-panel`}
        style={desktopWidth ? ({ "--desktop-width": desktopWidth } as React.CSSProperties) : undefined}
        className={cn(
          "shrink-0 lg:flex lg:flex-col lg:static lg:inset-auto lg:z-auto [&>*]:w-full",
          isLeft ? "lg:w-60" : desktopWidth ? "lg:w-[var(--desktop-width)]" : "lg:w-[480px]",
          isOpen ? "fixed inset-0 z-40 flex flex-col bg-background" : "hidden"
        )}
      >
        {children}
      </div>
      {/* 移动端遮罩（半透明背景，关闭抽屉） */}
      {isOpen && (
        <div
          className="lg:hidden fixed inset-0 z-30 bg-black/40"
          onClick={close}
          aria-hidden="true"
        />
      )}
    </>
  );
}