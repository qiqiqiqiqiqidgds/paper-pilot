/**
 * api.ts 测试（B2：code=4001 软失败分支 + consumeSSE 帧解析）
 * 通过 mock 全局 fetch 验证 request/consumeSSE 行为，不打真实网络。
 */
import { afterEach, describe, expect, it, vi } from "vitest";

// 保存原始 fetch，测试后恢复
const originalFetch = globalThis.fetch;

function mockFetchOnce(impl: (url: string, init?: RequestInit) => Promise<Response>) {
  const spy = vi.fn(impl);
  vi.stubGlobal("fetch", spy);
  return spy;
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("api.compare code=4001 (allowCodes)", () => {
  it("returns data instead of throwing when code=4001 and allowed", async () => {
    const { api } = await import("@/lib/api");
    const data = { main_paper: {}, related_papers: [], compare_table: [], summary: "" };
    const spy = mockFetchOnce(() => Promise.resolve(jsonResponse({ code: 4001, message: "未搜到相关工作", data })));

    const result = await api.compare("p_1", { max_results: 5 });
    expect(result).toEqual(data); // 不抛错，返回空数据渲染空态
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("still throws for other non-zero codes", async () => {
    const { api } = await import("@/lib/api");
    mockFetchOnce(() => Promise.resolve(jsonResponse({ code: 5001, message: "服务器错误", data: null })));
    await expect(api.compare("p_1")).rejects.toThrow("服务器错误");
  });

  it("still throws for HTTP errors", async () => {
    const { api } = await import("@/lib/api");
    mockFetchOnce(() => Promise.resolve(jsonResponse({ detail: "论文不存在" }, 404)));
    await expect(api.compare("p_1")).rejects.toThrow("论文不存在");
  });
});

describe("consumeSSE frame parsing", () => {
  it("parses event + data frames and yields in order", async () => {
    const { consumeSSE } = await import("@/lib/api");
    const body =
      "event: started\ndata: {\"paper_id\":\"p1\"}\n\n" +
      "event: progress\ndata: {\"completed\":1,\"total\":3}\n\n" +
      "event: done\ndata: {\"result\":{}}\n\n";
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(body));
        controller.close();
      },
    });
    mockFetchOnce(() => Promise.resolve(new Response(stream, { status: 200 })));

    const events: { event: string; data: unknown }[] = [];
    for await (const ev of consumeSSE("/api/analyze/stream", { paper_id: "p1", type: "breakdown" })) {
      events.push(ev);
    }
    expect(events.map((e) => e.event)).toEqual(["started", "progress", "done"]);
    expect(events[1].data).toEqual({ completed: 1, total: 3 });
  });

  it("skips frames with invalid JSON without breaking the stream", async () => {
    const { consumeSSE } = await import("@/lib/api");
    const body =
      "event: started\ndata: {broken json\n\n" +
      "event: done\ndata: {\"ok\":true}\n\n";
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(body));
        controller.close();
      },
    });
    mockFetchOnce(() => Promise.resolve(new Response(stream, { status: 200 })));

    const events: { event: string; data: unknown }[] = [];
    for await (const ev of consumeSSE("/api/analyze/stream", { paper_id: "p1", type: "breakdown" })) {
      events.push(ev);
    }
    expect(events.map((e) => e.event)).toEqual(["done"]);
  });

  it("throws readable message on HTTP error", async () => {
    const { consumeSSE } = await import("@/lib/api");
    mockFetchOnce(() => Promise.resolve(jsonResponse({ detail: "论文不存在" }, 404)));
    await expect(
      (async () => {
        for await (const _ of consumeSSE("/api/analyze/stream", { paper_id: "x", type: "breakdown" })) {
          /* noop */
        }
      })()
    ).rejects.toThrow("论文不存在");
  });
});

// 防止未使用告警：保留 originalFetch 引用用于说明
void originalFetch;

/**
 * F1：超时错误文案。
 * 修复前：controller.abort(new Error("请求超时")) 携带 reason，fetch 直接以 reason reject，
 * "aborted"/AbortError 判断失效，超时被误报成「网络错误：…」。
 * 修复后：abort 不带 reason，用局部标志判定 → 抛出明确的「请求超时」。
 */
function hangingFetch(impl?: (url: string, init?: RequestInit) => void) {
  return mockFetchOnce((url, init) => new Promise<Response>((_resolve, reject) => {
    // 模拟真实 fetch：signal abort 后以 AbortError reject
    init?.signal?.addEventListener("abort", () => {
      impl?.(url, init);
      const err = new Error("This operation was aborted");
      err.name = "AbortError";
      reject(err);
    });
  }));
}

