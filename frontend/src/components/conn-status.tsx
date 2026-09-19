"use client";
/**
 * 连接状态指示器：地球图标颜色即状态（绿=正常 / 琥珀=异常或降级），
 * 悬浮弹出面板展示后端与各接口状态（数据来自 /api/health + /api/papers 探测）。
 * 悬停自动检测（节流），点击立即重新检测。
 */
import { useCallback, useRef, useState } from "react";
import { Globe } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

type Level = "ok" | "warn" | "err" | "na";
interface StatusRow {
  label: string;
  value: string;
  level: Level;
}

function connLevel(rows: StatusRow[]): "ok" | "warn" | "err" {
  const backend = rows[0];
  if (!backend) return "warn";
  if (backend.level === "err") return "err";
  return rows.some((r) => r.level === "err") ? "warn" : "ok";
}

export function ConnStatus({ onChanged }: { onChanged?: (healthy: boolean) => void }) {
  const [rows, setRows] = useState<StatusRow[]>([
    { label: "后端服务", value: "检测中…", level: "na" },
  ]);
  const lastCheckRef = useRef(0);
  const checkingRef = useRef(false);

  const check = useCallback(
    async (force = false) => {
      if (checkingRef.current) return;
      if (!force && Date.now() - lastCheckRef.current < 5000) return;
      lastCheckRef.current = Date.now();
      checkingRef.current = true;
      const collected: StatusRow[] = [];
      let healthy = false;
      try {
        const h = await api.health();
        healthy = h?.status === "ok";
        collected.push({ label: "后端服务", value: `已连接${h?.version ? ` v${h.version}` : ""}`, level: healthy ? "ok" : "err" });
        // P2-3 复核（对照 backend/app/api/health.py 实际可能返回的枚举）：
        //   llm ∈ {configured, missing_key}；search ∈ {arxiv, configured, missing_key}
        //   （SEARCH_PROVIDER=tavily 且配/未配 key、否则 arxiv）；tavily ∈ {configured, missing_key}。
        //   旧映射两处真实错判：search="missing_key" 被判 ok（绿）、tavily="configured" 落到
        //   na（灰）且显示英文枚举原文——实测环境（arXiv 搜索 + 未配 Tavily）恰好未触发，
        //   故 T7 界面看起来正常。以下把全部枚举值显式映射到中文文案 + 正确状态灯。
        const llm = (h as { llm?: string })?.llm;
        collected.push({
          label: "LLM 大模型",
          value:
            llm === "configured"
              ? "已配置（可在设置中更换）"
              : llm === "missing_key"
                ? "未配置（点顶栏设置填写）"
                : String(llm ?? "未知"),
          level: llm === "configured" ? "ok" : "warn",
        });
        const search = (h as { search?: string })?.search;
        collected.push({
          label: "学术搜索",
          value:
            search === "arxiv"
              ? "已配置（arXiv）"
              : search === "configured"
                ? "已配置"
                : search === "missing_key"
                  ? "未配置（需要 API Key）"
                  : String(search ?? "未知"),
          level: search && search !== "none" && search !== "missing_key" ? "ok" : "warn",
        });
        const tavily = (h as { tavily?: string })?.tavily;
        collected.push({
          label: "Tavily 联网",
          value:
            tavily === "missing_key"
              ? "未配置（可选）"
              : tavily === "configured"
                ? "已配置"
                : String(tavily ?? "未知"),
          level: tavily === "missing_key" ? "warn" : tavily === "configured" ? "ok" : "na",
        });
        const dataOk = (h as { data_dir_ok?: boolean })?.data_dir_ok;
        collected.push({ label: "数据目录", value: dataOk ? "正常" : "异常", level: dataOk ? "ok" : "err" });
      } catch {
        collected.push({ label: "后端服务", value: "未连接", level: "err" });
        collected.push({ label: "各接口", value: "不可用", level: "err" });
      }
      // 论文库接口实际探测一次（GET，无副作用）
      if (healthy) {
        try {
          await api.listPapers();
          collected.push({ label: "论文库接口", value: "正常", level: "ok" });
        } catch {
          collected.push({ label: "论文库接口", value: "异常", level: "err" });
        }
      }
      setRows(collected);
      checkingRef.current = false;
      onChanged?.(healthy);
    },
    [onChanged]
  );

  const level = connLevel(rows);

  return (
    <div className="relative group mr-1" onMouseEnter={() => void check()}>
      <button
        type="button"
        onClick={() => void check(true)}
        aria-label="服务状态（点击重新检测）"
        title="服务状态（点击重新检测）"
        className={cn(
          "h-[30px] w-[30px] rounded flex items-center justify-center border bg-card transition-colors text-muted-foreground hover:text-ink2",
          level === "ok" && "text-success hover:text-success",
          level === "warn" && "text-[hsl(40,59%,45%)] dark:text-[hsl(41,44%,48%)]",
          level === "err" && "text-destructive"
        )}
      >
        <Globe className="h-[15px] w-[15px]" aria-hidden="true" />
      </button>

      {/* 悬浮状态面板（app.html .conn-pop）。
          a11y: 除 group-hover 外补 group-focus-within——Tab 聚焦触发按钮时同样展开，
          键盘用户也能读到状态（面板本身仍可 hover 停留） */}
      <div className="invisible opacity-0 -translate-y-1 transition-all duration-150 group-hover:visible group-hover:opacity-100 group-focus-within:visible group-focus-within:opacity-100 group-focus-within:translate-y-0 hover:visible hover:opacity-100 hover:translate-y-0 absolute top-full right-0 mt-2 w-[250px] rounded-md border border-[hsl(var(--border-strong))] bg-card px-3 py-2.5 z-50"
        role="status"
        aria-label="后端与接口连接状态"
      >
        <div className="font-display font-semibold text-[12.5px] mb-1.5">服务状态</div>
        <div>
          {rows.map((r) => (
            <div key={r.label} className="flex items-center gap-[7px] text-[11.5px] py-[3px]">
              <span
                className={cn(
                  "h-1.5 w-1.5 rounded-full shrink-0",
                  r.level === "ok" && "bg-success",
                  r.level === "warn" && "bg-[hsl(40,59%,45%)]",
                  r.level === "err" && "bg-destructive",
                  r.level === "na" && "bg-[hsl(var(--border-strong))]"
                )}
                aria-hidden="true"
              />
              <span className="text-muted-foreground">{r.label}</span>
              <span className="ml-auto text-ink2 text-right">{r.value}</span>
            </div>
          ))}
        </div>
        <div className="mt-[7px] pt-1.5 border-t border-dashed text-[10.5px] text-muted-foreground">
          悬停自动检测 · 点击图标重新检测
        </div>
      </div>
    </div>
  );
}
