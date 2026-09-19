"use client";
import { useState, useRef, useEffect, type Ref, type ReactNode } from "react";
import { Document, Page } from "react-pdf";
import type { PDFDocumentProxy } from "pdfjs-dist";
// workerSrc 单点设置：lib/pdf 改为 dynamic import 懒加载（SSR 安全）。
// 浏览器侧 useEffect 内 await initPdfJs() 后再渲染 <Document>，
// 否则 <Document> 内部会用 react-pdf 自带的相对路径默认值（404）。
import { initPdfJs } from "@/lib/pdf";
// Sprint 3 / I4：pdfjs 4.x worker 是 ESM .mjs。
// 方案：scripts/copy-pdf-worker.mjs（predev/prebuild 钩子）把 worker 复制到
// public/pdf.worker.min.mjs，这里只挂静态路径——绕开 webpack 编译/压缩 ESM worker。
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import { toast } from "sonner";
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut, FileText, AlertCircle, RefreshCw, FileWarning } from "lucide-react";
import { Button } from "./ui/button";
import { UploadButton } from "./upload-button";
import { DocxViewer } from "./docx-viewer";
import { RibbonStrip } from "./ribbon-strip";
import { cn } from "@/lib/utils";
import { usePaperStore } from "@/stores/paper-store";
import { buildSearchCandidates, stripPageAnnotations } from "@/lib/highlight-candidates";

// PDF.js worker 配置（workerSrc）已收敛到 src/lib/pdf.ts 单点设置，
// 此处不再重复赋值，避免与 react-pdf 默认值产生顺序竞争。

// P0-1：<Document options> 必须是稳定引用——react-pdf 的 loadDocument effect
// 依赖 [options, pdfDispatch, source]（见 node_modules/react-pdf/dist/Document.js:211-242），
// options 引用变化即 cleanup 里 loadingTask.destroy() 并整本重新 getDocument。
// 若写成 JSX 内联字面量，翻页/缩放/SSE 进度等任何一次 setState 触发的重渲染
// 都会让整本 PDF 销毁重载（onLoadSuccess 二次触发还会重置缩放、清空文本缓存）。
// 因此提为模块级常量，保证每次渲染传给 <Document> 的都是同一个引用。
const DOCUMENT_OPTIONS = {
  // P2-3：提供 CMap 与标准字体资源（predev 由 copy-pdf-worker.mjs 复制到 public/）。
  // 未内嵌字体的中文 PDF 缺这两项会整页渲染成空白/豆腐块，且 getTextContent()
  // 抽不出正确文本——引用跳转高亮随之失效；资源路径以 / 结尾是 pdfjs 的要求。
  cMapUrl: "/cmaps/",
  cMapPacked: true,
  standardFontDataUrl: "/standard_fonts/",
};

// 记录上次高亮的全部 span（命中时整段 run 都会加 class，P1-2：只记首 span 的话，
// clearHighlight 清不掉 run 的其余 span，同页多次跳转后会残留多个蜜黄块）。
// 新一次跳转时先清除。
// 模块级（PDFViewer 单实例，符合原函数 module-level 风格）
let lastHighlightedEls: HTMLElement[] = [];
// W1-01 §4.1：高亮 3 秒后自动渐隐（timer 句柄，供下次跳转时取消，防止旧高亮残留）
let highlightFadeTimer: ReturnType<typeof setTimeout> | null = null;

function clearHighlight() {
  if (highlightFadeTimer) {
    clearTimeout(highlightFadeTimer);
    highlightFadeTimer = null;
  }
  // 逐个判 document.contains：text layer 可能已被卸载（翻页/文档重载），
  // 不在文档中的元素跳过即可
  for (const el of lastHighlightedEls) {
    if (document.contains(el)) {
      el.classList.remove("paperpilot-highlight", "paperpilot-highlight-fade");
    }
  }
  lastHighlightedEls = [];
}

/** 3 秒后触发：先给上次高亮的全部 span 加 fade class（CSS 过渡渐隐），过渡结束再彻底清除 */
function fadeHighlightAfterDelay() {
  if (highlightFadeTimer) clearTimeout(highlightFadeTimer);
  highlightFadeTimer = setTimeout(() => {
    highlightFadeTimer = null;
    // 渐隐同样作用于整段 run 的所有 span，不只首 span（P1-2）
    const els = lastHighlightedEls.filter((el) => document.contains(el));
    if (els.length > 0) {
      for (const el of els) el.classList.add("paperpilot-highlight-fade");
      // 渐隐结束的清理也存入同一 timer 槽位：新跳转 clearHighlight() 会取消它，
      // 否则旧 650ms 定时器会在新跳转后误清新高亮（并取消其渐隐）
      const fadeTimer = setTimeout(() => {
        if (highlightFadeTimer === fadeTimer) highlightFadeTimer = null;
        clearHighlight();
      }, 650);
      highlightFadeTimer = fadeTimer;
    } else {
      clearHighlight();
    }
  }, 3000);
}

