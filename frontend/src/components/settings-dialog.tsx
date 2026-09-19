"use client";
/**
 * 设置对话框：在网页端填写 LLM / 搜索供应商配置（顶栏齿轮入口）。
 *
 * 交互约定（与后端 /api/settings 对齐）：
 * - API Key 输入框留空 = 保持后端已保存的 Key 不变（回显只有掩码）；
 * - 「测试连接」用当前表单值探测（不落盘）：LLM 发一次 1-token chat，
 *   若搜索选了 Tavily 则顺带查 1 条结果；
 * - 「保存」字段级覆盖并即时生效（后续请求即用新配置，无需重启）；
 * - 「恢复默认」清除网页端覆盖，回到 backend/.env 的兜底值。
 */
import { useCallback, useEffect, useState } from "react";
import { Loader2, RotateCcw, PlugZap, X } from "lucide-react";
import { Button } from "./ui/button";
import { useSettingsStore } from "@/stores/settings-store";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import type { SettingsTestResult } from "@/types";

// 常见 OpenAI 兼容提供商预设（只是表单快捷填充，可自由改成任意端点）
const PROVIDER_PRESETS = [
  { id: "minimax", label: "MiniMax", baseUrl: "https://api.minimaxi.com/v1", model: "MiniMax-M3" },
  { id: "deepseek", label: "DeepSeek", baseUrl: "https://api.deepseek.com", model: "deepseek-chat" },
  { id: "openai", label: "OpenAI", baseUrl: "https://api.openai.com/v1", model: "gpt-4o" },
  { id: "custom", label: "自定义（OpenAI 兼容）", baseUrl: "", model: "" },
] as const;

function detectPreset(baseUrl: string): string {
  const hit = PROVIDER_PRESETS.find((p) => p.baseUrl && p.baseUrl === baseUrl);
  return hit ? hit.id : "custom";
}

const inputCls =
  "w-full h-8 rounded border border-[hsl(var(--border-strong))] bg-background px-2.5 text-[12.5px] text-ink2 placeholder:text-muted-foreground focus:outline-none focus:border-[hsl(var(--cinnabar))] transition-colors";

function Field({
  label,
  htmlFor,
  hint,
  children,
}: {
  label: string;
  htmlFor: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-2.5">
      <label htmlFor={htmlFor} className="block text-[11.5px] text-muted-foreground mb-1">
        {label}
        {hint ? <span className="ml-1.5">{hint}</span> : null}
      </label>
      {children}
    </div>
  );
}

