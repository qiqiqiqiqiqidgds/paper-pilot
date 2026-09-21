"use client";
/**
 * 对比视图（批注手稿 · note 体系）
 * 联网搜对比 / 多篇库内对比 共用；逻辑与旧版一致（externalResult 优先、4001 空态、竞态防护）
 */
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { AnalysisView, Note, NoteHead, MiniPoints, circledNum } from "./analysis-shell";
import { toast } from "sonner";
import { usePaperStore } from "@/stores/paper-store";
import { api } from "@/lib/api";
import { safeHttpUrl } from "@/lib/utils";
import type { CompareResponse, RelatedPaper } from "@/types";

export function CompareView({ externalResult, onConsumed }: { externalResult?: CompareResponse | null; onConsumed?: () => void }) {
  const currentPaperId = usePaperStore((s) => s.currentPaperId);
  // P1-1：进行中锁上收到 store（compareStartedAt = 发起时刻，null = 空闲）。
  // 本组件随 activeTab 条件渲染，切书签带即卸载——本地 useState 锁会丢，
  // 等待期（30–90s）切走再切回按钮恢复可点、可并发重复发起；store 锁不受卸载影响
  const compareStartedAt = usePaperStore((s) => s.compareStartedAt);
  const loading = compareStartedAt !== null;
  const [result, setResult] = useState<CompareResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  // 接收外部传入的结果（多篇对比）
  useEffect(() => {
    if (externalResult) {
      setResult(externalResult);
      onConsumed?.();
    }
  }, [externalResult, onConsumed]);

  const runCompare = async () => {
    if (!currentPaperId) return;
    // 防双击/事件重放：入口同步再查一次 store 锁（同 analyze 的 F8 双保险，按钮 disabled 之外的批处理间隙防护）
    if (usePaperStore.getState().compareStartedAt !== null) return;
    const paperId = currentPaperId;
    const startedAt = Date.now();
    usePaperStore.setState({ compareStartedAt: startedAt });
    setError(null);
    try {
      // P2-16: 联网搜对比（单论文 + Tavily），不要传 paper_ids 数组
      const data = await api.compare(paperId, { max_results: 5 });
      // P1 竞态防护：请求期间切换论文，丢弃旧结果
      if (usePaperStore.getState().currentPaperId !== paperId) return;
      setResult(data);
      // F3: 同步写入 store（B4 缓存约定）——本组件挂在边批面板里，
      // 切换书签带即卸载，局部 result state 会丢失；写入 results[paperId].compare 后
      // ai-analysis-panel 的 externalResult={compareResult ?? currentResults.compare}
      // 兜底生效，切走再切回不丢。上面已确认 currentPaperId 仍是发起时的 paperId，无竞态。
      usePaperStore.setState((s) => ({
        results: {
          ...s.results,
          [paperId]: { ...(s.results[paperId] || {}), compare: data },
        },
      }));
      // 后端 code=4001（未搜到相关工作/供应商未配置）返回空数据：提示而非报错
      const hasRelated = !!(data.related_papers && data.related_papers.length > 0);
      if (hasRelated) {
        toast.success("对比分析完成");
      } else {
        toast.info("未搜到相关工作（可能搜索供应商未配置或无结果），可稍后重试");
      }
      // 刷新论文列表：让 has_compare 徽标/状态与服务端缓存同步（否则一直停留在旧值）
      void usePaperStore.getState().fetchPapers();
    } catch (e: unknown) {
      if (usePaperStore.getState().currentPaperId !== paperId) return;
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      toast.error(`对比失败：${msg}`);
    } finally {
      // 复位 store 锁（成功/失败/异常都走到；store setState 不受组件卸载影响）。
      // 仅当锁仍归属本任务（发起时刻未被切论文复位、也未被新任务覆盖）才清，
      // 防止旧任务收尾误清新任务的锁（同 analyzeStream finally 的槽位守卫）
      if (usePaperStore.getState().compareStartedAt === startedAt) {
        usePaperStore.setState({ compareStartedAt: null });
      }
    }
  };

  // 标记这是多篇对比还是联网搜
  const isMultiPaper = !!(result && result.related_papers && result.related_papers.some((p: RelatedPaper) => p.paper_id));

  return (
    <AnalysisView
      title="相关工作对比"
      description={isMultiPaper ? "多篇论文对比（来自论文库）" : "联网搜索 arxiv 等学术源 + LLM 生成对比表"}
      analyzing={loading}
      onAnalyze={runCompare}
      error={error}
      disabled={loading}
      hasResult={!!result}
      runLabel="联网对比"
      emptyLabel="对比"
      rerunLabel="重新对比"
      progressTitle="联网对比中"
      costHint="约 30–90 秒（联网搜索 + 生成）"
    >
      {result && <CompareResultView data={result} onRetry={runCompare} />}
    </AnalysisView>
  );
}