// 跳转改为 paperpilot:jump-to-pdf 事件驱动（page.tsx 分发），无 imperative handle。

/**
 * 书桌外壳（对齐 app.html .desk/.sheet-wrap 构图）：
 * 居中 620px 纸页（paper-page），顶边书签带，下方页脚/缩放浮签由调用方传入。
 * 空态 / 加载 / 错误 / 正常四种分支共用，保证书签带任何时刻可见（设计稿行为）。
 */
function Desk({
  mainRef,
  containerRef,
  wrapRef,
  children,
  foot,
  zoom,
  wideContent = true,
}: {
  mainRef: Ref<HTMLElement>;
  containerRef: Ref<HTMLDivElement>;
  wrapRef?: Ref<HTMLDivElement>;
  children: ReactNode;
  foot?: ReactNode;
  zoom?: ReactNode;
  // P2-5（移动端实测 T8）：内容条是否允许按内容撑宽（min-w-fit）。
  // 纯便签态（空态/加载中）没有大画布，必须让外层收缩到视口内——否则 min-w-fit
  // 会按 620px 纸页把整条内容带撑出 375px 视口，.docx-note 卡片（含「上传文件」
  // 按钮）被裁掉一半。PDF 态保持默认 true：缩放 >100% 时靠 min-w-fit 让纸页随
  // 画布撑宽、桌面向右滚动（桌面端 620px 构图不受影响，max-w-full 负责小屏收缩）。
  wideContent?: boolean;
}) {
  return (
    <main ref={mainRef} className="flex-1 relative bg-desk overflow-hidden" aria-label="PDF 阅读器">
      {/* 书签带浮层：绝对定位于书桌左上，不随内容滚动（与缩放浮签同级） */}
      <RibbonStrip />
      <div className="h-full overflow-auto desk-scroll" ref={containerRef}>
        <div className={cn("min-h-full flex justify-center px-9 pt-[64px] pb-16", wideContent && "min-w-fit")}>
          <div className="relative w-[620px] max-w-full" ref={wrapRef}>
            <div className="paper-page">{children}</div>
            {foot ?? (
              <div className="sheet-foot">
                <button className="pn-btn" disabled aria-label="上一页">
                  <ChevronLeft className="h-3 w-3" />
                </button>
                <span className="pn">— 页 —</span>
                <button className="pn-btn" disabled aria-label="下一页">
                  <ChevronRight className="h-3 w-3" />
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
      {zoom}
    </main>
  );
}

// P2-1：全文定位的受限并发——每批并行 getTextContent 的页数。
// getTextContent 是 pdfjs worker 调用，8 并发足以把 500 页 PDF 的逐页串行
// （最坏几十秒无反馈）压到约 total/8 批的耗时，又不至于一次性占满 worker/内存。
const PAGE_SEARCH_BATCH = 8;
// P2-1：页文本缓存上限（条数 = 页数）。原实现无上限，超大 PDF 全量缓存无界增长。
// 超限按 Map 插入序淘汰最早缓存的条目（近似"最旧先出"）；取舍：被淘汰页再次
// 搜索时重新提取（耗时换内存），比整体清空少一次缓存抖动，实现也足够简单。
const PAGE_TEXT_CACHE_LIMIT = 300;

/** 页文本缓存超过 PAGE_TEXT_CACHE_LIMIT 时按插入序淘汰最旧条目，保证有界 */
function trimPageTextCache(cache: Map<number, string>) {
  while (cache.size > PAGE_TEXT_CACHE_LIMIT) {
    const oldest = cache.keys().next().value;
    if (oldest === undefined) break;
    cache.delete(oldest);
  }
}

export function PDFViewer() {
  const pdfUrl = usePaperStore((s) => s.pdfUrl);
  const pdfLoadError = usePaperStore((s) => s.pdfLoadError);
  const currentPaperId = usePaperStore((s) => s.currentPaperId);
  const currentFileType = usePaperStore((s) => s.currentFileType);
  const zoom = usePaperStore((s) => s.zoom);
  const setZoom = usePaperStore((s) => s.setZoom);
  const [numPages, setNumPages] = useState(0);
  const [page, setPage] = useState(1);
  const [parseError, setParseError] = useState<string | null>(null);
  // lib/pdf 改为 dynamic import 懒加载后，<Document> 必须等到 initPdfJs() 完成
  // （workerSrc 已覆盖到 /pdf.worker.min.mjs）才能挂载，否则内部用 react-pdf
  // 自带的相对路径 'pdf.worker.mjs' 默认值会 404，抛
  // "No 'GlobalWorkerOptions.workerSrc' specified" / fetch failed。
  const [pdfjsReady, setPdfjsReady] = useState(false);
  // F14: initPdfJs 失败后用计数触发 effect 重跑（重试入口），否则 pdfjsReady 恒 false，
  // UI 永远停在"加载 PDF 渲染器..."
  const [initAttempt, setInitAttempt] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  // 纸页包裹层（书签带 + paper-page + 页脚）：引用跳转时闪蜜黄描边（app.html .flash）
  const sheetWrapRef = useRef<HTMLDivElement>(null);
  // A6: 外层布局元素（<main>）的 ref——ResizeObserver 观察它而不是滚动容器，
  // 避免容器自身纵向滚动条的出现/消失（内容驱动）误触发适宽重算
  const mainRef = useRef<HTMLElement>(null);
  // 用 ref 让 jumpToPage 拿到最新 numPages（闭包问题）
  const numPagesRef = useRef(0);
  // 全文定位用：react-pdf 加载后的 pdfjs 文档实例 + 每页文本缓存
  // （LLM 猜的页码不可靠，点击引用时先在全文搜真实页再跳转）
  const pdfDocRef = useRef<PDFDocumentProxy | null>(null);
  const pageTextCacheRef = useRef<Map<number, string>>(new Map());
  // P0-1：记录上次已执行「适宽」的 file（pdfUrl）。同一文档再次触发 onLoadSuccess
  // （StrictMode 双挂载等意外的重复加载）时跳过适宽，避免把用户手动缩放重置回
  // 适宽值；不同论文的 blob URL 不同，仍会重新适宽。
  const lastFittedFileRef = useRef<string | null>(null);

  // 切换论文/清空 pdfUrl 时重置 pdfjs 引用：旧 Document 卸载到新文档 onLoadSuccess
  // 之间的过渡窗口内，不能拿旧文档做全文搜索（getPage 会抛错被吞成"未找到"）；
  // 同时递增跳转 token，使在途的旧论文跳转立即作废（否则会用 A 的页码在 B 上 setPage）
  useEffect(() => {
    jumpTokenRef.current += 1;
    pdfDocRef.current = null;
    pageTextCacheRef.current = new Map();
    numPagesRef.current = 0;
    // F2: 同步重置页码 state——长论文读到第 6 页后切 4 页短论文，
    // 旧 pageNumber 越界会导致新文档加载后 <Page pageNumber={6}> 请求不存在的页，
    // 画布报 "Failed to load the page."、页码显示 "6 / 4"
    setPage(1);
    setNumPages(0);
  }, [pdfUrl]);

  // 浏览器侧动态加载 react-pdf + 设置 workerSrc。
  // 挂载一次即可（initPdfJs 内部已用 initPromise 缓存，幂等）；
  // F14: 失败时 initPdfJs 会清掉缓存的 rejected promise，重试按钮递增 initAttempt
  // 触发本 effect 重跑，而不是永远卡死。
  useEffect(() => {
    let cancelled = false;
    initPdfJs()
      .then(() => {
        if (!cancelled) setPdfjsReady(true);
      })
      .catch((err) => {
        // 极少数情况（网络/DNS 拉不到 chunk）：不在挂载阶段直接 throw，避免 ErrorBoundary
        // 把整个工具栏都吃掉；改为记录错误，由 !pdfjsReady 分支渲染错误 + 重试按钮。
        console.error("[pdf-viewer] initPdfJs failed:", err);
        if (!cancelled) setParseError("PDF 渲染器初始化失败（" + (err?.message || String(err)) + "）");
      });
    return () => {
      cancelled = true;
    };
  }, [initAttempt]);

  // A6: 计算「适合宽度」缩放（上限 100%）。
  // 纸页目标宽 = min(620px 纸宽, 书桌可用宽)：按滚动容器宽做确定性计算，
  // 不测量 w-fit 纸页自身（加载中时宽度极小，会把缩放算错）
  const computeFitWidthScale = async (doc: PDFDocumentProxy): Promise<number | null> => {
    const container = containerRef.current;
    if (!container || container.clientWidth <= 0) return null;
    try {
      const pdfPage = await doc.getPage(1);
      const viewport = pdfPage.getViewport({ scale: 1 });
      if (!viewport.width) return null;
      const available = Math.min(620, container.clientWidth - 72); // px-9 左右留白各 36px
      if (available <= 60) return null;
      // 上限 100%：大屏不放大超过原始大小；保留 3 位小数避免浮点噪音
      return Math.min(1, Math.round((available / viewport.width) * 1000) / 1000);
    } catch {
      return null;
    }
  };

  // A6: 布局宽度变化（拖拽分割条 / 窗口缩放 / 移动端抽屉开合）时重新「适合宽度」，
  // 保证任何宽度下页面都完整可见。
  // 【关键】observe 的是外层 <main>（mainRef）而非滚动容器本身：
  // 容器的 clientWidth 会因"内容增高 → 出现纵向滚动条"而变小（缩放 >100% 时
  // A4 页面高度超过容器高度），这是内容驱动的宽度变化——若据此 refit，
  // 用户手动放大的缩放会在滚动条出现后（约 2.5s 画布渲染完）被重置回适宽值，
  // 且页面变矮滚动条消失再次触发，最终稳定在 58% 附近（回归缺陷的根因）。
  // <main> 的尺寸只随布局变化，与容器滚动条无关；回调里再按「宽度是否真的变化」
  // 过滤（窗口高度等纯高度变化不影响适宽，不 refit）。
  useEffect(() => {
    const layoutEl = mainRef.current;
    if (!layoutEl || typeof ResizeObserver === "undefined") return;
    let lastWidth: number | null = null;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[entries.length - 1];
      if (!entry) return;
      const width = entry.contentRect.width;
      // 首次回调只记录基线（observe 即触发一次），不 refit
      if (lastWidth === null) {
        lastWidth = width;
        return;
      }
      // 仅宽度变化才 refit；高度变化（窗口高度调整等）不影响适宽值
      if (width === lastWidth) return;
      lastWidth = width;
      const doc = pdfDocRef.current;
      // 文档未加载完成时不做 fit（避免用 null 文档计算 / 覆盖加载中的缩放）
      if (!doc || numPagesRef.current === 0) return;
      void computeFitWidthScale(doc).then((fit) => {
        if (fit != null) setZoom(fit);
      });
    });
    observer.observe(layoutEl);
    return () => observer.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentPaperId, currentFileType, pdfUrl]);

  // next/dynamic 包装不转发 ref（React 18），改用全局事件驱动：
  // AI 面板侧 dispatch `paperpilot:jump-to-pdf`，本组件内部自监听。
  // handler 通过 ref 取最新 jumpToPage：监听器只挂载一次（旧实现无 deps 数组，
  // 每次渲染——翻页/缩放/SSE 进度——都 remove/add 三个 window listener）
  const jumpToPageRef = useRef<(page: number, text?: string) => void>(() => {});
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<{ page: number; text?: string }>).detail;
      const { page: targetPage, text: highlightText } = detail || {};
      // 注意不能用 `if (targetPage)`：LLM 有时会产出 0 基页码（P0），
      // 0 是合法输入，jumpToPage 内部会做 1..numPages 夹取
      if (targetPage != null) jumpToPageRef.current(targetPage, highlightText);
    };
    window.addEventListener("paperpilot:jump-to-pdf", handler);

    // 快捷键 ←/→ 翻页（快捷键 hook 只负责分发按键事件）
    const pageHandler = (e: Event) => {
      const direction = (e as CustomEvent).type === "paperpilot:next-page" ? 1 : -1;
      setPage((p) => {
        const np = numPagesRef.current;
        return Math.max(1, Math.min(np || p, p + direction));
      });
    };
    window.addEventListener("paperpilot:prev-page", pageHandler);
    window.addEventListener("paperpilot:next-page", pageHandler);
    return () => {
      window.removeEventListener("paperpilot:jump-to-pdf", handler);
      window.removeEventListener("paperpilot:prev-page", pageHandler);
      window.removeEventListener("paperpilot:next-page", pageHandler);
    };
  }, []);

  // 跳转竞态防护：连续点击引用时只让最后一次跳转生效
  // （findTextPage 逐页搜索耗时，旧跳转的异步回调不能覆盖新跳转的目标页/高亮）
  const jumpTokenRef = useRef(0);

  // 跳转到指定页 + 高亮文本（PDF 未加载完时重试等 numPages 就绪）
  const jumpToPage = (targetPage: number, highlightText?: string) => {
    const token = ++jumpTokenRef.current;
    const isCurrent = () => token === jumpTokenRef.current;

    // PDF 还没加载完（numPages=0）时，AI 引用的页码会被 `|| 1` 错误地夹到第 1 页。
    // F6: 重试 20 次 / 每次 250ms（共约 5s）等到 numPages 就绪后再 setPage；
    // 旧方案 5 次 × 100ms 只等 500ms，几乎必然放弃并把页码错设成 1。
    let attempts = 0;
    const tryJump = () => {
      attempts += 1;
      const np = numPagesRef.current;
      if (np === 0) {
        if (attempts < 20) {
          setTimeout(tryJump, 250);
          return;
        }
        // F6: 约 5s 后文档仍未加载出来（PDF 还在下载/渲染器未就绪）：
        // 放弃本次跳转——此时 setPage 会被 `|| 1` 夹到第 1 页（跳错页），
        // 且后续高亮搜索必然失败、弹出"未找到匹配的原文段落"假错误。
        // P3: 不再静默——温和提示用户稍后重试；仅当仍是本次跳转时才提示
        // （期间用户已切论文/点了新引用则 token 已失效，不弹误导 toast）。
        if (isCurrent()) {
          toast.info("PDF 还在加载，跳转未完成，请稍后重试");
        }
        return;
      }
      if (!isCurrent()) return; // 期间已有更新的跳转
      // 限制页码范围（能走到这里说明文档已加载，np > 0）
      const safePage = Math.max(1, Math.min(np, targetPage));
      setPage(safePage);
      // 纸页闪蜜黄描边（重排强制重启动画，同 app.html flashSheet）
      const wrap = sheetWrapRef.current;
      if (wrap) {
        wrap.classList.remove("sheet-flash");
        void wrap.offsetWidth;
        wrap.classList.add("sheet-flash");
      }
      // 滚动到顶部
      setTimeout(() => {
        if (!isCurrent()) return;
        if (containerRef.current) {
          containerRef.current.scrollTo({ top: 0, behavior: "smooth" });
        }
        // 高亮文本（基于 text layer；内部会轮询等 react-pdf 渲染完）
        void (async () => {
          if (!(highlightText && highlightText.length > 5)) return;
          // 纯页码标注文本（无可搜内容）静默跳过，不弹误导 toast
          const searchText = stripPageAnnotations(highlightText);
          if (!searchText) return;
          // 快速路径：先按 LLM 给的页码高亮
          const found = await highlightInTextLayer(highlightText, isCurrent);
          if (!isCurrent()) return;
          if (found) return;
          // 兜底：LLM 页码可能猜错（尤其旧分析结果），在整篇 PDF 中搜真实页
          let realPage = await findTextPage(searchText);
          // F6/F10 兜底：剥离页码标注后搜不到 → 用未剥离的原文再搜一次
          // （剥离规则可能误删了原文里真实存在的内容，如证据文本本身含 "[P3]"）
          if (realPage == null && highlightText !== searchText) {
            realPage = await findTextPage(highlightText);
          }
          if (!isCurrent()) return;
          if (realPage && realPage !== safePage) {
            setPage(realPage);
            // 新页渲染后再次高亮
            setTimeout(() => {
              if (!isCurrent()) return;
              void highlightInTextLayer(highlightText, isCurrent);
            }, 150);
          } else if (realPage == null) {
            // 文档已加载且两轮搜索都未命中才弹错误（文档没加载时已在上面静默 return）
            toast.error("未找到匹配的原文段落（可尝试重新运行分析生成更准确的引用）");
          }
        })();
      }, 100);
    };
    tryJump();
  };

  // 每次 render 后同步最新实现给事件监听器（监听器只挂载一次，见上方 effect）
  useEffect(() => {
    jumpToPageRef.current = jumpToPage;
  });

  // 全局定位：在整篇 PDF 中搜索引用文本所在的真实页（getTextContent + 页文本缓存）。
  // P2-1：原实现逐页 await 串行搜索，500 页 PDF 最坏几十秒无反馈；改为受限并发——
  // 每批 PAGE_SEARCH_BATCH 页并行提取文本，批完成后按页码升序扫描、命中即返回。
  // 语义保持：批次严格按页码顺序处理、批内也按页码升序扫描，所以"首个命中页"
  // 就是全篇最小命中页，与原串行实现"从第 1 页起找第一个命中"完全一致；
  // 批内即使多页同时命中也不提前返回（并行提取本就已发起，等整批完成再扫描即可）。
  const findTextPage = async (searchText: string): Promise<number | null> => {
    const pdf = pdfDocRef.current;
    const total = numPagesRef.current;
    if (!pdf || total === 0) return null;
    const norm = (s: string) => s.replace(/\s+/g, " ").toLowerCase();
    const target = norm(searchText);
    if (!target || target.length < 5) return null;
    const getPageText = async (p: number): Promise<string> => {
      const cached = pageTextCacheRef.current.get(p);
      if (cached !== undefined) return cached;
      let pageText = "";
      try {
        const page = await pdf.getPage(p);
        const content = await page.getTextContent();
        pageText = content.items
          .map((item) => ("str" in item ? item.str : ""))
          .join(" ");
      } catch {
        pageText = "";
      }
      pageTextCacheRef.current.set(p, pageText);
      // P2-1：缓存有界化（见 PAGE_TEXT_CACHE_LIMIT 处的取舍说明）
      trimPageTextCache(pageTextCacheRef.current);
      return pageText;
    };
    for (let start = 1; start <= total; start += PAGE_SEARCH_BATCH) {
      const end = Math.min(start + PAGE_SEARCH_BATCH - 1, total);
      // 批内页码升序构造；Promise.all 只是把同批的提取并行化，不改变顺序语义
      const pages: number[] = [];
      for (let p = start; p <= end; p++) pages.push(p);
      const texts = await Promise.all(pages.map((p) => getPageText(p)));
      for (let i = 0; i < pages.length; i++) {
        if (texts[i] && norm(texts[i]).includes(target)) return pages[i];
      }
    }
    return null;
  };

  // 重新加载 PDF（点重试按钮时调用）
  const retryLoad = () => {
    if (!currentPaperId) return;
    setParseError(null);
    // 重新触发 setCurrentPaper 流程：会清 pdfUrl + 重新 fetch blob
    usePaperStore.getState().setCurrentPaper(currentPaperId);
  };

  // F14: 重新初始化 PDF 渲染器（initPdfJs 失败后的重试入口）。
  // initPdfJs 失败时会清掉缓存的 rejected promise，这里递增 initAttempt 触发 effect 重跑。
  const retryInit = () => {
    setParseError(null);
    setInitAttempt((n) => n + 1);
  };

  // DOCX 在线预览：docx-preview 纯前端渲染（近似分页），失败时组件内部降级为下载兜底
  if (currentFileType === "docx" && currentPaperId) {
    return <DocxViewer paperId={currentPaperId} />;
  }

  // F4: 三态拆分——未选论文（空态）/ PDF 加载中（loading）/ 加载失败（下方错误态）
  if (!currentPaperId) {
    // 设计稿空态：书签带 + 纸页里的「书架还空着」便签，而非空书桌
    return (
      <Desk mainRef={mainRef} containerRef={containerRef} wideContent={false}>
        <div className="docx-note">
          <b>书架还空着</b>
          点右上角「上传」，或拖个 PDF 进来，
          <br />
          边读边拆。
          <div className="mt-5">
            {/* W1-01 §5.1：空状态上传按钮（复用顶栏的上传组件） */}
            <UploadButton onUploaded={(p) => usePaperStore.getState().setCurrentPaper(p.paper_id)}>
              <Button variant="default" size="sm">
                <FileText className="h-4 w-4 mr-1" />
                上传文件
              </Button>
            </UploadButton>
            <div className="text-[11px] mt-3 opacity-70">也可以把文件直接拖进窗口任意位置</div>
          </div>
        </div>
      </Desk>
    );
  }

  // 已选论文但 pdfUrl 未就绪且无错误：居中 loading（旧实现与"未选论文"共用空态，
  // 用户选完论文会看到"从左侧选择一篇论文"的误导文案）。
  // 注意必须带上 !pdfLoadError：store 的错误路径只写 pdfLoadError 不写 pdfUrl
  //（pdfLoadError != null ⟹ pdfUrl === null），漏掉会把下载失败也命中 loading，
  // 下面的错误分支变成死代码
  if (!pdfUrl && !pdfLoadError) {
    return (
      <Desk mainRef={mainRef} containerRef={containerRef} wideContent={false}>
        <div className="docx-note" role="status" aria-live="polite">
          <b>正在摊开这一页…</b>
          论文原文加载中，稍等片刻。
          <br />
          加载失败的话，点右上角网络图标重新检测。
        </div>
      </Desk>
    );
  }

  // 1. PDF 文件下载/读取失败
  if (pdfLoadError) {
    return (
      // wideContent=false：错误便签没有大画布，min-w-fit 会在 375px 视口把
      // 内容带撑出横向滚动（同空态/加载中的处理，P2-5）
      <Desk mainRef={mainRef} containerRef={containerRef} wideContent={false}>
        <div className="px-10 py-16 text-center">
          <AlertCircle className="h-10 w-10 mx-auto mb-3 text-destructive" />
          <div className="font-display text-base font-semibold mb-1 text-foreground">PDF 加载失败</div>
          <div className="text-[12.5px] text-muted-foreground mb-4 break-all leading-relaxed">{pdfLoadError}</div>
          <div className="flex gap-2 justify-center">
            <Button size="sm" variant="default" onClick={retryLoad}>
              <RefreshCw className="h-3 w-3 mr-1" />重新加载
            </Button>
            <Button size="sm" variant="outline" onClick={() => usePaperStore.getState().setCurrentPaper(null)}>
              返回书架
            </Button>
          </div>
        </div>
      </Desk>
    );
  }

  return (
    <Desk
      mainRef={mainRef}
      containerRef={containerRef}
      wrapRef={sheetWrapRef}
      // P2-5/P3: parseError 非空时（解析失败 error 分支 / 渲染器初始化失败 F14 分支）
      // 内容是纯错误便签，无需 min-w-fit（375px 下会横向溢出）；正常态保持 min-w-fit
      // 供缩放 >100% 时纸页随画布撑宽。parseError 在 onLoadSuccess/重试时清空复原。
      wideContent={!parseError}
      foot={
        /* 页脚：翻页圆钮 + 衬线页码（在纸页下方，与设计稿一致） */
        <div className="sheet-foot">
          <button
            className="pn-btn"
            onClick={() => setPage(Math.max(1, page - 1))}
            disabled={page <= 1}
            aria-label="上一页"
          >
            <ChevronLeft className="h-3 w-3" />
          </button>
          <span className="pn" aria-live="polite">· {page} / {numPages || "?"} ·</span>
          <button
            className="pn-btn"
            onClick={() => setPage(Math.min(numPages, page + 1))}
            disabled={page >= numPages}
            aria-label="下一页"
          >
            <ChevronRight className="h-3 w-3" />
          </button>
        </div>
      }
      zoom={
        /* 缩放浮签（书桌右下角） */
        <div className="zoom-pill" role="group" aria-label="缩放控制">
          <button
            onClick={() => setZoom(Math.max(0.5, zoom - 0.1))}
            disabled={zoom <= 0.5 + 1e-9}
            aria-label="缩小"
          >
            <ZoomOut className="h-3.5 w-3.5" />
          </button>
          <span aria-live="polite">{Math.round(zoom * 100)}%</span>
          <button
            onClick={() => setZoom(Math.min(3, zoom + 0.1))}
            disabled={zoom >= 3 - 1e-9}
            aria-label="放大"
          >
            <ZoomIn className="h-3.5 w-3.5" />
          </button>
        </div>
      }
    >
      {pdfjsReady ? (
        /* pdf-holder：纸页内 22px 内边距 + 白底画布居中（app.html .pdf-holder） */
        <div className="pdf-holder">
          <Document
            file={pdfUrl}
            // P0-1：options 必须是稳定引用，原因见模块级 DOCUMENT_OPTIONS 处的注释
            options={DOCUMENT_OPTIONS}
            onLoadSuccess={(doc) => {
              // react-pdf 10：onLoadSuccess 参数直接是 pdfjs 文档对象（PDFDocumentProxy）
              // 不能命名为 numPages：会遮蔽外层同名 state（审查报告 P3-7）
              const total = doc.numPages;
              setNumPages(total);
              numPagesRef.current = total;
              // F2 双保险：页码 state 若仍越界（竞态窗口），clamp 到新文档的有效范围，
              // 避免 <Page> 请求不存在的页报 "Failed to load the page."
              setPage((p) => Math.min(Math.max(1, p), total));
              // 缓存 pdfjs 文档实例 + 清空页文本缓存（全文定位用）
              pdfDocRef.current = doc;
              pageTextCacheRef.current = new Map();
              setParseError(null);
              // A6: 打开新文档默认「适合宽度」（上限 100%），初始就能看全页面；
              // 工具栏百分比显示的就是该实际值。
              // P0-1：只在该文档首次加载时适宽——同一 file（pdfUrl）再次触发
              // onLoadSuccess 时跳过，避免任何意外的重复加载把用户手动缩放
              // 重置回适宽值；不同论文（不同 blob URL）仍要适宽。
              if (pdfUrl && pdfUrl !== lastFittedFileRef.current) {
                lastFittedFileRef.current = pdfUrl;
                void (async () => {
                  const fit = await computeFitWidthScale(doc);
                  if (fit != null) setZoom(fit);
                })();
              }
            }}
            onLoadError={(err) => {
              console.error("PDF parse error:", err);
              setParseError(err?.message || "PDF 解析失败（文件可能已损坏或加密）");
            }}
            loading={<div className="text-muted-foreground p-8">加载 PDF 中…</div>}
            error={
              <div className="text-center max-w-md py-6">
                <FileWarning className="h-10 w-10 mx-auto mb-3 text-destructive" />
                <div className="font-display text-base font-semibold mb-1 text-foreground">PDF 解析失败</div>
                <div className="text-[12.5px] text-muted-foreground mb-4 break-all leading-relaxed">
                  {parseError || "文件可能已损坏、加密或非标准 PDF 格式"}
                </div>
                <div className="flex gap-2 justify-center">
                  <Button size="sm" variant="default" onClick={retryLoad}>
                    <RefreshCw className="h-3 w-3 mr-1" />重新加载
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => usePaperStore.getState().setCurrentPaper(null)}>
                    返回书架
                  </Button>
                </div>
              </div>
            }
          >
            <Page
              pageNumber={page}
              scale={zoom}
              renderTextLayer
              renderAnnotationLayer
              className="bg-white"
            />
          </Document>
        </div>
      ) : parseError ? (
        // F14: 渲染器初始化失败——渲染错误信息 + 重试按钮（此前永远停在"加载 PDF 渲染器..."）
        <div className="px-10 py-16 text-center">
          <FileWarning className="h-10 w-10 mx-auto mb-3 text-destructive" />
          <div className="font-display text-base font-semibold mb-1 text-foreground">PDF 渲染器加载失败</div>
          <div className="text-[12.5px] text-muted-foreground mb-4 break-all leading-relaxed">{parseError}</div>
          <div className="flex gap-2 justify-center">
            <Button size="sm" variant="default" onClick={retryInit}>
              <RefreshCw className="h-3 w-3 mr-1" />重试
            </Button>
          </div>
        </div>
      ) : (
        // lib/pdf 懒加载还没就绪：避免在 workerSrc 覆盖完成前挂载 <Document>，
        // 否则 <Document> 会用 react-pdf 自带的相对路径默认值，导致
        // "No 'GlobalWorkerOptions.workerSrc' specified"。
        <div className="docx-note"><b>加载 PDF 渲染器…</b>首次会拉取渲染脚本，稍等片刻。</div>
      )}
    </Desk>
  );
}

