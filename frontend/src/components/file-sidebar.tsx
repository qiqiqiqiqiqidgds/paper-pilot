"use client";
/**
 * 论文库侧栏（批注手稿版）：左侧书架，横排书卡
 * 逻辑与旧版一致：多选对比（2-5 篇）、删除确认、加载错误重试
 */
import { useState } from "react";
import { GitCompare, Loader2, X, FileText, Plus } from "lucide-react";
import { Button } from "./ui/button";
import { ScrollArea } from "./ui/scroll-area";
import { UploadButton } from "./upload-button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "./ui/alert-dialog";
import { usePaperStore } from "@/stores/paper-store";
import { useMobileSidebar } from "./mobile-toggle";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { PaperInfo } from "@/types";

/* 书卡左侧的布脊色条（与书签带同族色，按序循环） */
const TICKS = [
  "hsl(var(--rb1))",
  "hsl(var(--rb2))",
  "hsl(var(--rb3))",
  "hsl(var(--rb4))",
  "hsl(var(--rb5))",
];

interface Props {
  papers: PaperInfo[];
  currentId: string | null;
  onSelect: (id: string) => void;
  onUploaded?: (paper: PaperInfo) => void;
}

export function FileSidebar({ papers, currentId, onSelect, onUploaded }: Props) {
  const removePaper = usePaperStore((s) => s.removePaper);
  const papersLoading = usePaperStore((s) => s.papersLoading);
  const papersLoadError = usePaperStore((s) => s.papersLoadError);
  const fetchPapers = usePaperStore((s) => s.fetchPapers);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [comparing, setComparing] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<PaperInfo | null>(null);
  const [deleting, setDeleting] = useState(false);
  // P2-10 改进: 移动端抽屉全屏覆盖顶栏时,提供抽屉内的关闭入口避免用户被困。
  // 桌面端此按钮 lg:hidden 自动隐藏,不影响正常顶栏交互。
  const mobileOpen = useMobileSidebar((s) => s.open);
  const closeMobile = useMobileSidebar((s) => s.close);
  const isMobileDrawer = mobileOpen === "left";

  const requestDelete = (e: React.MouseEvent, paper: PaperInfo) => {
    e.stopPropagation();
    setPendingDelete(paper);
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await removePaper(pendingDelete.paper_id);
      setSelected((s) => {
        const next = new Set(s);
        next.delete(pendingDelete.paper_id);
        return next;
      });
      toast.success("已删除");
      setPendingDelete(null);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`删除失败：${msg}`);
      // keep dialog open so user can retry; reset only on success
    } finally {
      setDeleting(false);
    }
  };

  const handleDialogOpenChange = (open: boolean) => {
    if (!open && deleting) return; // 不允许在删除进行中关闭
    if (!open) setPendingDelete(null);
  };

  const toggleSelect = (e: React.MouseEvent | React.ChangeEvent, id: string) => {
    e.stopPropagation();
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(id)) {
        next.delete(id);
      } else {
        // 与后端 ComparePapersRequest.max_length=5 对齐：超上限给出友好提示而非 422
        if (next.size >= 5) {
          toast.error("最多同时对比 5 篇论文");
          return s;
        }
        next.add(id);
      }
      return next;
    });
  };

  const handleCompare = async () => {
    if (selected.size < 2) {
      toast.error("至少选择 2 篇论文");
      return;
    }
    if (!currentId || !selected.has(currentId)) {
      toast.error("主论文必须被选中");
      return;
    }
    // F5: 发起前记录主论文 id。多篇对比 await 期间用户切换主论文时，
    // show-compare 的结果会写进新论文名下（张冠李戴）——检测到切换则静默丢弃
    const mainId = usePaperStore.getState().currentPaperId || currentId;
    setComparing(true);
    try {
      const ids = Array.from(selected);
      const data = await api.comparePapers(ids, currentId);
      // F5: await 后确认主论文没变，变了就丢弃本次结果
      if (usePaperStore.getState().currentPaperId !== mainId) return;
      toast.success("对比完成", { description: `对比了 ${ids.length} 篇论文` });
      // 刷新论文列表：多篇对比结果存在主论文名下，同步 has_compare 状态
      void usePaperStore.getState().fetchPapers();
      // 触发 AI 面板切换到对比书签带
      window.dispatchEvent(new CustomEvent("paperpilot:show-compare", { detail: data }));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`对比失败：${msg}`);
    } finally {
      setComparing(false);
    }
  };

  return (
    <>
      <aside
        className="w-full lg:w-60 border-r bg-background flex flex-col shrink-0 h-full"
        aria-label="论文库侧栏"
      >
        <div className="px-3 pt-3.5 pb-2 flex items-center justify-between shrink-0">
          <span className="text-[11px] tracking-[2px] text-muted-foreground">书架 · {papers.length} 本</span>
          {isMobileDrawer && (
            <Button
              size="icon"
              variant="ghost"
              className="h-7 w-7 lg:hidden"
              onClick={closeMobile}
              aria-label="关闭论文库"
            >
              <X className="h-4 w-4" />
            </Button>
          )}
        </div>

        {/* 勾选即给出可见反馈：1 篇时提示还差几篇，≥2 篇才可发起对比 */}
        {selected.size >= 1 && (
          <div className="px-3 pb-2 shrink-0">
            <Button
              size="sm"
              className="w-full"
              onClick={handleCompare}
              disabled={comparing || selected.size < 2}
            >
              <GitCompare className="h-3 w-3" />
              {comparing
                ? "对比中…"
                : selected.size < 2
                  ? `已选 ${selected.size} 篇 · 再选 ${2 - selected.size} 篇可对比`
                  : `对比选中 (${selected.size})`}
            </Button>
          </div>
        )}

        <ScrollArea className="flex-1">
          <div className="px-3 pb-3 space-y-2" role="list" aria-label="论文列表">
            {papersLoadError && (
              <div className="p-3 rounded border border-destructive/30 bg-destructive/5 text-xs space-y-2" role="alert">
                <div className="text-destructive font-medium">论文库加载失败</div>
                <div className="text-muted-foreground break-all">{papersLoadError}</div>
                <Button size="sm" variant="outline" className="w-full h-7 text-xs" onClick={() => fetchPapers()}>
                  <Loader2 className="h-3 w-3" />重试
                </Button>
              </div>
            )}
            {!papersLoadError && papers.length === 0 && !papersLoading && (
              <div className="text-xs text-muted-foreground py-10 px-2 flex flex-col items-center gap-3 text-center">
                <span className="h-11 w-11 rounded-full border border-dashed border-border flex items-center justify-center">
                  <FileText className="h-4 w-4" />
                </span>
                <span>
                  论文库还空着<br />点「上传论文」，放入第一篇
                </span>
              </div>
            )}
            {papersLoading && papers.length === 0 && (
              <div className="text-xs text-muted-foreground py-10 px-2 flex flex-col items-center gap-2" role="status" aria-live="polite">
                <Loader2 className="h-4 w-4 animate-spin" />
                加载论文库中…
              </div>
            )}
            {papers.map((p, i) => {
              const isSelected = selected.has(p.paper_id);
              const isCurrent = currentId === p.paper_id;
              return (
                <div
                  key={p.paper_id}
                  onClick={() => onSelect(p.paper_id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onSelect(p.paper_id);
                    }
                  }}
                  role="listitem"
                  tabIndex={0}
                  aria-label={`论文：${p.title || p.filename}（${p.pages} 页）`}
                  aria-current={isCurrent ? "true" : undefined}
                  className={cn(
                    "book-card group focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                    isCurrent && "bg-[#FFF9EC] dark:bg-[#2E2820] border-[hsl(var(--border-strong))] -translate-y-0.5 font-semibold",
                    isSelected && "ring-1 ring-ring"
                  )}
                >
                  <span className="book-card-tick" style={{ background: TICKS[i % TICKS.length] }} aria-hidden="true" />
                  <span className="flex-1 min-w-0">
                    <span
                      className={cn(
                        "block font-display text-[12.5px] truncate",
                        isCurrent ? "text-foreground font-semibold" : "text-ink2"
                      )}
                      title={p.title || p.filename}
                    >
                      {p.title || p.filename}
                    </span>
                  </span>
                  <span className="font-mono text-[10px] text-muted-foreground shrink-0">{p.pages}P</span>
                  {/* 多选对比复选框（勾选 2-5 篇） */}
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={(e) => toggleSelect(e, p.paper_id)}
                    onClick={(e) => e.stopPropagation()}
                    className="shrink-0 accent-[hsl(var(--cinnabar))] w-3.5 h-3.5"
                    aria-label={`选中《${p.title || p.filename}》以对比`}
                  />
                  {/* 圆形取下钮（app.html .book.del：右上角悬浮出现） */}
                  <button
                    type="button"
                    className="book-del opacity-0 group-hover:opacity-100 focus-visible:opacity-100 max-lg:opacity-100"
                    onClick={(e) => requestDelete(e, p)}
                    aria-label={`删除《${p.title || p.filename}》`}
                    title="取下这本"
                  >
                    ✕
                  </button>
                </div>
              );
            })}
          </div>
        </ScrollArea>

        {/* 上传入口：虚线书卡（与顶栏上传共用同一组件与守卫逻辑） */}
        <div className="pt-2 shrink-0">
          <UploadButton onUploaded={onUploaded}>
            <button
              type="button"
              className="book-card border-dashed bg-transparent justify-center gap-1.5 text-muted-foreground hover:text-[hsl(var(--cinnabar))] hover:border-[hsl(var(--cinnabar))] w-full"
              aria-label="上传新的论文"
            >
              <Plus className="h-3.5 w-3.5" aria-hidden="true" />
              <span className="text-xs">上传论文</span>
            </button>
          </UploadButton>
        </div>
      </aside>
      <AlertDialog
        open={pendingDelete !== null}
        onOpenChange={handleDialogOpenChange}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除论文</AlertDialogTitle>
            <AlertDialogDescription>
              要删除《{pendingDelete?.title || pendingDelete?.filename || ""}》吗？该论文的所有分析结果（拆解/创新/漏洞/对比）会一并清除，此操作不可撤销。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => {
                e.preventDefault();
                confirmDelete();
              }}
              disabled={deleting}
              className={cn(
                "bg-destructive text-destructive-foreground hover:bg-destructive/90",
                deleting && "opacity-70"
              )}
            >
              {deleting ? "删除中…" : "删除"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
