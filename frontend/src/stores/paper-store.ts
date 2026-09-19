"use client";
import { create } from "zustand";
import { toast } from "sonner";
import { api, API_BASE, consumeSSE } from "@/lib/api";
import type {
  PaperInfo,
  AnalysisType,
  AnalysisResult,
  ChapterInfo,
  PaperResults,
  CompareResponse,
  BreakdownResult,
  InnovationResult,
  FlawsResult,
} from "@/types";

/**
 * 流式分析进度（来自 SSE）
 * - stage:        当前阶段（starting / started / chapters / map / reduce）
 * - completed:    Map 阶段已完成章节数
 * - total:        Map 阶段总章节数
 * - chapters:     章节列表（来自 chapters_detected 事件）
 * - currentChapter: 当前正在 Map 的章节名（来自 map_started 事件）
 */
export interface StreamProgress {
  stage: "starting" | "started" | "chapters" | "map" | "reduce" | string;
  completed: number;
  total: number;
  chapters?: { name: string; page_start: number; page_end: number }[];
  currentChapter?: string;
}

/**
 * SSE data 载荷窄化：后端字段缺失/类型异常时不让 NaN/undefined 进入 UI。
 * （旧实现全部裸 as 断言，payload 异常时 progress 会显示 "undefined / undefined 章节"）
 */
const asRecord = (v: unknown): Record<string, unknown> =>
  (v && typeof v === "object" ? v : {}) as Record<string, unknown>;
const asNum = (v: unknown, fallback = 0): number =>
  typeof v === "number" && Number.isFinite(v) ? v : fallback;
const asStr = (v: unknown, fallback = ""): string =>
  typeof v === "string" ? v : fallback;

/**
 * 空的分析错误集合（F11：analyzeError 单一字段会让 A Tab 的报错串台到 B Tab，
 * 改为按类型记录；切论文/清空时整体复位用）
 */
const EMPTY_ANALYZE_ERRORS: Record<AnalysisType, string | null> = {
  breakdown: null,
  innovation: null,
  flaws: null,
};

/**
 * 当前 SSE 流式分析的 AbortController（cancelAnalysis 用）。
 * analyzeStream 的防并发锁保证全局最多一条流，模块级单槽即可。
 */
let activeStreamController: AbortController | null = null;

/**
 * 已生成的 PPT 信息（generatePPT 响应）。按 paper_id 分组持久在 store：
 * 之前放在 PPTView 组件本地 state，切书签组件卸载即丢——文件明明还在
 * 服务端，UI 却没有任何入口再次下载，只能重新生成。
 */
export interface PPTResult {
  download_url: string;
  filename: string;
  size: number;
  pages: number;
  warnings: string[];
}

export interface PaperState {
  papers: PaperInfo[];  papersLoading: boolean;
  papersLoadError: string | null;
  currentPaperId: string | null;
  currentFileType: "pdf" | "docx" | null;
  pdfFile: File | null;
  pdfUrl: string | null;        // 用于 react-pdf 渲染（docx 不用）
  pdfLoadError: string | null;  // 单独的 PDF 文件下载错误（论文详情 OK 但文件流失败）
  zoom: number;

  // 分析结果：按 paper_id 分组，防止切换论文时 A 的结果污染 B（P0-5/6）
  // compare 由 /api/compare 生成并缓存，也存这里（B4：切走再切回可恢复）
  results: Record<string, Partial<PaperResults>>;
  // 已生成的 PPT（按 paper_id 分组，切书签/切论文回来不丢，见 PPTResult 注释）
  pptResults: Record<string, PPTResult>;
  analyzing: AnalysisType | null;
  // F11: 按分析类型记录错误（原单一 analyzeError 字段会跨 Tab 串台）
  analyzeErrors: Record<AnalysisType, string | null>;
  streamProgress: StreamProgress | null;  // SSE 流式进度（仅 breakdown 用）
  // P1-1：compare / PPT 生成的进行中锁（上收自视图组件本地 state——组件随 activeTab
  // 条件渲染，切书签带即卸载，本地锁丢失后等待期可并发重复发起 LLM 任务）。
  // 值 = 任务发起时刻（Date.now()），null = 空闲；时间戳同时充当所有权令牌：
  // 任务收尾仅在锁仍归属自己时才复位，防止切论文复位后旧任务的 finally 误清新任务的锁
  // （同 analyzeStream finally 的槽位守卫）。PPT 的「已等待 N 秒」计时也读它，重挂不归零。
  compareStartedAt: number | null;
  pptStartedAt: number | null;

