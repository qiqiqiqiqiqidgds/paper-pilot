"use client";
/**
 * 分析面板共享组件（批注手稿 · note 体系，对齐 design-preview/app.html）
 * - AnalysisView：边批容器，四种状态 = 进度 note（可取消）/ 错误 note / 空态 empty-set / 结果（紧凑头 + children）
 * - Note / NoteHead / NoteBody / JumpButton / ZhuQuote / MiniPoints：边批 note 基础件
 * - CopyButton：段落一键复制（clipboard + execCommand 降级）
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { MousePointerClick, Copy, Check, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useMobileSidebar } from "@/components/mobile-toggle";
import { useIsMobile } from "@/hooks/use-is-mobile";
import { cn } from "@/lib/utils";
import type { AnalysisViewProps } from "@/types";

/** CJK 带圈序号（①-⑳），超出后回退为普通数字 */
const CJK_NUMS = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩", "⑪", "⑫", "⑬", "⑭", "⑮", "⑯", "⑰", "⑱", "⑲", "⑳"];
export function circledNum(n: number): string {
  return n >= 1 && n <= CJK_NUMS.length ? CJK_NUMS[n - 1] : String(n);
}

/* ============================================================
   AnalysisView：边批容器（四态互斥渲染）
   ============================================================ */
