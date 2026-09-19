/**
 * SSE 流式分析竞态测试（问题 3）
 *
 * 核心场景：流 A 正常完成（reduce_completed）后 for-await 收尾期间，
 * 用户立即重开流 B —— 旧流 A 的 P0 兜底此前会误报"分析中断"并清掉
 * 新流 B 的 analyzing（订阅时序竞态）。修复后：
 *   1. terminated 守卫：正常完成的旧流永不触发兜底
 *   2. 切论文时 abort 旧流 fetch（防悬挂）
 *   3. 静默关闭（无终止事件）仍保留"分析中断"兜底
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

// 用 vi.hoisted 让 mock 工厂能引用同一声明
const { consumeSSE } = vi.hoisted(() => ({ consumeSSE: vi.fn() }));

vi.mock("@/lib/api", () => ({
  consumeSSE,
  API_BASE: "/api/proxy",
  api: {},
}));

import { usePaperStore } from "@/stores/paper-store";

const tick = () => new Promise((r) => setTimeout(r, 0));

const RESULT_A = { summary: "A 结果", quotes: [] };
const RESULT_B = { summary: "B 结果", quotes: [] };

beforeEach(() => {
  vi.clearAllMocks();
  usePaperStore.setState({
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
    // F11: analyzeError 单一字段改为按类型记录的 analyzeErrors
    analyzeErrors: { breakdown: null, innovation: null, flaws: null },
    streamProgress: null,
  });
});

describe("analyzeStream 竞态（场景 A：旧流收尾期重开新流）", () => {
  it("旧流 A 正常完成后的兜底不误杀新流 B", async () => {
    let releaseA: (() => void) | undefined;
    const gateA = new Promise<void>((r) => { releaseA = r; });
    let releaseB: (() => void) | undefined;
    const gateB = new Promise<void>((r) => { releaseB = r; });

    // 流 A：正常完成（reduce_completed + done），随后收尾挂起
    async function* genA() {
      yield { event: "started", data: {} };
      yield { event: "reduce_completed", data: { result: RESULT_A } };
      yield { event: "done", data: {} };
      await gateA; // 收尾挂起：模拟 reader 排空剩余字节的网络延迟
    }
    // 流 B：正在运行中（map 阶段挂起，未发终止事件）
    async function* genB() {
      yield { event: "started", data: {} };
      yield { event: "progress", data: { completed: 1, total: 3 } };
      await gateB;
      yield { event: "reduce_completed", data: { result: RESULT_B } };
    }

    consumeSSE.mockReturnValueOnce(genA());

    // 1. 启动流 A，等它跑完 reduce_completed（analyzing 变 null，按钮重新可用）
    const pA = usePaperStore.getState().analyzeStream("breakdown");
    for (let i = 0; i < 5; i++) await tick();
    expect(usePaperStore.getState().analyzing).toBeNull();

    // 2. 用户立即重开流 B（运行中）
    consumeSSE.mockReturnValueOnce(genB());
    const pB = usePaperStore.getState().analyzeStream("breakdown");
    for (let i = 0; i < 5; i++) await tick();
    expect(usePaperStore.getState().analyzing).toBe("breakdown");

    // 3. 放行流 A 收尾：旧流兜底必须被 terminated 守卫拦下（修复点）
    releaseA?.();
    await pA;
    expect(usePaperStore.getState().analyzing).toBe("breakdown");
    expect(usePaperStore.getState().analyzeErrors.breakdown).toBeNull();
    // 流 A 的结果保留（未被旧流兜底清掉），流 B 仍在运行

    // 4. 流 B 正常结束
    releaseB?.();
    await pB;
    expect(usePaperStore.getState().analyzing).toBeNull();
    expect(usePaperStore.getState().analyzeErrors.breakdown).toBeNull();
    expect(usePaperStore.getState().results.p1?.breakdown).toEqual(RESULT_B);
  });
});

describe("analyzeStream 竞态（场景 B：切论文中止旧流）", () => {
  it("切走论文时旧流被 abort（fetch 不悬挂）", async () => {
    let capturedSignal: AbortSignal | undefined;
    let releaseD: (() => void) | undefined;
    const gateD = new Promise<void>((r) => { releaseD = r; });

    consumeSSE.mockImplementation(async function* (_url: string, _body: unknown, _headers: unknown, options?: { signal?: AbortSignal }) {
      capturedSignal = options?.signal;
      yield { event: "started", data: {} };
      yield { event: "chapters_detected", data: { count: 1, chapters: [] } };
      await gateD; // 流挂起在运行中
      yield { event: "map_started", data: { chapter: "x" } };
    });

    const p = usePaperStore.getState().analyzeStream("breakdown");
    for (let i = 0; i < 5; i++) await tick();
    expect(usePaperStore.getState().analyzing).toBe("breakdown");
    expect(capturedSignal?.aborted).toBe(false);

    // 切换论文 → 下一个事件到达时旧流应被 abort（修复点）
    usePaperStore.setState({ currentPaperId: "p2" });
    releaseD?.();
    for (let i = 0; i < 5; i++) await tick();
    expect(capturedSignal?.aborted).toBe(true);
    await p;
    // 切走后旧流不应写任何状态
    expect(usePaperStore.getState().results.p1?.breakdown).toBeUndefined();
  });
});

describe("analyzeStream 兜底（保留原行为）", () => {
  it("流静默关闭（无终止事件）仍判定中断", async () => {
    let releaseC: (() => void) | undefined;
    const gateC = new Promise<void>((r) => { releaseC = r; });
    async function* genC() {
      yield { event: "started", data: {} };
      yield { event: "progress", data: { completed: 1, total: 3 } };
      await gateC; // 后端流静默关闭：无 reduce_completed/done/error
    }
    consumeSSE.mockReturnValueOnce(genC());

    const p = usePaperStore.getState().analyzeStream("breakdown");
    for (let i = 0; i < 5; i++) await tick();
    releaseC?.();
    await p;

    expect(usePaperStore.getState().analyzing).toBeNull();
    expect(usePaperStore.getState().analyzeErrors.breakdown).toBe("分析中断，请重试");
  });
});