  // actions
  fetchPapers: () => Promise<void>;
  upload: (file: File, options?: Parameters<typeof api.upload>[1]) => Promise<PaperInfo>;
  setCurrentPaper: (id: string | null) => Promise<void>;
  removePaper: (id: string) => Promise<void>;
  analyze: (type: AnalysisType, force?: boolean) => Promise<void>;
  /**
   * 流式分析（仅 breakdown 支持）：SSE 边收边更新 streamProgress，
   * reduce_completed 时把结果写进 results[paperId][type]。
   * 失败时把消息写进 analyzeErrors[type]。完成后 analyzing/streamProgress 清空。
   */
  analyzeStream: (type: AnalysisType) => Promise<void>;
  /**
   * 取消进行中的流式分析（仅 breakdown SSE 支持）：中止底层连接并立即解锁 UI。
   * 非流式分析（innovation/flaws）没有取消入口，调用为 no-op。
   */
  cancelAnalysis: () => void;
  /**
   * 记录某论文已生成的 PPT 信息（生成成功时由 PPTView 调用）；
   * 传 null 删除该记录（「重新生成」回到表单）。
   */
  setPptResult: (paperId: string, info: PPTResult | null) => void;
  setZoom: (z: number) => void;
}

export const usePaperStore = create<PaperState>((set, get) => ({
  papers: [],
  papersLoading: false,
  papersLoadError: null,
  currentPaperId: null,
  currentFileType: null,
  pdfFile: null,
  pdfUrl: null,
  pdfLoadError: null,
  zoom: 1.0,
  results: {},
  pptResults: {},
  analyzing: null,
  analyzeErrors: { ...EMPTY_ANALYZE_ERRORS },
  streamProgress: null,
  compareStartedAt: null,
  pptStartedAt: null,

  fetchPapers: async () => {
    set({ papersLoading: true, papersLoadError: null });
    try {
      const data = await api.listPapers();
      set({ papers: data.items, papersLoading: false });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      console.error("fetchPapers failed:", e);
      set({
        papersLoading: false,
        papersLoadError: msg || "论文库加载失败",
      });
    }
  },

  upload: async (file: File, options?: Parameters<typeof api.upload>[1]) => {
    const data = await api.upload(file, options);
    await get().fetchPapers();
    return data;
  },

  setCurrentPaper: async (id: string | null) => {
    // 切论文/关闭论文时中止仍在飞的旧分析流：旧流结果本就会被 stale 守卫丢弃，
    // 提前 abort 让后端立刻停止 LLM 生成（省 token），也消除"旧流数十秒后才
    // stale 退出"的窗口期（窗口期内新论文可再启动分析，正是取消句柄竞态的根源）。
    // 旧流的 catch 走 signal.aborted 分支静默退出，不写错误。
    if (activeStreamController) {
      const stale = activeStreamController;
      activeStreamController = null;
      stale.abort();
    }
    if (!id) {
      set({ currentPaperId: null, currentFileType: null, pdfUrl: null, pdfLoadError: null, analyzeErrors: { ...EMPTY_ANALYZE_ERRORS }, analyzing: null, streamProgress: null, compareStartedAt: null, pptStartedAt: null });
      return;
    }
    // 切换论文时清空状态（P0-5/6：results 改为按 paper_id 分组后，
    // 这里只需清空 analyzing/streamProgress/analyzeErrors，结果在新论文加载时按需读取。
    // P1-1：compare/PPT 进行中锁一并复位，防旧论文的锁串台到新论文；
    // 仍在飞的旧任务由其收尾时的所有权守卫兜底，不会误清之后新任务的锁）
    set({ currentPaperId: id, currentFileType: null, pdfUrl: null, pdfLoadError: null, analyzeErrors: { ...EMPTY_ANALYZE_ERRORS }, analyzing: null, streamProgress: null, compareStartedAt: null, pptStartedAt: null });

    // 竞态防护：每次 await 之后检查 currentPaperId 是否仍是本次的 id。
    // 快速 A→B 切换时，如果 A 的请求比 B 的 setState 晚回来，未检查就直接 setState 会把 B 的 pdfUrl 覆盖成 A 的。
    const isStale = () => get().currentPaperId !== id;

    // 先获取论文详情（拿到 file_type）
    try {
      const detail = await api.getPaper(id);
      if (isStale()) return;
      // detail 是 PaperDetail（含 meta/page_count；列表项 PaperInfo 才是无 meta 的形状）
      const fileType: "pdf" | "docx" = detail.file_type || "pdf";
      set({ currentFileType: fileType });

      // 只有 PDF 才下载并用 react-pdf 渲染
      if (fileType === "pdf") {
        // P1 修复：PDF 下载加 AbortController + 60s 超时（其他 fetch 都已加）
        // 之前是裸 fetch，网络挂起时 setState 卡死，UI 无响应
        // X-API-Key 由服务端 BFF 代理统一附加，客户端无需携带
        const pdfController = new AbortController();
        const pdfTimeoutId = setTimeout(() => pdfController.abort(new Error("PDF 下载超时（60s）")), 60_000);
        let res: Response;
        try {
          res = await fetch(`${API_BASE}/api/papers/${id}/file`, { signal: pdfController.signal });
        } catch (e: unknown) {
          // 网络层失败（断网/CORS/超时）
          clearTimeout(pdfTimeoutId);
          const msg = e instanceof Error ? e.message : String(e);
          if (!isStale()) {
            set({ pdfLoadError: msg || "网络错误：无法连接到后端" });
          }
          return;
        }
        clearTimeout(pdfTimeoutId);
        if (isStale()) return;
        if (res.ok) {
          try {
            const blob = await res.blob();
            // blob() 之后再检查一次：这是覆盖 pdfUrl 的最关键时点
            if (isStale()) return;
            const url = URL.createObjectURL(blob);
            set({ pdfUrl: url, pdfLoadError: null });
          } catch (e: unknown) {
            const msg = e instanceof Error ? e.message : String(e);
            if (!isStale()) {
              set({ pdfLoadError: msg || "PDF 文件读取失败" });
            }
          }
        } else {
          // HTTP 非 2xx：把后端 detail 带出来
          let msg = `下载失败 (HTTP ${res.status})`;
          try {
            const body = await res.json();
            if (body?.detail) msg = typeof body.detail === "string" ? body.detail : `下载失败 (HTTP ${res.status})`;
            else if (body?.message) msg = body.message;
          } catch {
            // 忽略
          }
          if (!isStale()) {
            set({ pdfLoadError: msg });
          }
        }
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      console.error("load paper detail failed:", e);
      if (!isStale()) {
        // 论文详情失败时也给个提示（不只是 console）
        toast.error(`加载论文失败：${msg || "未知错误"}`);
        // P2-1：同时写入 pdfLoadError，让 PDF 区进入"加载失败 + 重新加载"
        // 错误态。否则详情一失败这里早退，pdfUrl/pdfLoadError 双空，
        // pdf-viewer 永远渲染"正在摊开这一页…"loading 分支，无任何重试入口。
        set({ pdfLoadError: msg || "论文详情加载失败" });
      }
      // 详情失败（论文已删/网络断）时早退：不再连打 4 个注定失败的缓存请求
      return;
    }

    // 后台静默加载该论文已有的分析结果（不阻塞 UI）
    // 含 compare（B4）：/api/compare 结果会落服务端缓存，切走再切回时恢复。
    // Promise.all 并行：4 个串行 await 在高延迟下白等 4 倍 RTT
    type CachedEntry = { type: AnalysisType | "compare"; result: unknown };
    const loadOne = async (type: AnalysisType | "compare"): Promise<CachedEntry | null> => {
      if (isStale()) return null;
      try {
        const cached = await api.getAnalysis(id, type);
        return cached?.result ? { type, result: cached.result } : null;
      } catch {
        return null; // 没缓存是正常的，不报错
      }
    };
    const cachedEntries = await Promise.all<CachedEntry | null>([
      loadOne("breakdown"),
      loadOne("innovation"),
      loadOne("flaws"),
      loadOne("compare"),
    ]);
    if (isStale()) return;
    const patch: Partial<PaperResults> = {};
    for (const entry of cachedEntries) {
      if (!entry) continue;
      const { type, result } = entry;
      if (type === "compare") patch.compare = result as CompareResponse;
      else if (type === "breakdown") patch.breakdown = result as BreakdownResult;
      else if (type === "innovation") patch.innovation = result as InnovationResult;
      else patch.flaws = result as FlawsResult;
    }
    if (Object.keys(patch).length > 0) {
      set((s) => ({
        results: { ...s.results, [id]: { ...(s.results[id] || {}), ...patch } },
      }));
    }
  },

  removePaper: async (id: string) => {
    await api.deletePaper(id);
    if (get().currentPaperId === id) {
      // F15: 删除的是当前论文 → 复用 setCurrentPaper(null) 的清理集合
      //（旧实现漏清 analyzing/streamProgress/analyzeErrors，残留状态会锁死/串台到下一篇论文）
      set({ currentPaperId: null, currentFileType: null, pdfUrl: null, pdfLoadError: null, analyzeErrors: { ...EMPTY_ANALYZE_ERRORS }, analyzing: null, streamProgress: null, compareStartedAt: null, pptStartedAt: null });
    }
    // 同时清理该 paper_id 的 results 与 pptResults
    set((s) => {
      const newResults = { ...s.results };
      delete newResults[id];
      const newPpts = { ...s.pptResults };
      delete newPpts[id];
      return { results: newResults, pptResults: newPpts };
    });
    await get().fetchPapers();
  },

  analyze: async (type: AnalysisType, force = false) => {
    const id = get().currentPaperId;
    if (!id) return;

    // F8: 防并发双保险 —— 入口先同步置锁，
    // 否则双击会各自通过缓存检查、并行触发两次 LLM。
    // 有任意分析进行中直接忽略（按钮 disabled 之外的批处理间隙防护）
    if (get().analyzing) return;
    set((s) => ({ analyzing: type, analyzeErrors: { ...s.analyzeErrors, [type]: null } }));

    // 已有缓存且不强制重跑，直接返回（F8: 锁是同步置上的，这里同步释放，无渲染闪烁）
    if (!force && get().results[id]?.[type]) {
      set({ analyzing: null });
      return;
    }

    // 优先读服务端缓存（避免 LLM 重复跑）
    if (!force) {
      try {
        const cached = await api.getAnalysis(id, type);
        if (cached?.result) {
          // 竞态防护：写之前确认 paper 仍是当前 paper（stale 时 setCurrentPaper 已清 analyzing）
          if (get().currentPaperId !== id) return;
          set((s) => ({
            results: { ...s.results, [id]: { ...(s.results[id] || {}), [type]: cached.result } },
            analyzing: null,
          }));
          return;
        }
      } catch {
        // 没缓存，继续走 LLM
      }
    }

    try {
      const data = await api.analyze(id, type);
      // 竞态防护（P0-5）：若用户在分析期间切换了论文，丢弃结果
      if (get().currentPaperId !== id) return;
      set((s) => ({
        results: { ...s.results, [id]: { ...(s.results[id] || {}), [type]: data.result } },
        analyzing: null,
      }));
    } catch (e: unknown) {
      // 同样检查 stale
      if (get().currentPaperId !== id) return;
      const msg = e instanceof Error ? e.message : String(e);
      set((s) => ({ analyzing: null, analyzeErrors: { ...s.analyzeErrors, [type]: msg } }));
    }
  },

  /**
   * 流式分析（POST /api/analyze/stream，SSE 边收边更新进度）
   * 后端事件 → store state 映射：
   *   started           → stage: "started"
   *   chapters_detected → stage: "chapters", total=count, chapters=[...]
   *   map_started       → 保留 progress，更新 currentChapter
   *   map_completed     → 中间事件，由 progress 事件统一更新计数
   *   map_failed        → 同上
   *   progress          → stage=event.stage, completed, total（保留 currentChapter/chapters）
   *   maps_completed    → 中间事件，不改 state
   *   reduce_started    → stage: "reduce"
   *   reduce_completed  → 写 results[type]，清 analyzing/streamProgress
   *   done              → 兜底清（reduce_completed 已清，正常情况下是 no-op）
   *   error             → 写 analyzeErrors[type]，清 analyzing/streamProgress
   * 注意：当前后端 SSE 端点只支持 breakdown，其他 type 会立即发 error 事件。
   */
  analyzeStream: async (type: AnalysisType) => {
    const id = get().currentPaperId;
    // 防并发双保险：任意类型分析进行中直接忽略（与 analyze 的守卫一致）。
    // 旧实现只拦同类型——innovation 分析中切到 breakdown Tab 点"重试"会并发两个
    // LLM 任务，先完成的一方会提前解锁、把另一方的进度条藏掉
    if (!id || get().analyzing) return;

    set((s) => ({
      analyzing: type,
      analyzeErrors: { ...s.analyzeErrors, [type]: null },
      streamProgress: { stage: "starting", completed: 0, total: 0 },
    }));

    // 本流独立 AbortController：切论文/异常退出时中止 fetch，避免旧流悬挂（场景 B）
    const controller = new AbortController();
    activeStreamController = controller;
    // 是否收到过终止事件（reduce_completed / done / error）。
    // P0 兜底只对"流静默结束"判定中断；正常完成的流收尾期若用户重开新流，
    // 兜底不再误杀新流（场景 A：旧流 fallback 误报"分析中断"清掉新流 analyzing）
    let terminated = false;

    // 包装 set：自动跳过 stale 写入（P0-6）
    const safeSet: typeof set = (updater, replace) => {
      if (get().currentPaperId !== id) return;
      set(updater, replace);
    };

    try {
      for await (const ev of consumeSSE("/api/analyze/stream", {
        paper_id: id,
        type,
        paper_language: "中文",
      }, undefined, { signal: controller.signal })) {
        // 每次事件循环都检查 stale，防止在 SSE 流期间切换论文导致结果污染；
        // 同时中止旧流，让后端及时停止生成
        if (get().currentPaperId !== id) {
          controller.abort();
          return;
        }

        switch (ev.event) {
          case "started":
            safeSet({ streamProgress: { stage: "started", completed: 0, total: 0 } });
            break;

          case "chapters_detected": {
            // 后端 chapters_detected.data: { count: number, chapters: ChapterInfo[] }
            const d = asRecord(ev.data);
            safeSet({
              streamProgress: {
                stage: "chapters",
                completed: 0,
                total: asNum(d.count),
                chapters: Array.isArray(d.chapters) ? (d.chapters as ChapterInfo[]) : [],
              },
            });
            break;
          }

          case "map_started": {
            // 后端 map_started.data: { chapter: string }
            const d = asRecord(ev.data);
            safeSet((s) => ({
              streamProgress: {
                ...(s.streamProgress || { stage: "map", completed: 0, total: 0 }),
                stage: "map",
                currentChapter: asStr(d.chapter),
              },
            }));
            break;
          }

          case "map_completed":
          case "map_failed":
          case "fallback_legacy":
          case "maps_completed":
            // 中间事件：Map 结果不存 store，由 progress 事件统一更新计数
            // fallback_legacy 表示走了整篇模式，无需特殊处理
            break;

          case "progress": {
            // 后端 progress.data: { stage?: string, completed: number, total: number }
            const d = asRecord(ev.data);
            safeSet((s) => ({
              streamProgress: {
                ...(s.streamProgress || { stage: "map", completed: 0, total: 0 }),
                stage: asStr(d.stage, "map"),
                completed: asNum(d.completed),
                total: asNum(d.total),
              },
            }));
            break;
          }

          case "reduce_started":
            safeSet((s) => ({
              streamProgress: {
                ...(s.streamProgress || { stage: "reduce", completed: 0, total: 0 }),
                stage: "reduce",
                currentChapter: undefined,
              },
            }));
            break;

          case "reduce_completed": {
            // 后端 reduce_completed.data: { result: AnalysisResult }
            const d = asRecord(ev.data);
            if (!d.result) break; // 异常帧（无 result）不写坏 results
            terminated = true;
            safeSet((s) => ({
              results: {
                ...s.results,
                [id]: { ...(s.results[id] || {}), [type]: d.result as AnalysisResult },
              },
              analyzing: null,
              streamProgress: null,
            }));
            break;
          }

          case "error": {
            // 后端 error.data: { message: string }
            const d = asRecord(ev.data);
            terminated = true;
            safeSet((s) => ({
              analyzing: null,
              analyzeErrors: { ...s.analyzeErrors, [type]: asStr(d.message, "流式分析失败") },
              streamProgress: null,
            }));
            break;
          }

          case "done":
            // reduce_completed 已清过；这里兜底再清一次（幂等）
            terminated = true;
            safeSet({ analyzing: null, streamProgress: null });
            break;
        }
      }

      // P0 兜底：for-await 自然结束（后端流静默关闭、没发 done/error/reduce_completed）时，
      // 只要 analyzing 仍停留在本次 type，说明没有任何终止事件处理过它 → 判定中断，解除锁死。
      // !terminated 守卫：正常完成的流永不误报——流 A 收尾期用户重开的流 B 不被旧流兜底误杀。
      if (!terminated && get().currentPaperId === id && get().analyzing === type) {
        set((s) => ({
          analyzing: null,
          analyzeErrors: { ...s.analyzeErrors, [type]: "分析中断，请重试" },
          streamProgress: null,
        }));
      }
    } catch (e: unknown) {
      // 用户点「取消」（cancelAnalysis 已 abort 本流的 controller、清空槽位并清态）：
      // consumeSSE 会把 abort 翻译成 "请求已取消" 抛到这里。
      // 用「本流 signal 是否被 abort」判定取消——不能看槽位是否为 null：
      // 取消后用户立刻重开新流时，槽位已是新流的 controller，旧判据会把
      // 新流误判成非取消路径，进而清掉新流的 analyzing/写入"请求已取消"错误。
      // 取消时的 UI 清理由 cancelAnalysis 同步完成，这里直接退出即可。
      const cancelledByUser = controller.signal.aborted;
      if (cancelledByUser) {
        return;
      }
      // 兜底中止本流（若已 abort 则幂等）
      controller.abort();
      if (get().currentPaperId !== id) return;
      const msg = e instanceof Error ? e.message : String(e);
      set((s) => ({
        analyzing: null,
        analyzeErrors: { ...s.analyzeErrors, [type]: msg || "流式请求失败" },
        streamProgress: null,
      }));
    } finally {
      // P1-1：条件清理——只有槽位仍指向本流时才清空。
      // 无条件清空会偷走后启动流的取消句柄：切论文后旧流 stale 退出
      // （事件间隔可达数十秒，期间用户已在新论文上启动流 B），旧流的
      // finally 把槽位抹成 null，流 B 的「取消」按钮从此静默失效。
      if (activeStreamController === controller) {
        activeStreamController = null;
      }
    }
  },

  cancelAnalysis: () => {
    const ctrl = activeStreamController;
    if (!ctrl) return;
    ctrl.abort();
    activeStreamController = null;
    // 立即解锁 UI；analyzeStream 的 catch 走 cancelledByUser 分支不再写错误
    set({ analyzing: null, streamProgress: null });
  },

  setPptResult: (paperId, info) => {
    set((s) => {
      const next = { ...s.pptResults };
      if (info === null) delete next[paperId];
      else next[paperId] = info;
      return { pptResults: next };
    });
  },

  setZoom: (z) => set({ zoom: z }),
}));

// ====== ObjectURL 内存泄漏防护 ======
// 每次切换论文都会 URL.createObjectURL() 一个新的 blob URL，
// 旧的不 revoke 会一直占着内存（PDF 几十 MB 一篇）。
// 用 subscribe 统一兜底：pdfUrl 变化时 revoke 掉上一个。
if (typeof window !== "undefined") {
  let lastPdfUrl: string | null = null;
  usePaperStore.subscribe((state) => {
    if (state.pdfUrl !== lastPdfUrl) {
      if (lastPdfUrl) {
        URL.revokeObjectURL(lastPdfUrl);
      }
      lastPdfUrl = state.pdfUrl;
    }
  });

  // 页面卸载 / 刷新时 revoke 当前 url（防意外泄漏）。
  // P3: 改用 pagehide 而非 beforeunload——pagehide 在 bfcache（前进/后退缓存）
  // 恢复场景也会触发（beforeunload 不会），且不会阻止页面进入 bfcache；
  // 清理逻辑不变。
  window.addEventListener("pagehide", () => {
    const url = usePaperStore.getState().pdfUrl;
    if (url) URL.revokeObjectURL(url);
  });
}
