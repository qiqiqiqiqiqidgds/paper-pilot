"use client";
/**
 * 创新视图（批注手稿 · note 体系）
 * 创新等级（印章 + 分级理由）+ 编号创新点（跳 PDF）+ ◎ 适用场景 + 朱批引用；逻辑与旧版一致
 */
import { Note, NoteHead, JumpButton, ZhuQuote, MiniPoints, CopyButton } from "./analysis-shell";
import type { InnovationResult } from "@/types";

export function InnovationView({ data, onJumpToPDF }: { data: InnovationResult; onJumpToPDF?: (page: number, text?: string) => void }) {
  return (
    <div>
      <Note variant="plain">
        <NoteHead title="创新等级" />
        {/* 印章样式：LLM 偶发返回未知枚举值时兜底显示原文，避免印章空白 */}
        <div className="my-1.5">
          <span className="seal">
            {data.innovation_level === "incremental" && "渐进式"}
            {data.innovation_level === "significant" && "显著"}
            {data.innovation_level === "disruptive" && "颠覆性"}
            {data.innovation_level !== "incremental" && data.innovation_level !== "significant" && data.innovation_level !== "disruptive" && (data.innovation_level || "未分级")}
          </span>
        </div>
        {data.level_reasoning && <p className="note-body muted mt-2">{data.level_reasoning}</p>}
      </Note>

      {data.core_innovations?.map((c, i) => (
        <Note key={`${i}-${(c.title || "").slice(0, 8) || `inno-${i}`}`}>
          {/* key 带 index 前缀：LLM 可能输出两个同名创新点，纯 title key 会碰撞 */}
          <NoteHead no={String(i + 1)} title={c.title || `创新点 ${i + 1}`} page={c.page_ref ? `P${c.page_ref}` : ""} />
          <p className="note-body">{c.description}</p>
          {c.evidence && <p className="note-body muted mt-1 text-[11.5px]">依据：{c.evidence}</p>}
          <div className="flex items-center justify-between gap-2">
            {/* evidence 是 LLM 给出的原文依据，透传后可作为 PDF 高亮目标 */}
            <JumpButton page={c.page_ref} text={c.evidence} onJumpToPDF={onJumpToPDF} />
            {c.evidence && <CopyButton text={c.evidence} label={`复制创新点 ${i + 1} 的证据`} />}
          </div>
        </Note>
      ))}

      {data.applicable_scenarios?.length > 0 && (
        <Note>
          <NoteHead no="◎" title="适用场景" />
          <MiniPoints items={data.applicable_scenarios} />
        </Note>
      )}

      {data.quotes && data.quotes.length > 0 && (
        data.quotes.map((q, i) => (
          <ZhuQuote key={`${q.page}-${q.section}-${i}`} quote={q} onJumpToPDF={onJumpToPDF} />
        ))
      )}
    </div>
  );
}
