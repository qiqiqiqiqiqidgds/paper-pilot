"use strict";

/**
 * 最小 preload：contextIsolation 开启，页面拿不到 Node 能力。
 * 预留一个 desktop 信息桥，后续如需"打开数据目录 / 检查更新"等
 * 原生能力，在这里用 contextBridge 暴露并在 main.js 用 ipcMain 实现。
 */
const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("paperpilotDesktop", {
  isDesktop: true,
  platform: process.platform,
  versions: { electron: process.versions.electron, chrome: process.versions.chrome },
});
