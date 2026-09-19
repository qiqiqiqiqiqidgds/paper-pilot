"use client";
/**
 * 漏洞视图（批注手稿 · note 体系）
 * 三层局限（编号 note + 严重度章）+ .suggest 改进建议 + ✦ 整体评价；逻辑与旧版一致
 */
import { Note, NoteHead, JumpButton, CopyButton, circledNum } from "./analysis-shell";
import type { FlawsResult, FlawItem } from "@/types";
import { cn } from "@/lib/utils";

export function FlawsView({ data, onJumpToPDF }: { data: FlawsResult; onJumpToPDF?: (page: number, text?: string) => void }) {
  const groups: Array<{ label: string; items: FlawItem[] | undefined }> = [
    { label: "方法层面", items: data.method_level },
    { label: "实验层面", items: data.experiment_level },
    { label: "写作层面", items: data.writing_level },
  ];
  const totalCount = groups.reduce((n, g) => n + (g.items?.length || 0), 0);

  let idx = 0;
  return (
    <div>
      {groups.map(({ label, items }) =>
        (items || []).map((f, i) => {
          idx += 1;
          return (
            <Note key={`${f.page_ref}-${f.description?.slice(0, 20)}-${label}-${i}`}>
              <NoteHead no={circledNum(idx)} title={label} page={f.page_ref ? `P${f.page_ref}` : ""} />
              <div className="mb-1">
                <span className={cn("stamp", f.severity !== "major" && "mild")}>
                  {f.severity === "major" ? "严重" : "一般"}
                </span>
              </div>
              <p className="note-body">{f.description}</p>
              {f.evidence && <p className="note-body muted mt-1 text-[11.5px]">依据：{f.evidence}</p>}
              <div className="flex items-center justify-between gap-2">
                {/* evidence 是 LLM 给出的原文依据，透传后可作为 PDF 高亮目标 */}
                <JumpButton page={f.page_ref} text={f.evidence} onJumpToPDF={onJumpToPDF} />
                {f.evidence && <CopyButton text={f.evidence} label="复制证据" />}
              </div>
            </Note>
          );
        })
      )}
      {data.improvements?.map((imp, i) => (
        <Note variant="plain" key={`${imp.flaw_ref}-${imp.suggestion?.slice(0, 20)}-${i}`}>
          <div className="suggest">
            <b>针对局限 {imp.flaw_ref}</b>　{imp.suggestion}　
            <span className="stamp mild" style={{ transform: "none" }}>
              可行性 {imp.feasibility === "high" ? "高" : imp.feasibility === "medium" ? "中" : "低"}
            </span>
          </div>
        </Note>
      ))}
      {data.overall_assessment && (
        <Note>
          <NoteHead no="✦" title="整体评价" />
          <p className="note-body">{data.overall_assessment}</p>
        </Note>
      )}
      {totalCount === 0 && !data.overall_assessment && !(data.improvements?.length) && (
        <Note variant="plain">
          <p className="note-body muted">分析完成，但返回内容为空。</p>
        </Note>
      )}
    </div>
  );
}
