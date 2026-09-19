// PDF 文本高亮搜索候选生成（纯 TS，无 react-pdf 依赖，便于单测）
// 背景：LLM 的 evidence 可能含页码标注或轻微改写，单一窗口精确匹配会失败，
// 多候选依次尝试可显著提高 text layer 匹配命中率（创新 Tab 跳转修复）。

/**
 * LLM 引用文本中常见的页码标注（跳转匹配前剥离，避免干扰原文定位）
 * F10: 只在页码标注有明确括号时剥离——[P3] / （P3） / (P3) / 【P3】 / （第 X 页） / (第 X 页)。
 * 旧正则方括号可选（\[?...\]?），裸 "P2"/"P100" 会被误删（如 "P2P 网络"、"P95 延迟"）。
 */
const PAGE_ANNOTATION_RE =
  /\[\s*P\s*\d+\s*\]|（\s*P\s*\d+\s*）|\(\s*P\s*\d+\s*\)|【\s*P\s*\d+\s*】|（\s*第\s*\d+\s*页\s*）|\(\s*第\s*\d+\s*页\s*\)/gi;

/** 归一化空白 */
function norm(s: string): string {
  return s.replace(/\s+/g, " ").trim();
}

/**
 * 剥离页码标注后的完整文本（供全文定位使用——全局搜索需要完整引用文本，
 * 短窗口候选（30 字）在全文搜索里容易命中无关页）
 */
export function stripPageAnnotations(text: string): string {
  return norm(text.replace(PAGE_ANNOTATION_RE, " "));
}

/**
 * 生成高亮搜索候选：
 * 1. 剥离 LLM 页码标注（[P3] / （P3） / 【P3】 / （第 4 页）等带括号形式）
 * 2. 多窗口前缀（30/20/12 字符）+ 尾部 30 字符兜底 + 剥离前的原文兜底
 * 3. 去重、过滤过短候选（<5 字符容易误匹配）
 */
export function buildSearchCandidates(text: string): string[] {
  const stripped = stripPageAnnotations(text);
  const candidates: string[] = [];

  // 多窗口前缀（优先长窗口：更精确）
  for (const len of [30, 20, 12]) {
    if (stripped.length >= len) candidates.push(stripped.slice(0, len));
  }
  // 文本不足 30 字时用全量
  if (stripped.length > 0 && stripped.length < 30) candidates.push(stripped);
  // 尾部兜底：evidence 末尾往往是完整句子
  if (stripped.length > 30) candidates.push(stripped.slice(-30));
  // 剥离前原文兜底（剥离规则过严时；若剥离后已为空说明全是标注，兜底无意义）
  const raw = norm(text);
  if (raw && stripped.length > 0 && raw !== stripped) candidates.push(raw.slice(0, 30));

  return Array.from(new Set(candidates)).filter((c) => c.length >= 5);
}
