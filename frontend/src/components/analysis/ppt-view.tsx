"use client";
/**
 * PPT 视图（批注手稿 · note 体系）
 * 生成表单（check-row 勾选项）/ 生成中（不定进度 + elapsed）/ 成功（下载卡）/ 错误；逻辑与旧版一致
 */
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Note, NoteHead } from "./analysis-shell";
import { toast } from "sonner";
import { usePaperStore } from "@/stores/paper-store";
import { api, downloadBlob } from "@/lib/api";
import { cn } from "@/lib/utils";

export function PPTView() {
  const currentPaperId = usePaperStore((s) => s.currentPaperId);
  const results = usePaperStore((s) => s.results);
  const pptInfo = usePaperStore((s) =>
    s.currentPaperId ? s.pptResults[s.currentPaperId] ?? null : null,
  );
  const setPptResult = usePaperStore((s) => s.setPptResult);
  // P0-5/6：results 按 paper_id 分组
  const currentResults = currentPaperId ? results[currentPaperId] || {} : {};
  // P1-1：进行中锁上收到 store（pptStartedAt = 发起时刻，null = 空闲）。
  // 本组件随 activeTab 条件渲染，切书签带即卸载——本地 useState 锁会丢，
  // 等待期（10–30s）切走再切回可重复发起；store 锁不受卸载影响
  const pptStartedAt = usePaperStore((s) => s.pptStartedAt);
  const loading = pptStartedAt !== null;
  const [error, setError] = useState<string | null>(null);
  const [includeFlaws, setIncludeFlaws] = useState(false);
  const [includeCompare, setIncludeCompare] = useState(false);
  // P2-15: 进度反馈（elapsed timer + 不确定 progress）
  const [elapsedSec, setElapsedSec] = useState(0);

  // 勾选项可用性跟随已有分析结果（app.html：需先做对应分析才可勾选）
  const canFlaws = !!currentResults.flaws;
  const canCompare = !!currentResults.compare;

  useEffect(() => {
    setError(null);
    setElapsedSec(0);
  }, [currentPaperId]);

  useEffect(() => {
    if (pptStartedAt === null) {
      setElapsedSec(0);
      return;
    }
    // 以 store 里的发起时刻为基准：切书签带卸载重挂后，已等待秒数接着真实时长继续走
    const tick = () => setElapsedSec(Math.floor((Date.now() - pptStartedAt) / 1000));
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [pptStartedAt]);

  const handleGenerate = async () => {
    if (!currentPaperId) return;
    // 防双击/事件重放：入口同步再查一次 store 锁（同 analyze 的 F8 双保险）
    if (usePaperStore.getState().pptStartedAt !== null) return;
    const paperId = currentPaperId;
    const startedAt = Date.now();
    usePaperStore.setState({ pptStartedAt: startedAt });
    setError(null);
    try {
      const data = await api.generatePPT(paperId, {
        include_flaws: includeFlaws,
        include_compare: includeCompare,
      });

      // P1 竞态防护：请求期间切换论文，丢弃旧结果
      if (usePaperStore.getState().currentPaperId !== paperId) return;

      // 运行时校验响应结构（P0-8）
      if (
        !data ||
        typeof data.download_url !== "string" ||
        typeof data.filename !== "string" ||
        typeof data.size !== "number"
      ) {
        throw new Error("后端返回的 PPT 数据结构异常：缺少 download_url / filename / size 字段。");
      }

      setPptResult(paperId, {
        download_url: data.download_url,
        filename: data.filename,
        size: data.size,
        pages: typeof data.pages === "number" ? data.pages : 0,
        warnings: Array.isArray(data.warnings) ? data.warnings : [],
      });
      toast.success("PPT 已生成");
      // 后端勾选页数据缺失时透出 warnings（ppt.py），不能静默少页
      if (data.warnings && data.warnings.length > 0) {
        toast.warning(data.warnings.join("；"), { duration: 8000 });
      }
    } catch (e: unknown) {
      if (usePaperStore.getState().currentPaperId !== paperId) return;
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      toast.error(`生成失败：${msg}`);
    } finally {
      // 复位 store 锁（成功/失败/异常都走到；store setState 不受组件卸载影响）。
      // 仅当锁仍归属本任务（发起时刻未被切论文复位、也未被新任务覆盖）才清，
      // 防止旧任务收尾误清新任务的锁（同 compare-view / analyzeStream finally 的守卫）
      if (usePaperStore.getState().pptStartedAt === startedAt) {
        usePaperStore.setState({ pptStartedAt: null });
      }
    }
  };

  const handleDownload = async () => {
    if (!pptInfo) return;
    const paperId = currentPaperId;
    try {
      // 走 BFF 代理下载（附服务端鉴权 header），代替裸 <a href>
      await downloadBlob(pptInfo.download_url, pptInfo.filename);
    } catch (e: unknown) {
      if (usePaperStore.getState().currentPaperId !== paperId) return;
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`下载失败：${msg}`);
    }
  };

  const hasBreakdown = !!currentResults.breakdown;
  const hasInnovation = !!currentResults.innovation;
  const canGenerate = hasBreakdown || hasInnovation;

  if (loading) {
    return (
      <Note variant="plain" role="status" aria-live="polite" aria-busy="true">
        <NoteHead no="✦" title="正在生成 PPT" />
        <p className="note-body">首次约 10–30 秒…</p>
        <div className="progress-bar indeterminate" aria-hidden="true"><i /></div>
        <p className="note-body muted text-[11px]">已等待 {elapsedSec} 秒</p>
      </Note>
    );
  }

  if (error) {
    return (
      <Note variant="err" role="alert">
        <NoteHead title="生成失败" />
        <p className="note-body break-all">{error}</p>
        <Button size="sm" variant="ghost" className="mt-2" onClick={handleGenerate}>
          重试
        </Button>
      </Note>
    );
  }

  if (pptInfo) {
    return (
      <Note variant="plain">
        <NoteHead title="PPT 已生成" />
        <p className="note-body">
          {pptInfo.filename}
          {pptInfo.size ? `　${Math.round(pptInfo.size / 1024)} KB` : ""}
          {pptInfo.pages ? ` · ${pptInfo.pages} 页` : ""}
        </p>
        {pptInfo.warnings.length > 0 && (
          <p className="note-body muted mt-1.5">注意：{pptInfo.warnings.join("；")}</p>
        )}
        <div className="flex gap-2 mt-2.5">
          <Button size="sm" onClick={handleDownload}>
            下载 .pptx
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => currentPaperId && setPptResult(currentPaperId, null)}
          >
            重新生成
          </Button>
        </div>
        <p className="note-body muted text-[11px] mt-2">可用 PowerPoint / Keynote / WPS 打开微调。</p>
      </Note>
    );
  }

  return (
    <Note variant="plain">
      <NoteHead title="生成汇报 PPT" />
      <p className="note-body mb-2">基于已完成的拆解与创新点分析自动生成。</p>
      {!canGenerate && (
        <p className="note-body muted mb-2">请先在「拆解」或「创新」至少完成一项分析，否则没有可用的生成素材。</p>
      )}
      <label className={cn("check-row", !canFlaws && "disabled")}>
        <input
          type="checkbox"
          checked={includeFlaws}
          onChange={(e) => setIncludeFlaws(e.target.checked)}
          disabled={!canFlaws || loading}
        />
        包含「局限性」页{canFlaws ? "" : "（需先做漏洞分析）"}
      </label>
      <label className={cn("check-row", !canCompare && "disabled")}>
        <input
          type="checkbox"
          checked={includeCompare}
          onChange={(e) => setIncludeCompare(e.target.checked)}
          disabled={!canCompare || loading}
        />
        包含「相关工作对比」页{canCompare ? "" : "（需先做对比分析）"}
      </label>
      <Button size="sm" className="mt-2" onClick={handleGenerate} disabled={!canGenerate}>
        生成 PPT
      </Button>
      <p className="note-body muted text-[11px] mt-2">10–30 秒；生成后下载 .pptx，用 PowerPoint / Keynote / WPS 打开微调。</p>
    </Note>
  );
}
