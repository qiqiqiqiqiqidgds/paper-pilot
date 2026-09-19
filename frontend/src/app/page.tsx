"use client";
// lib/pdf 顶层 import 仅做"模块登记"，不再有副作用：react-pdf 已在 lib/pdf 内
// 改为 dynamic import 懒加载，浏览器侧 useEffect 内 initPdfJs() 完成 workerSrc 覆盖。
// 任何使用 PDF 渲染的组件挂载前必须 await initPdfJs()（见 pdf-viewer.tsx）。
import "@/lib/pdf";
import { useEffect } from "react";
import dynamic from "next/dynamic";
import { TopBar } from "@/components/top-bar";
import { FileSidebar } from "@/components/file-sidebar";
import { AIAnalysisPanel } from "@/components/ai-analysis-panel";
import { ErrorBoundary } from "@/components/error-boundary";
import { MobilePanel, useMobileSidebar } from "@/components/mobile-toggle";
import { SettingsDialog } from "@/components/settings-dialog";
import { usePaperStore } from "@/stores/paper-store";
import { useKeyboardShortcuts } from "@/hooks/use-keyboard-shortcuts";
import { useIsMobile } from "@/hooks/use-is-mobile";

const PDFViewer = dynamic(
  () => import("@/components/pdf-viewer").then((m) => m.PDFViewer),
  { ssr: false, loading: () => <div className="flex-1 flex items-center justify-center text-muted-foreground">加载 PDF 渲染器…</div> }
);

export default function HomePage() {
  // 细粒度订阅：避免翻页/缩放等高频 store 更新触发整个页面重渲染
  const papers = usePaperStore((s) => s.papers);
  const currentPaperId = usePaperStore((s) => s.currentPaperId);
  const fetchPapers = usePaperStore((s) => s.fetchPapers);
  const setCurrentPaper = usePaperStore((s) => s.setCurrentPaper);
  // 移动端（<lg）判定：跳转分发前关抽屉用（原为手写 window.innerWidth < 1024，P3 收敛到 hook）
  const isMobile = useIsMobile();

  useEffect(() => {
    fetchPapers();
  }, [fetchPapers]);

  // 全局快捷键：←/→ 翻页、1-5 切书签带
  useKeyboardShortcuts();

  return (
    // P2-10: h-[100dvh] 适配移动浏览器地址栏
    <div className="h-[100dvh] flex flex-col">
      <TopBar onUploaded={async (p) => {
        // 解析完成自动定位到摘要页（第 1 页）
        await setCurrentPaper(p.paper_id);
        window.dispatchEvent(new CustomEvent("paperpilot:jump-to-pdf", { detail: { page: 1 } }));
      }} />

      {/* API 供应商设置对话框（全局挂载，顶栏齿轮唤起） */}
      <SettingsDialog />

      {/* 批注手稿三区：左侧论文架 | 书桌（纸页） | 边批列（固定宽） */}
      <div className="flex-1 flex overflow-hidden relative">
        {/* 左侧论文架 —— 移动端变抽屉 */}
        <ErrorBoundary>
          <MobilePanel side="left">
            <FileSidebar
              papers={papers}
              currentId={currentPaperId}
              onSelect={setCurrentPaper}
              onUploaded={async (p) => {
                await setCurrentPaper(p.paper_id);
                window.dispatchEvent(new CustomEvent("paperpilot:jump-to-pdf", { detail: { page: 1 } }));
              }}
            />
          </MobilePanel>
        </ErrorBoundary>

        {/* resetKey=论文 id：切换论文时复位错误边界（旧实现报错后永远停在错误态）。
            不能用 React key 触发重挂载：PDFViewer 经 next/dynamic 懒加载，
            keyed 重挂载会使旧 <main> 宿主节点残留为孤儿并在 DOM 中累积（P0），
            resetKey 只清错误态、不卸载子树。 */}
        <ErrorBoundary resetKey={currentPaperId ?? "no-paper"}>
          <PDFViewer />
        </ErrorBoundary>

        {/* 边批列（AI 分析）—— 移动端变抽屉，桌面固定 360px */}
        <ErrorBoundary resetKey={currentPaperId ?? "no-paper"}>
          <MobilePanel side="right" desktopWidth="360px">
            {/* 跳转分发点统一关移动抽屉：创新/漏洞/引用等各视图
                直调 onJumpToPDF 时不再各自处理——移动端抽屉全屏遮挡 PDF，
                不关抽屉的跳转对用户等于点击无反应 */}
            <AIAnalysisPanel
              onJumpToPDF={(page, text) => {
                if (isMobile) {
                  useMobileSidebar.getState().close();
                }
                window.dispatchEvent(new CustomEvent("paperpilot:jump-to-pdf", { detail: { page, text } }));
              }}
            />
          </MobilePanel>
        </ErrorBoundary>
      </div>
    </div>
  );
}