/**
 * 在 text layer 中高亮指定文本
 * 直接遍历 .react-pdf__Page__textContent 下的 <span>，匹配后加 paperpilot-highlight
 * class 并 scrollIntoView。text layer 是异步渲染的，所以用轮询等待（最多 1s）。
 */

function highlightInTextLayer(text: string, isCurrent?: () => boolean): Promise<boolean> {
  return new Promise((resolve) => {
    if (typeof window === "undefined") {
      resolve(false);
      return;
    }

    const candidates = buildSearchCandidates(text);
    if (candidates.length === 0) {
      resolve(false);
      return;
    }

    const MAX_ATTEMPTS = 20; // 20 × 50ms = 1s 上限
    const POLL_MS = 50;
    let attempts = 0;

    const tryFind = () => {
      // 轮询期间用户已发起新跳转 → 本流程作废（不误高亮旧引用）
      if (isCurrent && !isCurrent()) {
        resolve(false);
        return;
      }
      attempts += 1;
      // 等 container 出现且内部 span 就绪（否则会匹配到空 text layer 直接失败）
      const container = document.querySelector<HTMLElement>(".react-pdf__Page__textContent");
      if (!container || container.querySelectorAll("span").length === 0) {
        if (attempts < MAX_ATTEMPTS) {
          setTimeout(tryFind, POLL_MS);
        } else {
          resolve(false);
        }
        return;
      }
      if (isCurrent && !isCurrent()) {
        resolve(false);
        return;
      }
      // 依次尝试候选，任一命中即高亮
      for (const candidate of candidates) {
        if (applyHighlight(container, candidate)) {
          resolve(true);
          return;
        }
      }
      resolve(false);
    };
    tryFind();
  });
}