export function SettingsDialog() {
  const open = useSettingsStore((s) => s.open);
  const view = useSettingsStore((s) => s.view);
  const loading = useSettingsStore((s) => s.loading);
  const error = useSettingsStore((s) => s.error);
  const setOpen = useSettingsStore((s) => s.setOpen);
  const refresh = useSettingsStore((s) => s.refresh);

  // 表单状态（打开对话框 / 视图刷新时从脱敏视图回填）
  const [llmKey, setLlmKey] = useState("");
  const [llmBaseUrl, setLlmBaseUrl] = useState("");
  const [llmModel, setLlmModel] = useState("");
  const [provider, setProvider] = useState("custom");
  const [searchProvider, setSearchProvider] = useState<"arxiv" | "tavily">("arxiv");
  const [tavilyKey, setTavilyKey] = useState("");
  const [tavilyBaseUrl, setTavilyBaseUrl] = useState("https://api.tavily.com");
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testResult, setTestResult] = useState<SettingsTestResult | null>(null);

  useEffect(() => {
    if (!open) return;
    setLlmKey("");
    setTestResult(null);
    if (view) {
      setLlmBaseUrl(view.llm.base_url);
      setLlmModel(view.llm.model);
      setProvider(detectPreset(view.llm.base_url));
      setSearchProvider(view.search.provider);
      setTavilyBaseUrl(view.search.tavily_base_url || "https://api.tavily.com");
      setTavilyKey("");
    }
  }, [open, view]);

  // Esc 关闭（对话框标准行为）
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, setOpen]);

  const applyPreset = useCallback((id: string) => {
    setProvider(id);
    const preset = PROVIDER_PRESETS.find((p) => p.id === id);
    if (preset && preset.baseUrl) {
      setLlmBaseUrl(preset.baseUrl);
      setLlmModel(preset.model);
    }
  }, []);

  if (!open) return null;

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await api.settings.test({
        llm: {
          // Key 留空 = 用后端已保存的值探测
          api_key: llmKey.trim() || undefined,
          base_url: llmBaseUrl.trim() || undefined,
          model: llmModel.trim() || undefined,
        },
        search: searchProvider === "tavily",
      });
      setTestResult(result);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "连接测试失败");
    } finally {
      setTesting(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.settings.update({
        llm: {
          api_key: llmKey.trim() || undefined,
          base_url: llmBaseUrl.trim(),
          model: llmModel.trim(),
        },
        search: {
          provider: searchProvider,
          tavily_api_key: tavilyKey.trim() || undefined,
          tavily_base_url: searchProvider === "tavily" ? tavilyBaseUrl.trim() : undefined,
        },
      });
      await refresh();
      toast.success("设置已保存，即时生效");
      setOpen(false);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    setSaving(true);
    try {
      await api.settings.update({ reset_llm: true, reset_search: true });
      await refresh();
      toast.success("已恢复 .env 默认配置");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "恢复失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[100]">
      {/* 遮罩（暗色下加深一档保证面板浮出感） */}
      <div
        className="absolute inset-0 bg-black/55"
        onClick={() => setOpen(false)}
        aria-hidden="true"
      />
      {/* 面板 */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label="设置"
        className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[min(540px,92vw)] max-h-[84vh] overflow-y-auto rounded-lg border border-[hsl(var(--border-strong))] bg-card shadow-2xl"
      >
        <div className="flex items-center justify-between px-4 h-[42px] border-b sticky top-0 bg-card z-10">
          <h2 className="font-display font-semibold text-[14px]">设置 · API 供应商</h2>
          <Button size="icon" variant="ghost" onClick={() => setOpen(false)} aria-label="关闭设置">
            <X className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>

        <div className="px-4 py-4">
          {loading && !view ? (
            <div className="flex items-center gap-2 text-[12.5px] text-muted-foreground py-8 justify-center">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> 正在读取配置…
            </div>
          ) : error && !view ? (
            <p className="note-body muted py-4">读取配置失败：{error}（请确认后端已启动）</p>
          ) : (
            <>
              {/* ===== LLM ===== */}
              <section aria-label="LLM 配置">
                <Field label="提供商预设" htmlFor="llm-preset" hint="选择后自动填充地址与模型名，可再手改">
                  <select
                    id="llm-preset"
                    value={provider}
                    onChange={(e) => applyPreset(e.target.value)}
                    className={inputCls}
                  >
                    {PROVIDER_PRESETS.map((p) => (
                      <option key={p.id} value={p.id}>{p.label}</option>
                    ))}
                  </select>
                </Field>
                <Field label="Base URL（OpenAI 兼容端点）" htmlFor="llm-base-url">
                  <input
                    id="llm-base-url"
                    type="url"
                    value={llmBaseUrl}
                    onChange={(e) => {
                      setLlmBaseUrl(e.target.value);
                      setProvider(detectPreset(e.target.value.trim()));
                    }}
                    placeholder="https://api.example.com/v1"
                    className={inputCls}
                    autoComplete="off"
                  />
                </Field>
                <Field label="模型名" htmlFor="llm-model">
                  <input
                    id="llm-model"
                    type="text"
                    value={llmModel}
                    onChange={(e) => setLlmModel(e.target.value)}
                    placeholder="例如 deepseek-chat / MiniMax-M3"
                    className={inputCls}
                    autoComplete="off"
                  />
                </Field>
                <Field
                  label="API Key"
                  htmlFor="llm-key"
                  hint={view?.llm.api_key_masked ? `已保存 ${view.llm.api_key_masked}，留空保持不变` : "未配置"}
                >
                  <input
                    id="llm-key"
                    type="password"
                    value={llmKey}
                    onChange={(e) => setLlmKey(e.target.value)}
                    placeholder={view?.llm.api_key_configured ? "留空保持已保存的 Key" : "sk-…"}
                    className={inputCls}
                    autoComplete="new-password"
                  />
                </Field>
              </section>

              {/* ===== 搜索 ===== */}
              <section aria-label="搜索配置" className="mt-5 pt-3 border-t">
                <div className="font-display font-semibold text-[12.5px] mb-2">联网搜索</div>
                <Field label="供应商" htmlFor="search-provider">
                  <select
                    id="search-provider"
                    value={searchProvider}
                    onChange={(e) => setSearchProvider(e.target.value as "arxiv" | "tavily")}
                    className={inputCls}
                  >
                    <option value="arxiv">arXiv（免费，无需 Key）</option>
                    <option value="tavily">Tavily（通用网页搜索，需 Key）</option>
                  </select>
                </Field>
                {searchProvider === "tavily" && (
                  <>
                    <Field
                      label="Tavily API Key"
                      htmlFor="tavily-key"
                      hint={view?.search.tavily_api_key_masked ? `已保存 ${view.search.tavily_api_key_masked}，留空保持不变` : "未配置"}
                    >
                      <input
                        id="tavily-key"
                        type="password"
                        value={tavilyKey}
                        onChange={(e) => setTavilyKey(e.target.value)}
                        placeholder={view?.search.tavily_api_key_configured ? "留空保持已保存的 Key" : "tvly-…"}
                        className={inputCls}
                        autoComplete="new-password"
                      />
                    </Field>
                    <Field label="Tavily Base URL" htmlFor="tavily-base-url">
                      <input
                        id="tavily-base-url"
                        type="url"
                        value={tavilyBaseUrl}
                        onChange={(e) => setTavilyBaseUrl(e.target.value)}
                        className={inputCls}
                        autoComplete="off"
                      />
                    </Field>
                  </>
                )}
              </section>

              {/* ===== 测试结果 ===== */}
              {testResult && (
                <div
                  className="mt-4 rounded border border-dashed border-[hsl(var(--cinnabar))]/45 bg-[hsl(var(--cinnabar))]/[0.045] px-3 py-2"
                  role="status"
                >
                  {(["llm", "search"] as const).map((k) => {
                    const r = testResult[k];
                    if (!r) return null;
                    return (
                      <div key={k} className="flex items-start gap-1.5 text-[11.5px] py-[3px]">
                        <span
                          className={cn(
                            "mt-[6px] h-1.5 w-1.5 rounded-full shrink-0",
                            r.ok ? "bg-success" : "bg-destructive"
                          )}
                          aria-hidden="true"
                        />
                        <span className="text-muted-foreground shrink-0">{k === "llm" ? "LLM" : "搜索"}</span>
                        <span className={r.ok ? "text-ink2" : "text-destructive"}>{r.message}</span>
                      </div>
                    );
                  })}
                </div>
              )}

              {/* ===== 操作区（窄屏自动换行，避免 4 按钮挤一行） ===== */}
              <div className="mt-4 pt-3 border-t flex flex-wrap items-center gap-2">
                <Button size="sm" variant="outline" onClick={handleTest} disabled={testing}>
                  {testing ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : <PlugZap className="h-3.5 w-3.5" aria-hidden="true" />}
                  测试连接
                </Button>
                <Button size="sm" variant="ghost" onClick={handleReset} disabled={saving} title="清除网页端覆盖值，回到 backend/.env 配置">
                  <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                  恢复默认
                </Button>
                <div className="ml-auto flex items-center gap-2">
                  <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>取消</Button>
                  <Button size="sm" onClick={handleSave} disabled={saving || !llmBaseUrl.trim() || !llmModel.trim()}>
                    {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : null}
                    保存
                  </Button>
                </div>
              </div>
              <p className="note-body muted mt-3">
                配置保存在本机（backend/data/settings.json），Key 不会进入代码仓库；保存后即时生效，无需重启。
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
