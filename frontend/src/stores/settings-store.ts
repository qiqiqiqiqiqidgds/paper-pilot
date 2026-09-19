"use client";
/**
 * 设置状态：对话框开关 + 后端脱敏视图（GET /api/settings）。
 * API Key 等敏感值的权威存储在后端（data/settings.json），前端只持有
 * 脱敏后的视图用于回显，不做 localStorage 持久化——避免密钥落地浏览器。
 */
import { create } from "zustand";
import { api } from "@/lib/api";
import type { SettingsView } from "@/types";

interface SettingsStore {
  open: boolean;
  view: SettingsView | null;
  loading: boolean;
  error: string | null;
  setOpen: (open: boolean) => void;
  refresh: () => Promise<void>;
}

export const useSettingsStore = create<SettingsStore>((set) => ({
  open: false,
  view: null,
  loading: false,
  error: null,
  setOpen: (open) => {
    set({ open });
    if (open) void useSettingsStore.getState().refresh();
  },
  refresh: async () => {
    set({ loading: true, error: null });
    try {
      const view = await api.settings.get();
      set({ view });
    } catch (e) {
      set({ error: e instanceof Error ? e.message : String(e) });
    } finally {
      set({ loading: false });
    }
  },
}));
