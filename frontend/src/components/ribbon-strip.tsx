"use client";
/**
 * 五条书签带：横向色签一排，绝对定位于书桌左上（.ribbon-strip，浮层不随滚动）
 * 点击切换右侧边批内容（ui-store），完成过的边批带白色小圆点标记
 */
import { useUiStore } from "@/stores/ui-store";
import { usePaperStore } from "@/stores/paper-store";
import { cn } from "@/lib/utils";

const RIBBONS = [
  { key: "breakdown", label: "拆解", cls: "r1", aria: "拆解：论文结构化总结" },
  { key: "innovation", label: "创新", cls: "r2", aria: "创新：提炼核心创新点" },
  { key: "compare", label: "对比", cls: "r3", aria: "对比：相关工作对比表" },
  { key: "flaws", label: "漏洞", cls: "r4", aria: "漏洞：局限性分析" },
  { key: "ppt", label: "PPT", cls: "r5", aria: "PPT：生成汇报 PPT" },
] as const;

export function RibbonStrip() {
  const activeTab = useUiStore((s) => s.activeTab);
  const setActiveTab = useUiStore((s) => s.setActiveTab);
  const currentPaperId = usePaperStore((s) => s.currentPaperId);
  const results = usePaperStore((s) => s.results);
  const currentResults = currentPaperId ? results[currentPaperId] || {} : {};

  return (
    <div className="ribbon-strip" role="tablist" aria-label="边批切换">
      {RIBBONS.map((r) => {
        const hasResult = r.key !== "ppt" && !!(currentResults as Record<string, unknown>)[r.key];
        return (
          <button
            key={r.key}
            type="button"
            role="tab"
            aria-selected={activeTab === r.key}
            // a11y: 指向边批面板容器（AIAnalysisPanel 内 id="ribbon-panel"，
            // 五个 tab 的内容都换装在该容器里，故共用同一面板 id）
            aria-controls="ribbon-panel"
            aria-label={r.aria}
            data-active={activeTab === r.key}
            onClick={() => setActiveTab(r.key)}
            className={cn("ribbon", r.cls, hasResult && "has-result")}
          >
            <span className="badge-dot" aria-hidden="true" />
            {r.label}
          </button>
        );
      })}
    </div>
  );
}
