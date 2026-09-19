"use client";
/**
 * 拆解视图（批注手稿 · note 体系）
 * ①-⑥ 五段结构化总结（段内附原文对照）+ ✦ 要点 + 朱批引用；逻辑与旧版一致
 */
import type { BreakdownResult, Quote } from "@/types";
import { Note, NoteHead, ZhuQuote, MiniPoints, circledNum } from "./analysis-shell";
import { matchQuotesForSection } from "@/lib/section-quotes";

/** 段落 + 该段匹配的原文引用（最多 2 条），实现"拆解 ↔ 原文对照" */
function SectionWithQuotes({
  no,
  title,
  text,
  section,
  quotes,
  onJumpToPDF,
}: {
  no: string;
  title: string;
  text: string;
  section: string;
  quotes: Quote[];
  onJumpToPDF?: (page: number, text?: string) => void;
}) {
  const matched = matchQuotesForSection(quotes, section);
  return (
    <Note>
      <NoteHead no={no} title={title} />
      <p className="note-body">{text}</p>
      {matched.slice(0, 2).map((q, i) => (
        <ZhuQuote key={`${section}-${q.page}-${i}`} quote={q} onJumpToPDF={onJumpToPDF} />
      ))}
    </Note>
  );
}

export function BreakdownView({ data, onJumpToPDF }: { data: BreakdownResult; onJumpToPDF?: (page: number, text?: string) => void }) {
  const quotes = data.quotes || [];
  const sections = [
    { title: "摘要", text: data.summary, section: "summary" },
    { title: "研究背景", text: data.background, section: "background" },
    { title: "研究目标", text: data.goal, section: "goal" },
    { title: "方法", text: data.method, section: "method" },
    { title: "实验", text: data.experiment, section: "experiment" },
    { title: "结论", text: data.conclusion, section: "conclusion" },
  ].filter((s) => s.text);

  return (
    <div>
      {sections.map((s, i) => (
        <SectionWithQuotes
          key={s.section}
          no={circledNum(i + 1)}
          title={s.title}
          text={s.text}
          section={s.section}
          quotes={quotes}
          onJumpToPDF={onJumpToPDF}
        />
      ))}
      {data.key_points && data.key_points.length > 0 && (
        <Note>
          <NoteHead no="✦" title="要点" />
          <MiniPoints items={data.key_points} />
        </Note>
      )}
      {quotes.map((q, i) => (
        <ZhuQuote key={`${q.page}-${q.section}-${i}`} quote={q} onJumpToPDF={onJumpToPDF} />
      ))}
      {sections.length === 0 && !(data.key_points?.length) && quotes.length === 0 && (
        <Note variant="plain">
          <p className="note-body muted">分析完成，但返回内容为空。</p>
        </Note>
      )}
    </div>
  );
}