function applyHighlight(container: HTMLElement, searchText: string): boolean {
  // 1. 清除上次高亮（如果还在 DOM 里）
  clearHighlight();

  // 2. 收集所有 text-bearing leaf spans。react-pdf 的 text layer 可能按行/词/字拆 span，
  //    所以下游比较时要把连续 span 拼起来再判断包含关系。
  const textSpans: HTMLElement[] = [];
  container.querySelectorAll<HTMLElement>("span").forEach((s) => {
    if (s.children.length > 0) return; // 跳过行/容器 span
    const t = s.textContent;
    if (t && t.length > 0) textSpans.push(s);
  });

  // 3. 归一化空白 + 大小写（英文 PDF 容错），避免 react-pdf 把空格切到后一个 span
  //    导致 "foo bar" 拼成 "foobar"
  const norm = (s: string) => s.replace(/\s+/g, " ").toLowerCase();
  const target = norm(searchText);
  // 实测加固（2026-09-09）：该 PDF 的文本层 span 在行边界处会丢失空格（如
  // "five hours.Large"、"single-passsummarization"），上面"空白归一化为单个空格"
  // 的比较会漏掉跨这类边界的候选。兜底：比较前把双方的全部空白都去掉再判断包含。
  // 取舍：去全部空白比逐字匹配宽松，理论上存在极小的误命中风险，但可接受——
  // 候选文本本身来自 LLM 引文（evidence/quote），窗口短（≤30 字符）且语义明确，
  // 误命中概率远小于"行边界空格丢失导致该候选永远匹配不上"的确定性失效。
  const targetStripped = target.replace(/\s+/g, "");

  // 4. 在连续 span 拼起来后寻找首个匹配
  const MAX_RUN = 80;
  for (let i = 0; i < textSpans.length; i++) {
    let acc = "";
    let accStripped = "";
    const run: HTMLElement[] = [];
    for (let j = i; j < Math.min(i + MAX_RUN, textSpans.length); j++) {
      const spanText = textSpans[j].textContent || "";
      acc += spanText;
      // 与 targetStripped 同为去空白 + 小写（norm 已 lowercase，兜底比较大小写须一致）
      accStripped += spanText.replace(/\s+/g, "").toLowerCase();
      run.push(textSpans[j]);
      // 主条件：空白归一化匹配；兜底：双方去全部空白后匹配（行边界丢空格容错）
      if (norm(acc).includes(target) || (targetStripped && accStripped.includes(targetStripped))) {
        // 命中：给整段 run 加 class，记录整段 run 的全部 span（清除/渐隐都要覆盖
        // 整段，P1-2：只记首 span 会残留其余 span），滚到视口
        for (const el of run) el.classList.add("paperpilot-highlight");
        lastHighlightedEls = run;
        run[0].scrollIntoView({ behavior: "smooth", block: "center" });
        // W1-01 §4.1：3 秒后自动渐隐
        fadeHighlightAfterDelay();
        return true;
      }
    }
  }

  // 5. 未命中
  return false;
}
