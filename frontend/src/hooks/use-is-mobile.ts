"use client";
/**
 * 是否处于移动端布局（< lg，即 window.innerWidth < 1024，与 Tailwind lg 断点、
 * MobilePanel 抽屉布局的切换点一致）。
 *
 * 抽取动机（P3）：top-bar.tsx / app/page.tsx / analysis-shell.tsx 三处重复手写
 * `window.innerWidth < 1024` 魔法数字，且各处都要自己加 typeof window 守卫。
 *
 * SSR 安全：初始值恒为 false（服务端无窗口，与旧代码 typeof window 守卫的
 * 桌面语义一致，也避免 hydration mismatch），挂载后用 matchMedia 监听断点
 * 变化（比 resize 事件节流更省，浏览器自动去抖），跨断点即时更新。
 */
import { useEffect, useState } from "react";

/** 与 Tailwind lg 断点一致的移动端判定阈值（px） */
const LG_BREAKPOINT_PX = 1024;

export function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${LG_BREAKPOINT_PX - 1}px)`);
    const update = () => setIsMobile(mql.matches);
    update();
    mql.addEventListener("change", update);
    return () => mql.removeEventListener("change", update);
  }, []);

  return isMobile;
}
