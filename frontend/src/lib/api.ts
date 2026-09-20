// 后端 API 客户端

import type { PaperInfo, PaperDetail, AnalysisResult, CompareResponse, PPTGenerateOptions, SettingsView, SettingsUpdatePayload, SettingsTestPayload, SettingsTestResult } from "@/types";

// API 走 Next.js BFF 代理（src/app/api/proxy/[...path]/route.ts），
// 由服务端转发到后端并附加鉴权密钥，浏览器 bundle 不再包含任何密钥。
// 桌面版（静态导出 + FastAPI 同源托管）构建时传 NEXT_PUBLIC_API_BASE=""
// 直连后端（后端路由本身就是 /api/*）。
const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "/api/proxy";

// 默认超时：30 秒（普通接口）；SSE/分析接口可单独传入更长超时
const DEFAULT_TIMEOUT_MS = 30_000;
// F17: 15 分钟——后端 Map 300s + Reduce 300s 最坏 600s+，10 分钟会在极端情况下误杀正常流
const DEFAULT_SSE_TIMEOUT_MS = 15 * 60 * 1000;
// P3: 文件下载超时 5 分钟——原 60s 对 50MB DOCX（慢速网络下下载 + BFF 转发）
// 偏紧，会误杀正常下载
const DOWNLOAD_TIMEOUT_MS = 300_000;

/** FastAPI 422 验证错误的 detail item 结构（仅在 extractError 内部使用） */
interface ValidationErrorItem {
  loc?: unknown;
  msg?: string;
  type?: string;
}

/**
 * SSE 事件载荷（一条 event: ... + data: ...）
 * data 保持 unknown，调用方按 ev.event 自行 narrow（cast 到具体类型）
 */
export type SSEEvent = { event: string; data: unknown };

/**
 * 判断错误是否为 abort 类（AbortError DOMException，或 abort(reason) 以 reason reject 的 Error）
 */
function isAbortError(e: unknown): boolean {
  return e instanceof Error && (e.name === "AbortError" || e.message.includes("aborted"));
}

/**
 * 用 fetch + ReadableStream 手动解析 SSE 帧（POST 用 EventSource 不行）
 *
 * 用法：
 *   for await (const ev of consumeSSE("/api/analyze/stream", { ... })) {
 *     switch (ev.event) { ... }
 *   }
 *
 * 帧格式：每个事件以 \n\n 结尾，包含 `event: name` 和 `data: json` 两行。
 * - HTTP 非 2xx → 抛错（含 extractError 提取的可读消息）
 * - HTTP 200 但 body 解析出错（如 event: error 帧）→ 由调用方自己处理
 * - 单帧 JSON 解析失败 → 静默忽略（不抛错，不中断流）
 * - 默认 15 分钟超时（可被 options.timeoutMs 覆盖）
 */
