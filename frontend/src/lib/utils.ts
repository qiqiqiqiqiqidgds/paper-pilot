import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatTime(iso: string) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString("zh-CN", { hour12: false });
}

/**
 * 外链 scheme 白名单：只放行 http(s) URL，其余（javascript:、data: 等伪协议
 * 或畸形字符串）返回 null，调用方应退化为纯文本展示。
 * 相关链接来自联网搜索 / LLM 输出，不能直接信任为 href。
 */
export function safeHttpUrl(raw: string | null | undefined): string | null {
  if (!raw) return null;
  try {
    const u = new URL(raw);
    return u.protocol === "http:" || u.protocol === "https:" ? u.toString() : null;
  } catch {
    return null;
  }
}
