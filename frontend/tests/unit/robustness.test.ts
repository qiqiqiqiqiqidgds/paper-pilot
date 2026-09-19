/**
 * 2026-09 健壮性修复回归测试（前端）
 *
 * 全部走 @/lib/api 的真实实现（stub global fetch），不做模块级 mock：
 * - consumeSSE：CRLF 帧分隔、多行 data 按 SSE 规范以 \n 连接、
 *   提前 break 时 reader.cancel 被调用（不再依赖外层 abort）
 * - request()：200 + 非 JSON body（网关故障页）→ 可读错误而非 "Unexpected token"
 * - analyzeStream：任意类型分析进行中时禁止并发触发（旧实现只拦同类型）
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, consumeSSE } from "@/lib/api";
import { usePaperStore, type PaperState } from "@/stores/paper-store";

const tick = () => new Promise((r) => setTimeout(r, 0));
const encoder = new TextEncoder();

/** 手写最小 Response 替身：consumeSSE 只用 ok/body.getReader() 三个成员 */
function fakeSSEResponse(chunks: string[]) {
  let i = 0;
  const calls = { cancelled: false, fetched: false };
  const res = {
    ok: true,
    status: 200,
    body: {
      getReader() {
        return {
          read: async () =>
            i < chunks.length
              ? { value: encoder.encode(chunks[i++]), done: false }
              : { value: undefined, done: true },
          cancel: async () => {
            calls.cancelled = true;
            i = chunks.length;
          },
          releaseLock: () => {},
        };
      },
    },
    calls,
  };
  const fetchMock = vi.fn(async () => {
    calls.fetched = true;
    return res;
  });
  return { res, fetchMock };
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("consumeSSE 解析容错", () => {
  it("CRLF（\\r\\n）帧也能正常解析", async () => {
    const { fetchMock } = fakeSSEResponse(["event: started\r\ndata: {\"a\": 1}\r\n\r\n"]);
    vi.stubGlobal("fetch", fetchMock);

    const events = [];
    for await (const ev of consumeSSE("/api/analyze/stream", {})) {
      events.push(ev);
    }
    expect(events).toEqual([{ event: "started", data: { a: 1 } }]);
  });

  it("多行 data 以 \\n 连接后在 token 边界分割的 JSON 仍可解析", async () => {
    // JSON 字符串内部不允许裸换行，所以合法的多行 data 分割点只能在 token 之间
    // （\n 是合法 JSON 空白）。此处验证 join 路径（旧实现是无分隔符拼接）。
    const { fetchMock } = fakeSSEResponse([
      'event: msg\ndata: {"a": [1, 2,\ndata: 3]}\n\n',
    ]);
    vi.stubGlobal("fetch", fetchMock);

    const events = [];
    for await (const ev of consumeSSE("/x", {})) events.push(ev);
    expect(events[0]?.data).toEqual({ a: [1, 2, 3] });
  });

  it("提前 break 退出时调用 reader.cancel 主动断开底层连接", async () => {
    const { fetchMock, res } = fakeSSEResponse([
      'event: a\ndata: {"n": 1}\n\n',
      'event: b\ndata: {"n": 2}\n\n', // 永远不会被消费
    ]);
    vi.stubGlobal("fetch", fetchMock);

    for await (const ev of consumeSSE("/x", {})) {
      void ev;
      break; // 模拟调用方提前退出
    }
    await tick();
    expect(res.calls.cancelled).toBe(true);
  });
});

describe("request() 200 + 非 JSON body", () => {
  it("网关返回 HTML 错误页时抛可读错误而非 SyntaxError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response("<html>Bad Gateway</html>", {
          status: 200,
          headers: { "content-type": "text/html" },
        })
      )
    );
    await expect(api.health()).rejects.toThrow(/响应不是有效 JSON/);
  });

  it("正常 JSON 响应不受影响", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json({ code: 0, message: "ok", data: { status: "ok" } })
      )
    );
    const data = await api.health();
    expect(data.status).toBe("ok");
  });
});

describe("analyzeStream 并发锁", () => {
  // Partial<PaperState> 标注：setState 接受部分状态，且 analyzing 等
  // 字段类型由 PaperState 推导（手写 string | null 会与 AnalysisType | null 冲突）
  const baseState: Partial<PaperState> = {
    papers: [],
    papersLoading: false,
    papersLoadError: null,
    currentPaperId: "p1",
    currentFileType: "pdf",
    pdfUrl: null,
    pdfLoadError: null,
    zoom: 1,
    results: {},
    analyzing: null,
    analyzeErrors: { breakdown: null, innovation: null, flaws: null },
    streamProgress: null,
  };

  beforeEach(() => {
    usePaperStore.setState({ ...baseState });
  });

  it("其他类型分析进行中时，analyzeStream 不应发起新流", async () => {
    const { fetchMock } = fakeSSEResponse(['event: started\ndata: {}\n\n']);
    vi.stubGlobal("fetch", fetchMock);
    usePaperStore.setState({ analyzing: "innovation" });

    await usePaperStore.getState().analyzeStream("breakdown");

    expect(fetchMock).not.toHaveBeenCalled();
    // 锁未被破坏
    expect(usePaperStore.getState().analyzing).toBe("innovation");
    expect(usePaperStore.getState().streamProgress).toBeNull();
  });

  it("空闲时正常发起流并处理 error 事件", async () => {
    const { fetchMock } = fakeSSEResponse([
      'event: started\ndata: {}\n\n',
      'event: error\ndata: {"message": "stop"}\n\n',
    ]);
    vi.stubGlobal("fetch", fetchMock);

    await usePaperStore.getState().analyzeStream("breakdown");
    expect(fetchMock).toHaveBeenCalled();
    expect(usePaperStore.getState().analyzing).toBeNull();
    expect(usePaperStore.getState().analyzeErrors.breakdown).toBe("stop");
  });
});