function CompareResultView({ data, onRetry }: { data: CompareResponse; onRetry: () => void }) {
  if (!data.related_papers || data.related_papers.length === 0) {
    // 后端 code=4001（搜索供应商未配置 / 未搜到相关工作）：空态而非报错
    return (
      <Note variant="plain" className="empty-set">
        <div className="note-title">未搜到相关工作</div>
        <p className="hint">可能是搜索供应商未配置，或确实没有相关工作，可稍后重试。</p>
        <Button size="sm" variant="ghost" onClick={onRetry}>
          重试
        </Button>
      </Note>
    );
  }

  return (
    <div>
      {data.main_paper && (
        <Note variant="plain">
          <NoteHead title="主论文" page={data.main_paper.year || ""} />
          <p className="note-body">
            {data.main_paper.title}
            {data.main_paper.method_summary ? ` —— ${data.main_paper.method_summary}` : ""}
          </p>
        </Note>
      )}

      {data.compare_table && data.compare_table.length > 0 && (
        <Note>
          <NoteHead no={circledNum(1)} title="对比表" />
          {/* 320px 边批放不下完整表格：横向滚动兜底，避免溢出面板 */}
          <div className="overflow-x-auto">
            <table className="mini-table">
              <tbody>
                {data.compare_table.slice(0, 9).map((row: string[], i: number) => (
                  <tr key={`row-${i}-${row[0]?.slice(0, 8) || ""}`}>
                    {row.map((cell: string, j: number) =>
                      i === 0 ? (
                        <th key={`${i}-${j}-${String(cell ?? "").slice(0, 20)}`}>{cell}</th>
                      ) : (
                        <td key={`${i}-${j}-${String(cell ?? "").slice(0, 20)}`}>{cell}</td>
                      )
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Note>
      )}

      {data.related_papers.map((p: RelatedPaper, i: number) => (
        // key 带 index：arXiv 同一论文 v1/v2 或重名论文的 url/title 会碰撞
        <Note key={`${i}-${p.url || p.title || "related"}`}>
          <NoteHead
            no={circledNum(i + 2)}
            title={p.title}
            page={p.year ? String(p.year) : ""}
            action={
              // 外链来自搜索/LLM 输出：只放行 http(s)，伪协议退化为纯文本
              safeHttpUrl(p.url) ? (
                <a
                  href={safeHttpUrl(p.url) ?? undefined}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="note-jump !mt-0 ml-auto shrink-0"
                  aria-label={`打开 ${p.title} 原文链接`}
                >
                  原文链接 ↗
                </a>
              ) : undefined
            }
          />
          {p.method && <p className="note-body"><b>方法</b>　{p.method}</p>}
          {p.dataset && <p className="note-body"><b>数据集</b>　{p.dataset}</p>}
          {p.result && <p className="note-body"><b>结果</b>　{p.result}</p>}
          {p.relation_to_main && <p className="note-body"><b>与本文关系</b>　{p.relation_to_main}</p>}
          {p.pros && <p className="note-body" style={{ color: "hsl(var(--green))" }}><b>优势</b>　{p.pros}</p>}
          {p.cons && <p className="note-body" style={{ color: "hsl(var(--destructive))" }}><b>劣势</b>　{p.cons}</p>}
        </Note>
      ))}

      {data.summary && (
        <Note>
          <NoteHead no="✦" title="整体对比" />
          <p className="note-body">{data.summary}</p>
        </Note>
      )}

      {data.main_advantages && data.main_advantages.length > 0 && (
        <Note>
          <NoteHead no="＋" title="主论文优势" />
          <MiniPoints items={data.main_advantages} tone="good" />
        </Note>
      )}

      {data.main_disadvantages && data.main_disadvantages.length > 0 && (
        <Note>
          <NoteHead no="－" title="主论文劣势" />
          <MiniPoints items={data.main_disadvantages} tone="bad" />
        </Note>
      )}
    </div>
  );
}
