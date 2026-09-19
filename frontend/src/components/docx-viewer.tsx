"use client";
/**
 * DOCX 在线预览（docx-preview 纯前端渲染）
 *
 * 数据流：fetch /api/proxy/api/papers/{id}/file → ArrayBuffer → renderAsync
 * 渲染进容器。分页按文档分页符近似切分（非 Word 排版引擎真实分页），
 * PDF 引用跳转高亮链路（paperpilot-highlight）在此视图不可用——AI 面板照常可用。
 *
 * 加载失败时降级为 DOCXPlaceholder（下载原文件查看），不白屏。
 */
import { useEffect, useRef, useState } from "react";
import { Download, Loader2, RefreshCw, FileWarning } from "lucide-react";
import { Button } from "./ui/button";
import { RibbonStrip } from "./ribbon-strip";
import { toast } from "sonner";
import { API_BASE, downloadBlob } from "@/lib/api";

/** 预览失败兜底：保留下载原文件入口（原"不支持在线预览"占位组件的失败态版本） */
function DOCXPlaceholder({ paperId, reason }: { paperId: string | null; reason?: string | null }) {
  const [downloading, setDownloading] = useState(false);
  const handleDownload = async () => {
    if (!paperId) return;
    setDownloading(true);
    try {
      // 走 BFF 代理下载（自动附服务端鉴权 header），代替 window.open（会被弹窗拦截且带不了 header）
      await downloadBlob(`/api/papers/${paperId}/file`);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`下载失败：${msg}`);
    } finally {
      setDownloading(false);
    }
  };

  return (
    <main className="flex-1 flex items-center justify-center bg-desk">
      <div className="text-center max-w-md p-8">
        <div className="h-16 w-16 mx-auto mb-4 rounded-full border border-dashed border-border flex items-center justify-center bg-card">
          <FileWarning className="h-6 w-6 text-muted-foreground" aria-hidden="true" />
        </div>
        <div className="font-display text-lg font-semibold mb-2 text-foreground">Word 在线预览加载失败</div>
        <div className="text-sm text-muted-foreground mb-6 leading-relaxed">
          {reason || "文件可能已损坏，或网络临时异常。"}
          <br />
          AI 分析结果在右侧，照常可用。
        </div>
        <Button onClick={handleDownload} disabled={downloading}>
          <Download className="h-4 w-4 mr-2" />
          {downloading ? "下载中…" : "下载原文件查看"}
        </Button>
      </div>
    </main>
  );
}

type PreviewState = { phase: "loading" | "ok" | "error"; message?: string };

