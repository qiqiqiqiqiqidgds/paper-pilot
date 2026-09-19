"use client";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";
import { UploadButton } from "./upload-button";
import { Button } from "./ui/button";
import { ConnStatus } from "./conn-status";
import { Presentation, Download, Sun, Moon, Upload, Settings } from "lucide-react";
import { MobileToggle, useMobileSidebar } from "./mobile-toggle";
import { useSettingsStore } from "@/stores/settings-store";
import { usePaperStore } from "@/stores/paper-store";
import { downloadMarkdown, hasAnyAnalysisResult } from "@/lib/export";
import { useIsMobile } from "@/hooks/use-is-mobile";
import { toast } from "sonner";
import type { PaperInfo } from "@/types";

interface Props {
  onUploaded: (paper: PaperInfo) => void;
}

export function TopBar({ onUploaded }: Props) {
  const isMobile = useIsMobile();
  const currentPaperId = usePaperStore((s) => s.currentPaperId);
  const papers = usePaperStore((s) => s.papers);
  const results = usePaperStore((s) => s.results);

  // 暗色模式：主题切换（next-themes，避免 hydration mismatch 用 mounted 守卫）
  // F13: 用 resolvedTheme 判断——defaultTheme="system" 时 theme === "system"，
  // 用 theme 判断会导致系统暗色用户点第一次只切到 "light"（仍是暗色），要连点两次才变亮
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const isDark = resolvedTheme === "dark";
  const toggleTheme = () => setTheme(isDark ? "light" : "dark");

  // 顶栏「PPT」：切到 PPT 书签带（不自动触发生成，用户自己勾选内容）
  const handleQuickPPT = () => {
    if (!currentPaperId) {
      toast.info("请先选择一篇论文");
      return;
    }
    // F19: 移动端（<lg）抽屉覆盖整个页面，切换书签带发生在被遮挡的面板上，先关抽屉
    if (isMobile) {
      useMobileSidebar.getState().close();
    }
    window.dispatchEvent(new CustomEvent("paperpilot:set-tab", { detail: { tab: "ppt" } }));
  };

  // 顶栏「导出」：当前论文分析结果导出为 Markdown（纯前端）
  const handleExport = () => {
    if (!currentPaperId) {
      toast.info("请先选择一篇论文");
      return;
    }
    const paper = papers.find((p) => p.paper_id === currentPaperId);
    const cur = results[currentPaperId] || {};
    // F16: 四个结果全为空时不产出空报告，直接提示先分析
    if (!hasAnyAnalysisResult(cur)) {
      toast.error("请先运行分析");
      return;
    }
    downloadMarkdown({
      title: paper?.title || "论文",
      filename: paper?.filename,
      breakdown: cur.breakdown,
      innovation: cur.innovation,
      flaws: cur.flaws,
      compare: cur.compare,
    });
    toast.success("已导出分析报告（Markdown）");
  };

  const currentPaper = papers.find((p) => p.paper_id === currentPaperId);

  return (
    <header
      className="h-[46px] border-b flex items-center justify-between px-4 bg-background shrink-0"
      role="banner"
      aria-label="顶部导航栏"
    >
      <div className="flex items-center gap-2 min-w-0">
        {/* P2-10: 移动端左侧栏切换按钮 */}
        <MobileToggle side="left" label="论文库" />
        {/* 品牌标：纸页 + 朱砂书签角 */}
        <svg viewBox="0 0 24 24" className="h-[22px] w-[22px] shrink-0" fill="none" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <rect x="4.5" y="3" width="15" height="18" rx="2" stroke="currentColor" strokeWidth="1.75" className="text-foreground" />
          <path d="M9.5 3v7.2l2.5-1.9 2.5 1.9V3" stroke="hsl(var(--cinnabar))" strokeWidth="1.75" />
          <line x1="8" y1="14.5" x2="16" y2="14.5" stroke="hsl(var(--cinnabar))" strokeWidth="1.75" opacity=".45" />
        </svg>
        <h1 className="font-display font-semibold text-[15px] tracking-[0.3px] truncate">PaperPilot</h1>
        <span className="font-display text-[13px] text-muted-foreground hidden md:inline truncate border-l border-[hsl(var(--border-strong))] pl-3.5 ml-1">
          正在读 · <b className="text-ink2 font-semibold">{currentPaper?.title || "书架上还没有摊开的书"}</b>
        </span>
      </div>

      <div className="flex items-center gap-1.5 shrink-0">
        {/* 连接状态：图标 + 悬浮面板 */}
        <ConnStatus />
        {/* API 供应商设置（LLM / 搜索，网页端可配） */}
        <Button
          size="icon"
          variant="ghost"
          onClick={() => useSettingsStore.getState().setOpen(true)}
          aria-label="设置 API 供应商"
          title="设置（API 供应商）"
        >
          <Settings className="h-[15px] w-[15px]" aria-hidden="true" />
        </Button>
        {/* 暗色模式开关 */}
        {mounted && (
          <Button
            size="icon"
            variant="ghost"
            onClick={toggleTheme}
            aria-label={isDark ? "切换到亮色模式" : "切换到暗色模式"}
            title={isDark ? "亮色模式" : "暗色模式"}
          >
            {isDark ? <Sun className="h-[15px] w-[15px]" /> : <Moon className="h-[15px] w-[15px]" />}
          </Button>
        )}
        {/* PPT（跳转 PPT 书签带；设计稿为 icon-only）。
            P2-视觉：小屏隐藏顶栏快捷入口（书签带已有 PPT tab 可达），
            为新增的设置按钮腾出顶栏空间，避免移动端图标拥挤 */}
        <Button size="icon" variant="ghost" onClick={handleQuickPPT} aria-label="生成 PPT" title="生成 PPT" className="hidden sm:inline-flex">
          <Presentation className="h-[15px] w-[15px]" aria-hidden="true" />
        </Button>
        {/* 导出分析报告（Markdown；设计稿未含此按钮，功能保留改 icon-only） */}
        <Button size="icon" variant="ghost" onClick={handleExport} aria-label="导出分析报告" title="导出分析报告（Markdown）">
          <Download className="h-[15px] w-[15px]" aria-hidden="true" />
        </Button>
        <UploadButton onUploaded={onUploaded}>
          <Button size="default" variant="default" aria-label="上传 PDF 或 Word 文件">
            <Upload className="h-3.5 w-3.5" aria-hidden="true" />
            <span>上传</span>
          </Button>
        </UploadButton>
        {/* P2-10: 移动端右侧栏切换按钮 */}
        <MobileToggle side="right" label="AI 分析面板" />
      </div>
    </header>
  );
}