describe("request 超时（F1）", () => {
  it("默认 30s 超时抛出明确的「请求超时」而不是「网络错误」", async () => {
    vi.useFakeTimers();
    try {
      const { api } = await import("@/lib/api");
      hangingFetch();
      const p = api.health(); // DEFAULT_TIMEOUT_MS = 30s
      const assertion = expect(p).rejects.toThrow("请求超时");
      await vi.advanceTimersByTimeAsync(30_001);
      await assertion;
    } finally {
      vi.useRealTimers();
    }
  });

  it("compare 使用 600s 超时（30s/300s 时不超时；> 后端搜索重试+LLM 最坏路径）", async () => {
    vi.useFakeTimers();
    try {
      const { api } = await import("@/lib/api");
      hangingFetch();
      const p = api.compare("p_1");
      let rejected = false;
      p.catch(() => { rejected = true; });
      // 默认超时点（30s）与 analyze 旧值（300s）时请求仍在进行
      await vi.advanceTimersByTimeAsync(300_000);
      expect(rejected).toBe(false);
      // 推进到 600s+1ms → 超时
      const assertion = expect(p).rejects.toThrow("请求超时");
      await vi.advanceTimersByTimeAsync(300_001);
      await assertion;
    } finally {
      vi.useRealTimers();
    }
  });

  it("analyze 使用 360s 超时（> 后端 LLM_TIMEOUT_SECONDS=300s，留网络余量）", async () => {
    vi.useFakeTimers();
    try {
      const { api } = await import("@/lib/api");
      hangingFetch();
      const p = api.analyze("p_1", "innovation");
      let rejected = false;
      p.catch(() => { rejected = true; });
      // 300s（后端整体超时点）时前端不应先超时
      await vi.advanceTimersByTimeAsync(300_000);
      expect(rejected).toBe(false);
      const assertion = expect(p).rejects.toThrow("请求超时");
      await vi.advanceTimersByTimeAsync(60_001);
      await assertion;
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("consumeSSE 读流阶段超时/取消转译（F1）", () => {
  /** 挂起的流：signal abort 后以 AbortError error（模拟 reader.read() 被 abort 打断） */
  function abortableBody(signal?: AbortSignal | null) {
    return new ReadableStream<Uint8Array>({
      start(controller) {
        signal?.addEventListener("abort", () => {
          const err = new Error("This operation was aborted");
          err.name = "AbortError";
          controller.error(err);
        });
      },
    });
  }

  it("读流阶段超时转译为「请求超时」（此前 AbortError 直接穿透 generator）", async () => {
    vi.useFakeTimers();
    try {
      const { consumeSSE } = await import("@/lib/api");
      mockFetchOnce((_url, init) => Promise.resolve(new Response(abortableBody(init?.signal), { status: 200 })));
      const collect = (async () => {
        for await (const _ of consumeSSE("/api/analyze/stream", { paper_id: "p1" }, undefined, { timeoutMs: 1_000 })) {
          /* noop：流挂起，不产生事件 */
        }
      })();
      const assertion = expect(collect).rejects.toThrow("请求超时");
      await vi.advanceTimersByTimeAsync(1_001);
      await assertion;
    } finally {
      vi.useRealTimers();
    }
  });

  it("外部取消（读流阶段）转译为「请求已取消」而不是「网络错误」", async () => {
    const { consumeSSE } = await import("@/lib/api");
    const ac = new AbortController();
    mockFetchOnce(() => Promise.resolve(new Response(abortableBody(ac.signal), { status: 200 })));
    const collect = (async () => {
      for await (const _ of consumeSSE("/api/analyze/stream", { paper_id: "p1" }, undefined, { signal: ac.signal })) {
        /* noop：流挂起，不产生事件 */
      }
    })();
    await new Promise((r) => setTimeout(r, 0)); // 等流开始读取
    ac.abort();
    await expect(collect).rejects.toThrow("请求已取消");
  });
});

describe("parseContentDispositionFilename (C7)", () => {
  it("优先解析 RFC5987 filename*=UTF-8'' 并 decodeURIComponent", async () => {
    const { parseContentDispositionFilename } = await import("@/lib/api");
    expect(
      parseContentDispositionFilename("attachment; filename*=UTF-8''%E6%B1%87%E6%8A%A5.pptx")
    ).toBe("汇报.pptx");
  });

  it("RFC5987 优先于普通 filename", async () => {
    const { parseContentDispositionFilename } = await import("@/lib/api");
    expect(
      parseContentDispositionFilename("attachment; filename=\"report.pptx\"; filename*=UTF-8''%E6%B1%87%E6%8A%A5.pptx")
    ).toBe("汇报.pptx");
  });

  it("回退到 filename=\"...\"（带引号）", async () => {
    const { parseContentDispositionFilename } = await import("@/lib/api");
    expect(parseContentDispositionFilename("attachment; filename=\"report.pptx\"")).toBe("report.pptx");
  });

  it("回退到不带引号的 token", async () => {
    const { parseContentDispositionFilename } = await import("@/lib/api");
    expect(parseContentDispositionFilename("attachment; filename=report.pptx")).toBe("report.pptx");
  });

  it("无 filename 或空头返回 null", async () => {
    const { parseContentDispositionFilename } = await import("@/lib/api");
    expect(parseContentDispositionFilename("attachment")).toBeNull();
    expect(parseContentDispositionFilename(null)).toBeNull();
  });
});
