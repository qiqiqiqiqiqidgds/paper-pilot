"use client";
/**
 * 界面级 UI 状态（与数据无关的展示状态）
 * - activeTab：当前书签带（拆解/创新/对比/漏洞/PPT）
 * 书签带渲染在纸页顶边（pdf-viewer），边批内容在右侧面板（ai-analysis-panel），
 * 两者通过本 store 共享；paperpilot:set-tab 事件与快捷键继续走事件通道。
 */
import { create } from "zustand";

interface UiState {
  activeTab: string;
  setActiveTab: (tab: string) => void;
}

export const useUiStore = create<UiState>((set) => ({
  activeTab: "breakdown",
  setActiveTab: (activeTab) => set({ activeTab }),
}));
