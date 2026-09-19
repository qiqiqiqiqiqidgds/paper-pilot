"use client";
/**
 * AI 分析面板（批注手稿 · note 体系）——右侧「边批」列
 * - 书签带渲染在纸页顶边（pdf-viewer 内 RibbonStrip），状态共享自 ui-store
 * - 本面板直接写在书桌背景上（与设计稿一致，无独立面板底色）
 * - note 连接圈落在面板左缘留白里（水平内边距由 AnalysisView 控制）
 * - 键盘 1-5 / paperpilot:set-tab 事件、多篇对比事件原样保留
 */
import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { toast } from "sonner";
import { ScrollArea } from "@/components/ui/scroll-area";
import { usePaperStore } from "@/stores/paper-store";
import { useUiStore } from "@/stores/ui-store";
import type { CompareResponse } from "@/types";
import { Note, AnalysisView, BreakdownView, InnovationView, FlawsView, CompareView, PPTView } from "./analysis";

export function AIAnalysisPanel({ onJumpToPDF }: { onJumpToPDF?: (page: number, text?: string) => void }) {
  // 细粒度订阅：避免翻页/缩放等高频 store 更新触发整个面板重渲染
  const currentPaperId = usePaperStore((s) => s.currentPaperId);
  const results = usePaperStore((s) => s.results);
  const analyzing = usePaperStore((s) => s.analyzing);
  // F11: 按类型取错误，避免 A 类边批的报错串台到 B
  const analyzeErrors = usePaperStore((s) => s.analyzeErrors);
  const streamProgress = usePaperStore((s) => s.streamProgress);
  const analyze = usePaperStore((s) => s.analyze);
  const analyzeStream = usePaperStore((s) => s.analyzeStream);
  const cancelAnalysis = usePaperStore((s) => s.cancelAnalysis);
  // 当前书签带：与纸页顶边的书签带（RibbonStrip）共享 ui-store
  const activeTab = useUiStore((s) => s.activeTab);
  const setActiveTab = useUiStore((s) => s.setActiveTab);
  const [compareResult, setCompareResult] = useState<CompareResponse | null>(null);
  const [guideDismissed, setGuideDismissed] = useState(false);

  // 当前论文的分析结果（P0-5/6：results 按 paper_id 分组）
  const currentResults = currentPaperId ? results[currentPaperId] || {} : {};

  // 监听 file-sidebar 触发的多篇对比事件
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<CompareResponse>).detail;
      setActiveTab("compare");
      setCompareResult(detail);
      // 同步写 store：externalResult 被 onConsumed 清空后，currentResults.compare
      // 保持本次最新值（否则会回退成旧的联网搜缓存，多篇结果瞬间被替换）
      usePaperStore.setState((s) => {
        const id = s.currentPaperId;
        if (!id) return {};
        return {
          results: {
            ...s.results,
            [id]: { ...(s.results[id] || {}), compare: detail },
          },
        };
      });
      toast.success("已切换到对比，查看多篇对比结果");
    };
    window.addEventListener("paperpilot:show-compare", handler);
    return () => window.removeEventListener("paperpilot:show-compare", handler);
  }, [setActiveTab]);

  // 切换论文时重置书签带和对比结果
  useEffect(() => {
    setActiveTab("breakdown");
    setCompareResult(null);
    setGuideDismissed(false);
  }, [currentPaperId, setActiveTab]);

  // 快捷键 1-5 切书签带（快捷键 hook 只负责分发按键事件）
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<{ tab?: string }>).detail;
      if (detail?.tab) setActiveTab(detail.tab);
    };
    window.addEventListener("paperpilot:set-tab", handler);
    return () => window.removeEventListener("paperpilot:set-tab", handler);
  }, [setActiveTab]);

  if (!currentPaperId) {
    return (
      // 宽度由外层 MobilePanel 控制（桌面固定 320px、移动端全屏抽屉）
      // id="ribbon-panel"：与未选论文态共用同一面板 id（两分支互斥渲染，不会重复），
      // 保证 RibbonStrip 各 tab 的 aria-controls 引用始终有效
      <aside id="ribbon-panel" className="w-full h-full bg-desk relative flex items-center justify-center shrink-0" aria-label="AI 分析边批">
        <Note variant="preface" className="max-w-[250px] mx-6">
          <div className="note-title">序 · 这里是批注的地方</div>
          <p className="note-body mt-1.5 text-[12px]">
            从左侧书架抽一本论文（点书卡），书顶书签带切换五类批注；AI 的分析会像学长批注一样写在这一栏。
          </p>
        </Note>
      </aside>
    );
  }

  // 是否显示首次使用引导：选了论文 + 没有任何分析结果 + 没在分析中 + 没被 dismiss
  const hasAnyResult = !!(currentResults.breakdown || currentResults.innovation || currentResults.flaws || compareResult || currentResults.compare);
  const showGuide = !hasAnyResult && !analyzing && !guideDismissed;

  return (
    <aside className="w-full h-full bg-desk flex flex-col shrink-0" aria-label="AI 分析边批">
      {/* 内容直接顶到面板顶部（书签带已是独立浮层，无需为它预留空间）。
          id="ribbon-panel"：五个书签 tab 的内容都换装在本容器内（按 activeTab
          条件渲染），RibbonStrip 的 aria-controls 统一指向这里（a11y） */}
      <div id="ribbon-panel" className="flex-1 min-h-0 flex flex-col pt-4 pb-6">
        <div className="mg-label shrink-0">随 读 随 批</div>

        {/* 引导卡（首次使用且尚无结果）：虚线序 note 样式 */}
        {showGuide && (
          <Note variant="preface" className="mb-4 mr-5 shrink-0">
            <div className="flex items-start justify-between gap-2">
              <div className="note-title">序 · 第一次用？按这个顺序看</div>
              <button
                onClick={() => setGuideDismissed(true)}
                className="text-muted-foreground hover:text-foreground shrink-0"
                aria-label="关闭引导"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
            <p className="note-body mt-1 text-[12px]">
              拆解 → 创新 → 漏洞 → 对比 → PPT；书顶书签带切换，结果可直接跳回 PDF 原文。
            </p>
          </Note>
        )}

        {activeTab === "breakdown" && (
          <div className="flex-1 min-h-0 overflow-hidden">
            <AnalysisView
              title="五段拆解"
              description="摘要 / 背景 / 目标 / 方法 / 实验 / 结论"
              emptyLabel="拆解"
              analyzing={analyzing === "breakdown"}
              disabled={!!analyzing && analyzing !== "breakdown"}
              hasResult={!!currentResults.breakdown}
              onAnalyze={() => analyzeStream("breakdown")}
              onCancel={() => cancelAnalysis()}
              error={analyzeErrors.breakdown}
              progress={analyzing === "breakdown" ? streamProgress : null}
              costHint="约 10–25 秒"
            >
              {currentResults.breakdown && <BreakdownView data={currentResults.breakdown} onJumpToPDF={onJumpToPDF} />}
            </AnalysisView>
          </div>
        )}

        {activeTab === "innovation" && (
          <div className="flex-1 min-h-0 overflow-hidden">
            <AnalysisView
              title="创新点分析"
              description="提炼核心创新点 + 评估创新等级"
              emptyLabel="创新点"
              analyzing={analyzing === "innovation"}
              disabled={!!analyzing && analyzing !== "innovation"}
              hasResult={!!currentResults.innovation}
              onAnalyze={() => analyze("innovation", !!currentResults.innovation)}
              error={analyzeErrors.innovation}
              costHint="约 10–25 秒"
            >
              {currentResults.innovation && <InnovationView data={currentResults.innovation} onJumpToPDF={onJumpToPDF} />}
            </AnalysisView>
          </div>
        )}

        {activeTab === "compare" && (
          <div className="flex-1 min-h-0 overflow-hidden">
            {/* B4：多篇对比事件优先，其次恢复服务端缓存的对比结果（切论文后不丢失） */}
            <CompareView externalResult={compareResult ?? currentResults.compare} onConsumed={() => setCompareResult(null)} />
          </div>
        )}

        {activeTab === "flaws" && (
          <div className="flex-1 min-h-0 overflow-hidden">
            <AnalysisView
              title="局限性分析"
              description="方法 / 实验 / 写作三层局限性 + 改进建议"
              emptyLabel="局限性"
              analyzing={analyzing === "flaws"}
              disabled={!!analyzing && analyzing !== "flaws"}
              hasResult={!!currentResults.flaws}
              onAnalyze={() => analyze("flaws", !!currentResults.flaws)}
              error={analyzeErrors.flaws}
              costHint="约 10–25 秒"
            >
              {currentResults.flaws && <FlawsView data={currentResults.flaws} onJumpToPDF={onJumpToPDF} />}
            </AnalysisView>
          </div>
        )}

        {activeTab === "ppt" && (
          <div className="flex-1 min-h-0">
            <ScrollArea className="h-full">
              <div className="pr-5 pt-1 pb-10">
                <PPTView />
              </div>
            </ScrollArea>
          </div>
        )}
      </div>
    </aside>
  );
}