export function AnalysisView({
  children,
  title,
  description,
  analyzing,
  onAnalyze,
  error,
  disabled,
  progress,
  hasResult,
  onCancel,
  costHint,
  runLabel,
  emptyLabel,
  rerunLabel,
  progressTitle,
}: AnalysisViewProps) {
  const pct = useMemo(() => {
    if (!progress) return 0;
    if (progress.stage === "reduce") return 95;
    if (progress.stage === "map" && progress.total > 0) {
      return Math.min(90, Math.round((progress.completed / progress.total) * 100));
    }
    if (progress.stage === "chapters") return 4;
    if (progress.stage === "started") return 2;
    return 0;
  }, [progress]);

  // 有确定总数（chapters/map 且 total>0）→ 定态进度；其余（启动中/整篇模式/reduce）→ 不定态
  const hasTotal = !!progress && progress.total > 0 && (progress.stage === "map" || progress.stage === "chapters");
  const isIndeterminate = !!progress && !hasTotal;

  const stageText = useMemo(() => {
    if (!progress) return "正在调用大模型，首次约 10–25 秒…";
    switch (progress.stage) {
      case "starting":
      case "started":
        return "已启动，正在读取论文…";
      case "chapters":
        return progress.total > 0 ? `识别到 ${progress.total} 个章节，开始逐章分析` : "正在识别章节…";
      case "map":
        return progress.currentChapter
          ? `正在分析「${progress.currentChapter}」`
          : progress.total > 0
            ? "逐章分析中…"
            : "正在分析全文…";
      case "reduce":
        return "正在汇总最终结果…";
      default:
        return "处理中…";
    }
  }, [progress]);

  // 进度 note 的标题：可覆盖；流式（SSE）默认「正在拆解」，普通分析默认「分析中」
  const resolvedProgressTitle = progressTitle || (progress ? "正在拆解" : "分析中");

  // 有结果：紧凑头 + children note 流；否则空态/进度/错误 note
  let body: React.ReactNode;
  if (analyzing) {
    body = (
      <div className="note plain" role="status" aria-live="polite" aria-busy="true">
        <div className="note-head">
          <span className="note-no" aria-hidden="true">✦</span>
          <span className="note-title">{resolvedProgressTitle}</span>
          {onCancel && !disabled && (
            <button type="button" className="note-jump ml-auto" onClick={onCancel}>
              取消
            </button>
          )}
        </div>
        <p className="note-body">{stageText}</p>
        <div className={cn("progress-bar", isIndeterminate && "indeterminate")} aria-hidden="true">
          <i style={{ width: `${isIndeterminate ? 33 : pct}%` }} />
        </div>
        {hasTotal && (
          <p className="note-body muted text-[11px]">
            {progress!.completed} / {progress!.total} 章节
          </p>
        )}
      </div>
    );
  } else if (error) {
    body = (
      <div className="note err" role="alert">
        <div className="note-head">
          <span className="note-title">分析失败</span>
        </div>
        <p className="note-body break-all">{error}</p>
        {/* disabled 与空态按钮一致：其他分析进行中时不允许并发触发第二个 LLM 任务 */}
        <Button size="sm" variant="ghost" className="mt-2" onClick={onAnalyze} disabled={analyzing || disabled}>
          重试
        </Button>
      </div>
    );
  } else if (hasResult) {
    // 结果模式：与设计稿一致，note 流直接铺开（当前视图名由书签带高亮表达），
    // 「重新分析」收在笔记末尾的落款位，不再挤占顶部一行
    body = (
      <>
        {children}
        <div className="mt-2 pt-3 border-t border-dashed border-[hsl(var(--border-strong))] text-center">
          <button
            type="button"
            className="note-jump mt-0"
            onClick={onAnalyze}
            disabled={analyzing || disabled}
          >
            <RefreshCw className="h-3 w-3" aria-hidden="true" />
            {rerunLabel || "重新分析"}
          </button>
        </div>
      </>
    );
  } else {
    body = (
      <div className="note plain empty-set">
        <div className="note-title">{emptyLabel || title}还没做</div>
        <p className="hint">这篇的{emptyLabel || title}结果还没有生成。{description ? `（${description}）` : ""}</p>
        <Button size="sm" onClick={onAnalyze} disabled={analyzing || disabled}>
          {runLabel || "开始分析"}
        </Button>
        {costHint && <p className="hint mt-2 mb-0">需要 {costHint}，走真实大模型。</p>}
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      <ScrollArea className="flex-1">
        {/* 与「随读随批」栏头左对齐；note 连接圈收在面板内侧（见 globals.css .note::before/::after） */}
        <div className="pr-5 pt-1 pb-10">{body}</div>
      </ScrollArea>
    </div>
  );
}

/* ============================================================
   note 基础件
   ============================================================ */

/** 边批条目容器：variant = plain（无连接件）/ zhu（朱批）/ preface（虚线序）/ err（错误） */
export function Note({
  variant,
  className,
  children,
  ...rest
}: {
  variant?: "plain" | "zhu" | "preface" | "err";
  className?: string;
  children: React.ReactNode;
} & Omit<React.ComponentProps<"div">, "className" | "children">) {
  return <div className={cn("note", variant, className)} {...rest}>{children}</div>;
}

/** note 头：序号（带圈数字/✦/◎ 等）+ 衬线标题 + 右侧页码/操作 */
export function NoteHead({
  no,
  title,
  page,
  action,
  className,
}: {
  no?: React.ReactNode;
  title: React.ReactNode;
  page?: string | number;
  action?: React.ReactNode;
  className?: string;
}) {
  const showPage = page !== undefined && page !== null && page !== "" && Number(page) !== 0;
  return (
    <div className={cn("note-head", className)}>
      {no != null && <span className="note-no">{no}</span>}
      <span className="note-title">{title}</span>
      {showPage && <span className="note-page">{page}</span>}
      {action}
    </div>
  );
}

/** 「跳到原文 P#」按钮：关闭移动端抽屉后派发跳转（onJumpToPDF 由面板统一分发） */
export function JumpButton({
  page,
  text,
  label,
  onJumpToPDF,
  className,
}: {
  page?: number;
  /** 可选引文文本：透传给 pdf-viewer 做原文高亮 */
  text?: string;
  label?: string;
  onJumpToPDF?: (page: number, text?: string) => void;
  className?: string;
}) {
  // F19: 移动端（<lg）抽屉覆盖整个页面，跳转会发生在被遮挡的阅读器上，先关抽屉
  // （P3: 原手写 window.innerWidth < 1024，收敛到 useIsMobile hook）
  const isMobile = useIsMobile();
  const handleJump = () => {
    if (isMobile) {
      useMobileSidebar.getState().close();
    }
    // 缺陷修复（2026-09-09 浏览器实测实锤）：必须透传 text。
    // 不透传会导致 jump-to-pdf 事件 detail 只有 { page }，pdf-viewer 的高亮
    // 链路入口条件是 highlightText && highlightText.length > 5，text 为 undefined
    // 时直接静默 return——跳页正常但"原文高亮"从未工作过。
    onJumpToPDF?.(page || 1, text);
  };
  if (!page || !onJumpToPDF) return null;
  return (
    <button type="button" className={cn("note-jump", className)} onClick={handleJump}>
      <MousePointerClick className="h-3 w-3" aria-hidden="true" />
      {label || `跳到原文 P${page}`}
    </button>
  );
}

/** 朱批原文引用：quote 底 + 左缘朱砂线，点击跳 PDF；附复制 */
export function ZhuQuote({
  quote,
  onJumpToPDF,
  label,
}: {
  quote: { section?: string; text?: string; page?: number };
  onJumpToPDF?: (page: number, text?: string) => void;
  label?: string;
}) {
  const { section = "", text = "", page = 0 } = quote;
  return (
    <Note variant="zhu" className="mt-1.5 mb-0">
      <p className="note-body">{text}</p>
      <div className="flex items-center justify-between gap-2">
        <JumpButton
          page={page}
          text={text}
          label={label || `${section || "原文"} · P${page}`}
          onJumpToPDF={onJumpToPDF}
        />
        {text && <CopyButton text={text} label="复制引用" />}
      </div>
    </Note>
  );
}

/** 小圆点列表（要点/优劣势）；tone = good（绿点）/ bad（红圆点） */
export function MiniPoints({ items, tone }: { items: string[]; tone?: "good" | "bad" }) {
  return (
    <ul className="mini-points">
      {items.filter((s) => s).map((s, i) => (
        // F18: key 用 index+前缀，LLM 输出重复要点时不会撞 key
        <li key={`${i}-${String(s).slice(0, 8)}`} className={tone}>{s}</li>
      ))}
    </ul>
  );
}

/**
 * 段落一键复制按钮
 * - 优先 navigator.clipboard；不支持时降级 textarea + execCommand
 * - 点击后短暂显示"已复制"
 */
export function CopyButton({ text, label }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  // 定时器句柄：重触发时清掉上一个（快速连点不会闪回），卸载后不再空转 setState
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (timerRef.current) clearTimeout(timerRef.current);
  }, []);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
      } catch {
        // 忽略（旧浏览器兜底失败）
      }
      document.body.removeChild(ta);
    }
    setCopied(true);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setCopied(false), 1500);
  };

  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        void copy();
      }}
      className="inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground shrink-0"
      aria-label={label || "复制文本"}
      title="复制"
    >
      {copied ? <Check className="h-3 w-3 text-success" aria-hidden="true" /> : <Copy className="h-3 w-3" aria-hidden="true" />}
      {copied ? "已复制" : "复制"}
    </button>
  );
}