export async function* consumeSSE(
  url: string,
  body: Record<string, unknown>,
  headers?: Record<string, string>,
  options: { timeoutMs?: number; signal?: AbortSignal } = {}
): AsyncGenerator<SSEEvent> {
  // 合并外部 signal 与超时 signal
  const controller = new AbortController();
  const timeoutMs = options.timeoutMs ?? DEFAULT_SSE_TIMEOUT_MS;
  // F1 同源修复：超时用局部标志判定，abort 不带 reason
  // （abort(reason) 在部分运行时会让 fetch 直接以 reason reject，
  //  "aborted"/AbortError 判断失效，超时被误报成"网络错误"）
  let timedOut = false;
  const timeoutId = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  // 外部取消同样不带 reason：带 reason 会让 fetch/reader.read() 以 reason reject，
  // 绕过下面的 AbortError 判断，被误译成"网络错误：外部取消"
  const externalAbortHandler = () => controller.abort();
  if (options.signal) {
    if (options.signal.aborted) {
      clearTimeout(timeoutId);
      throw new Error("请求已取消");
    }
    options.signal.addEventListener("abort", externalAbortHandler);
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${url}`, {
      method: "POST",
      headers: buildHeaders(headers),
      body: JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (e: unknown) {
    clearTimeout(timeoutId);
    if (options.signal) options.signal.removeEventListener("abort", externalAbortHandler);
    // F1: 超时/取消转译（timedOut 标志优先于错误形态判断）
    if (timedOut || isAbortError(e) || options.signal?.aborted) {
      throw new Error(timedOut ? "请求超时" : "请求已取消");
    }
    throw new Error(`网络错误：${e instanceof Error ? e.message : String(e)}`);
  }

  if (!res.ok || !res.body) {
    clearTimeout(timeoutId);
    if (options.signal) options.signal.removeEventListener("abort", externalAbortHandler);
    const message = await extractError(res, `HTTP ${res.status}`);
    throw new Error(message);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      // CRLF 归一在 buf 层做：逐 chunk 替换会漏掉跨 chunk 边界的 \r\n
      // （chunk1 尾 \r + chunk2 首 \n）。帧被及时消费，buf 只保留未成帧残余，重扫成本可忽略
      buf = buf.replace(/\r\n/g, "\n");
      let sep;
      while ((sep = buf.indexOf("\n\n")) !== -1) {
        const frame = buf.slice(0, sep);
        buf = buf.slice(sep + 2);
        let eventName = "message";
        let dataStr = "";
        for (const line of frame.split("\n")) {
          if (line.startsWith("event: ")) eventName = line.slice(7).trim();
          else if (line.startsWith("data: ")) {
            // SSE 规范：同一事件的多行 data 以 \n 连接（直接拼接会把多行 JSON 黏成非法串）
            dataStr = dataStr ? `${dataStr}\n${line.slice(6)}` : line.slice(6);
          }
        }
        if (dataStr) {
          try {
            yield { event: eventName, data: JSON.parse(dataStr) };
          } catch {
            // 忽略无法解析的帧（不中断流）
          }
        }
      }
    }
  } catch (e: unknown) {
    // F1: 读流阶段（可能持续 15 分钟）的超时/取消必须在此转译——
    // 之前 AbortError 直接穿透 generator（只有 finally 没有 catch），
    // analyzeStream 会把英文 "This operation was aborted" 原样写进 analyzeErrors；
    // 非 abort 错误（如连接中途重置）原样抛出，保持旧行为
    if (timedOut || isAbortError(e) || options.signal?.aborted) {
      throw new Error(timedOut ? "请求超时" : "请求已取消");
    }
    throw e;
  } finally {
    // 流结束或异常时清理；generator 被 break/return 提前退出时主动断开底层连接，
    // 不再依赖外层 abort signal 才关闭
    clearTimeout(timeoutId);
    if (options.signal) options.signal.removeEventListener("abort", externalAbortHandler);
    try { await reader.cancel(); } catch { /* already closed */ }
    try { reader.releaseLock(); } catch { /* ignore */ }
  }
}

/**
 * 构造请求 headers：自动带上 X-API-Key（如果配置了）
 */
function buildHeaders(extra?: Record<string, string>): Record<string, string> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  // X-API-Key 由服务端 BFF 代理统一附加，这里不再携带
  return { ...headers, ...(extra || {}) };
}

/**
 * 从错误响应里提取可读消息（401/413/429/5xx 等）
 *
 * 后端错误响应字段优先级：
 *   1. body.detail        —— FastAPI HTTPException(detail=...) 默认字段（最常见）
 *   2. body.message       —— 项目自定义 ApiResponse(code!=0) 的字段
 *   3. body.error         —— 部分中间件/SDK 使用
 *   4. 纯文本 body        —— 上游代理/网关直接返回的文本
 *   5. fallback "HTTP <status>" —— 兜底
 *
 * 之前的实现只查 body.message，FastAPI 抛 HTTPException(detail=...) 时拿不到具体原因，
 * 用户看到的全是 "HTTP 400"，文件过大、PDF 损坏、论文不存在等错误都看不出来了。
 */
async function extractError(res: Response, fallback: string): Promise<string> {
  const tryReadString = (v: unknown): string | null => {
    if (typeof v === "string" && v.trim()) return v;
    if (Array.isArray(v) && v.length > 0) {
      // Pydantic validation_error 返 detail: [{loc, msg, type}, ...]
      const flat = v
        .map((item: unknown) => {
          if (typeof item === "string") return item;
          if (item && typeof item === "object") {
            const obj = item as ValidationErrorItem;
            const loc = Array.isArray(obj.loc) ? obj.loc.join(".") : "";
            const msg = obj.msg || "";
            return loc ? `${loc}: ${msg}` : msg;
          }
          return "";
        })
        .filter(Boolean)
        .join("; ");
      return flat || null;
    }
    return null;
  };

  // 1. JSON 解析优先（detail / message / error）
  try {
    const body = await res.clone().json();
    if (body && typeof body === "object") {
      const candidates = [body.detail, body.message, body.error];
      for (const c of candidates) {
        const s = tryReadString(c);
        if (s) return s;
      }
    }
  } catch {
    // 不是 JSON 响应，下一步
  }

  // 2. 尝试纯文本（有些反代/网关直接返 text/plain）
  try {
    const text = await res.text();
    if (text && text.trim()) return text.trim();
  } catch {
    // 忽略
  }

  // 3. 兜底：HTTP 状态码 + 后端限流带的 Retry-After 提示
  let suffix = "";
  const retryAfter = res.headers.get("Retry-After");
  if (retryAfter) {
    const sec = Number(retryAfter);
    if (Number.isFinite(sec) && sec > 0) {
      suffix = `，请在 ${Math.ceil(sec)} 秒后重试`;
    }
  }
  return `${fallback}${suffix}`;
}

async function request<T>(
  path: string,
  options: RequestInit & { timeoutMs?: number; allowCodes?: number[] } = {}
): Promise<T> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, allowCodes = [], ...init } = options;

  // AbortController + 超时
  // F1: 超时用局部标志判定，abort 不带 reason。之前 abort(new Error("请求超时"))
  // 会让 fetch 以该 reason reject，下面的 AbortError 分支失效，超时被误报成"网络错误"。
  const controller = new AbortController();
  let timedOut = false;
  const timeoutId = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  // 透传调用方 signal
  let onAbort: (() => void) | undefined;
  if (init.signal) {
    if (init.signal.aborted) {
      clearTimeout(timeoutId);
      throw new Error("请求已取消");
    }
    onAbort = () => controller.abort();
    init.signal.addEventListener("abort", onAbort);
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      signal: controller.signal,
      headers: buildHeaders(init.headers as Record<string, string> | undefined),
    });
  } catch (e: unknown) {
    clearTimeout(timeoutId);
    // 复用 AbortController 时避免监听器累积
    if (init.signal && onAbort) init.signal.removeEventListener("abort", onAbort);
    // F1: 超时优先用标志判定（signal.aborted 也可能由外部取消触发，不能区分两者）
    if (timedOut) throw new Error("请求超时");
    if (isAbortError(e)) throw new Error("请求已取消");
    throw new Error(`网络错误：${e instanceof Error ? e.message : String(e)}`);
  }
  clearTimeout(timeoutId);
  if (init.signal && onAbort) init.signal.removeEventListener("abort", onAbort);

  if (!res.ok) {
    const message = await extractError(res, `HTTP ${res.status}`);
    throw new Error(message);
  }
  // 200 但 body 不是 JSON（反代/网关故障页、HTML 错误页等）：给可读消息而不是
  // 把 "Unexpected token '<'" 这类 SyntaxError 原样抛给用户
  let json: { code?: unknown; message?: unknown; data?: unknown };
  try {
    json = await res.json();
  } catch {
    throw new Error(`HTTP ${res.status}：响应不是有效 JSON（可能网关/代理异常）`);
  }
  if (json.code !== 0) {
    // 业务非致命码（如 4001「未搜到相关工作」）：返回 data 让调用方渲染空态，而不是抛错
    if (allowCodes.includes(json.code as number)) {
      return json.data as T;
    }
    throw new Error(
      (typeof json.message === "string" && json.message) || "API error"
    );
  }
  return json.data as T;
}

/**
 * 从 Content-Disposition 头解析文件名（C7）。
 * 优先 RFC5987 格式 filename*=UTF-8''...（decodeURIComponent 解码，中文文件名），
 * 回退 filename="..." / filename=token。解析失败返回 null。
 * 单独导出便于单测。
 */
export function parseContentDispositionFilename(header: string | null): string | null {
  if (!header) return null;
  // 1. RFC5987: filename*=UTF-8''%E6%8A%A5%E5%91%8A.pptx（兼容 charset 后带引号的变体）
  const rfc5987 = header.match(/filename\*\s*=\s*(?:[\w-]+)?'[^']*'([^;]+)/i);
  if (rfc5987?.[1]) {
    try {
      const decoded = decodeURIComponent(rfc5987[1].trim().replace(/^"|"$/g, ""));
      if (decoded) return decoded;
    } catch {
      // 解码失败继续走普通 filename
    }
  }
  // 2. filename="..."（带引号）或 filename=token（不带引号）
  const plain = header.match(/filename\s*=\s*(?:"([^"]+)"|([^;\s]+))/i);
  if (plain) {
    const value = (plain[1] ?? plain[2] ?? "").trim();
    if (value) return value;
  }
  return null;
}

/**
 * 带鉴权的文件下载：fetch(blob) → URL.createObjectURL → 临时 <a download> → revoke。
 * 相比 window.open / 裸 <a href>：能走 BFF 代理（附带头部），且不会被弹窗拦截。
 * 供 DOCX / PPT 下载复用。
 * 文件名优先级（C7）：显式传入的 filename > 响应头 Content-Disposition > 浏览器默认。
 */
export async function downloadBlob(path: string, filename?: string): Promise<void> {
  const controller = new AbortController();
  const timeoutId = setTimeout(
    () => controller.abort(new Error(`下载超时（${DOWNLOAD_TIMEOUT_MS / 1000}s）`)),
    DOWNLOAD_TIMEOUT_MS
  );
  try {
    const res = await fetch(`${API_BASE}${path}`, { signal: controller.signal });
    if (!res.ok) {
      const message = await extractError(res, `HTTP ${res.status}`);
      throw new Error(message);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename || parseContentDispositionFilename(res.headers.get("Content-Disposition")) || "";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } finally {
    clearTimeout(timeoutId);
  }
}

export const api = {
  health: () => request<{ status: string; version?: string }>("/api/health"),

  // 设置（网页端供应商配置）。连接测试最长等 60s——后端会真实探测外部 LLM / 搜索 API
  settings: {
    get: () => request<SettingsView>("/api/settings"),
    update: (body: SettingsUpdatePayload) =>
      request<SettingsView>("/api/settings", {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    test: (body: SettingsTestPayload) =>
      request<SettingsTestResult>("/api/settings/test", {
        method: "POST",
        body: JSON.stringify(body),
        timeoutMs: 60_000,
      }),
  },

  // 上传（P2-12: 支持 XHR onprogress 真实进度）
  upload: (
    file: File,
    options: {
      timeoutMs?: number;
      signal?: AbortSignal;
      onProgress?: (loaded: number, total: number) => void;
    } = {}
  ): Promise<PaperInfo> => {
    return new Promise<PaperInfo>((resolve, reject) => {
      const form = new FormData();
      form.append("file", file);

      // 用 XHR 才能拿到 onprogress 事件（fetch 不支持）
      // X-API-Key 由服务端 BFF 代理统一附加
      const xhr = new XMLHttpRequest();
      const timeoutMs = options.timeoutMs ?? 5 * 60 * 1000; // 5 分钟
      // settled 标志：保证 reject/resolve 只执行一次，
      // 避免 timeout → xhr.abort() → abort 事件抢先用「上传已取消」覆盖「上传超时」。
      let settled = false;
      let timeoutId: ReturnType<typeof setTimeout> | undefined;

      const settle = (fn: () => void) => {
        if (settled) return;
        settled = true;
        clearTimeout(timeoutId);
        if (options.signal) options.signal.removeEventListener("abort", externalAbort);
        fn();
      };

      const externalAbort = () =>
        settle(() => {
          xhr.abort();
          reject(new Error("上传已取消"));
        });

      timeoutId = setTimeout(
        () =>
          settle(() => {
            xhr.abort();
            reject(new Error("上传超时"));
          }),
        timeoutMs
      );

      if (options.signal) {
        if (options.signal.aborted) {
          settle(() => reject(new Error("上传已取消")));
          return;
        }
        options.signal.addEventListener("abort", externalAbort);
      }

      xhr.upload.addEventListener("progress", (e) => {
        if (e.lengthComputable && options.onProgress) {
          options.onProgress(e.loaded, e.total);
        }
      });

      xhr.addEventListener("load", () => {
        settle(() => {
          if (xhr.status >= 200 && xhr.status < 300) {
            try {
              const json = JSON.parse(xhr.responseText);
              if (json.code !== 0) {
                reject(new Error(json.message || "API error"));
              } else {
                resolve(json.data as PaperInfo);
              }
            } catch (e: unknown) {
              const msg = e instanceof Error ? e.message : String(e);
              reject(new Error(`响应解析失败: ${msg}`));
            }
          } else {
            // 非 2xx：构造临时 Response 对象复用 extractError
            // 注意 header 值可能含 ": "（如带引号文件名的 Content-Disposition），
            // 必须按第一个冒号切一次，split(": ") 会截断值
            const fakeRes = new Response(xhr.responseText, {
              status: xhr.status,
              statusText: xhr.statusText,
              headers: xhr.getAllResponseHeaders().split("\r\n").reduce(
                (acc, line) => {
                  const idx = line.indexOf(":");
                  if (idx > 0) {
                    const k = line.slice(0, idx).trim();
                    const v = line.slice(idx + 1).trim();
                    if (k && v) acc[k] = v;
                  }
                  return acc;
                },
                {} as Record<string, string>
              ),
            });
            extractError(fakeRes, `HTTP ${xhr.status}`).then(reject, reject);
          }
        });
      });

      xhr.addEventListener("error", () => {
        settle(() => reject(new Error("网络错误：上传失败")));
      });

      // timeout / 外部取消已在 settle 里处理，这里兜底网络层主动 abort
      xhr.addEventListener("abort", () => {
        settle(() => reject(new Error("上传已取消")));
      });

      xhr.open("POST", `${API_BASE}/api/upload`, true);
      xhr.send(form);
    });
  },

  // 论文库
  listPapers: () => request<{ total: number; items: PaperInfo[] }>("/api/papers"),
  getPaper: (id: string) => request<PaperDetail>(`/api/papers/${id}`),
  // 后端 ApiResponse.data 恒为 null（只有 message="已删除"）
  deletePaper: (id: string) => request<null>(`/api/papers/${id}`, { method: "DELETE" }),

  // 分析（LLM 调用耗时较长，默认 30s 会误报超时——F1: 显式放宽）。
  // 360s > 后端整体超时 300s（LLM_TIMEOUT_SECONDS）：前端超时必须留出网络余量，
  // 否则前端先 abort 报"请求超时"而后端任务仍在跑
  analyze: (paper_id: string, type: string, paper_language = "中文") =>
    request<{ type: string; result: AnalysisResult; elapsed_ms: number }>("/api/analyze", {
      method: "POST",
      body: JSON.stringify({ paper_id, type, paper_language }),
      timeoutMs: 360_000,
    }),

  getAnalysis: (paper_id: string, type: string) =>
    request<{ type: string; result: AnalysisResult }>(`/api/analyze/${paper_id}/${type}`),

  // W4 联网搜 + LLM 对比（基于 1 篇主论文 + 搜索相关工作）
  // 端点: POST /api/compare
  // 入参: { paper_id, max_results, paper_language }
  // code=4001（未搜到相关工作/供应商未配置）不抛错，返回空数据渲染空态
  // 600s ≈ 后端最坏路径（搜索重试 ~186s + LLM 300s）+ 余量
  compare: (paper_id: string, options: { max_results?: number; paper_language?: string } = {}) =>
    request<CompareResponse>("/api/compare", {
      method: "POST",
      body: JSON.stringify({ paper_id, max_results: options.max_results ?? 5, paper_language: options.paper_language ?? "中文" }),
      allowCodes: [4001],
      timeoutMs: 600_000,
    }),

  // W5 多篇库内论文对比（用户已上传的多篇论文）
  // 端点: POST /api/compare-papers
  // 入参: { paper_ids: 2-5 篇, main_id 必须在 paper_ids 中, paper_language }
  comparePapers: (paper_ids: string[], main_id: string, options: { paper_language?: string } = {}) =>
    request<CompareResponse>("/api/compare-papers", {
      method: "POST",
      body: JSON.stringify({ paper_ids, main_id, paper_language: options.paper_language ?? "中文" }),
      timeoutMs: 600_000,
    }),

  // W6 PPT（C5: 后端从不返回 task_id/status，新增 warnings 字段）
  generatePPT: (paper_id: string, options: PPTGenerateOptions = {}) =>
    request<{ download_url?: string; filename?: string; size?: number; pages?: number; warnings?: string[] }>("/api/generate-ppt", {
      method: "POST",
      body: JSON.stringify({ paper_id, ...options }),
      timeoutMs: 300_000,
    }),
};

export { API_BASE };