export function DocxViewer({ paperId }: { paperId: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  // Word 页面的未缩放自然宽度：zoom 生效后 offsetWidth 会被缩放，
  // 因此渲染完成时先记下原始值，缩放/resize 重算都用它，避免反馈循环
  const naturalWidthRef = useRef(0);
  const [state, setState] = useState<PreviewState>({ phase: "loading" });
  const [fitScale, setFitScale] = useState(1);
  const [reloadTick, setReloadTick] = useState(0);

  // 适宽缩放：把 Word 页面缩到面板宽度以内（上限 100% 不放大）。
  // 与 PDF 查看器的「适合宽度」语义一致；用 CSS zoom 而非 transform，
  // 缩放后布局高度/滚动条自然正确。
  const applyFit = () => {
    const scroll = scrollRef.current;
    const natural = naturalWidthRef.current;
    if (!scroll || !natural) return;
    const avail = scroll.clientWidth - 72; // 扣除 px-9 左右内边距（书桌留白）
    if (avail > 0) setFitScale(Math.min(1, Math.round((avail / natural) * 1000) / 1000));
  };

  // 面板宽度变化（拖分割条/窗口缩放）时重算。观察滚动容器而非被缩放的内容，
  // 内容宽度随 zoom 变化不会触发本观察器，无反馈循环。
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => applyFit());
    observer.observe(el);
    return () => observer.disconnect();
  }, [state.phase]);

  useEffect(() => {
    let cancelled = false;
    setState({ phase: "loading" });
    naturalWidthRef.current = 0;
    setFitScale(1);
    // P2-2：下载加 AbortController + 60s 超时（与 paper-store 的 PDF 下载对齐）。
    // 之前是裸 fetch：网络挂起时 UI 永远停在"渲染中…"，且唯一的恢复入口
    // （重新加载按钮）恰好被 loading 态禁用，整个视图卡死无解。
    // cleanup（换 paperId / 手动重载 / 卸载）时一并 abort 旧请求。
    const controller = new AbortController();
    const timeoutId = setTimeout(
      () => controller.abort(new Error("DOCX 下载超时（60s）")),
      60_000,
    );
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/api/papers/${paperId}/file`, {
          signal: controller.signal,
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const buf = await res.arrayBuffer();
        if (cancelled) return;
        clearTimeout(timeoutId);
        // 动态 import：docx-preview 依赖 DOM，避免被 SSR/构建链路静态引入
        const { renderAsync } = await import("docx-preview");
        if (cancelled || !containerRef.current) return;
        containerRef.current.innerHTML = "";
        await renderAsync(buf, containerRef.current, undefined, {
          inWrapper: true,
          breakPages: true,
          ignoreLastRenderedPageBreak: false,
          useBase64URL: true, // 图片走 data URL，避免 blob URL 生命周期问题
        });
        if (cancelled) return;
        // zoom 尚未生效（reset 为 1），此时 offsetWidth 即自然宽度
        const wrapper = containerRef.current.querySelector(".docx-wrapper") as HTMLElement | null;
        naturalWidthRef.current = wrapper ? wrapper.offsetWidth : 0;
        setState({ phase: "ok" });
      } catch (e: unknown) {
        if (!cancelled) {
          const msg = e instanceof Error ? e.message : String(e);
          setState({ phase: "error", message: msg });
        }
      } finally {
        clearTimeout(timeoutId);
      }
    })();
    return () => {
      cancelled = true;
      clearTimeout(timeoutId);
      // 中止在飞请求：换论文/重载时旧下载不再占用带宽与内存
      controller.abort();
    };
  }, [paperId, reloadTick]);

  // 渲染完成后做一次适宽（此时 naturalWidth 已就绪）
  useEffect(() => {
    if (state.phase === "ok") applyFit();
  }, [state.phase]);

  if (state.phase === "error") {
    return <DOCXPlaceholder paperId={paperId} reason={state.message} />;
  }

  return (
    <main className="flex-1 relative bg-desk overflow-hidden" aria-label="Word 预览器">
      {/* 书签带浮层：绝对定位于书桌左上，不随内容滚动 */}
      <RibbonStrip />
      <div className="h-full overflow-auto desk-scroll" ref={scrollRef}>
        <div className="min-h-full min-w-fit flex justify-center px-9 pt-[64px] pb-16">
          <div className="relative w-fit max-w-full">
            {/* 纸页（docx-preview 自带灰底白页样式；zoom 为适宽缩放 ≤100%） */}
            <div
              ref={containerRef}
              className="docx-preview-container"
              style={fitScale < 1 ? { zoom: fitScale } : undefined}
            />
            {state.phase === "loading" && (
              <div className="absolute inset-0 flex items-center justify-center">
                <span className="text-xs text-muted-foreground inline-flex items-center gap-1.5 bg-card border border-border rounded px-3 py-1.5">
                  <Loader2 className="h-3 w-3 animate-spin" /> 渲染中…
                </span>
              </div>
            )}

            {/* 页脚：功能钮 + 静态说明（保持与 PDF 纸页"两钮夹中签"的构图一致。
                P3: 原先写死的「· 1 / 1 ·」是假页码——docx-preview 的 breakPages
                只是按分页符近似切分，拿不到真实页数，改为如实说明。 */}
            <div className="sheet-foot">
              <button
                className="pn-btn"
                onClick={() => setReloadTick((n) => n + 1)}
                aria-label="重新加载"
                title="重新加载"
              >
                <RefreshCw className="h-3 w-3" />
              </button>
              <span className="pn">· 预览（分页为近似效果） ·</span>
              <button
                className="pn-btn"
                aria-label="下载原文件"
                title="下载原文件"
                onClick={() => {
                  downloadBlob(`/api/papers/${paperId}/file`).catch((e: unknown) => {
                    const msg = e instanceof Error ? e.message : String(e);
                    toast.error(`下载失败：${msg}`);
                  });
                }}
              >
                <Download className="h-3 w-3" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
