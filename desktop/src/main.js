"use strict";

/**
 * PaperPilot 桌面版主进程。
 *
 * 职责（见 docs/feasibility-electron-desktop.md §三 推荐架构）：
 *   1. 单实例锁；
 *   2. 探测空闲端口 → spawn PyInstaller 后端（onedir exe），注入全部运行配置；
 *   3. 轮询 /api/health 就绪后加载窗口（FastAPI 同源托管前端静态页）；
 *   4. 退出时杀后端进程树；后端异常退出时提示用户。
 *
 * 冒烟模式（CI / 脚本验证用）：electron . --smoke
 *   健康检查通过 + 首页可达 → exit 0；任一失败 → exit 1，不起窗口。
 */

const { app, BrowserWindow, dialog, shell } = require("electron");
const { spawn } = require("node:child_process");
const net = require("node:net");
const http = require("node:http");
const path = require("node:path");
const fs = require("node:fs");

const SMOKE = process.argv.includes("--smoke");
const HEALTH_TIMEOUT_MS = 60_000;
const HEALTH_POLL_INTERVAL_MS = 400;

// 资源目录：打包后 extraResources 位于 process.resourcesPath；
// 开发模式（未打包）用 desktop/resources/（由 scripts/assemble.mjs 组装）。
const resourcesDir = app.isPackaged
  ? process.resourcesPath
  : path.join(__dirname, "..", "resources");

const backendExe = path.join(resourcesDir, "backend", "paperpilot-backend.exe");
const frontendDir = path.join(resourcesDir, "frontend");
const userDataDir = app.getPath("userData");

/** @type {import("node:child_process").ChildProcess | null} */
let backendProc = null;
/** @type {BrowserWindow | null} */
let mainWindow = null;
let quitting = false;

function log(...args) {
  console.log(`[desktop] ${new Date().toISOString()} `, ...args);
}

/** 探测一个 127.0.0.1 上的空闲端口（listen(0) 让内核分配） */
function findFreePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on("error", reject);
    srv.listen(0, "127.0.0.1", () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

/** 启动后端进程，返回进程对象；resolve 当进程退出（用于健康检查竞态兜底） */
function spawnBackend(port) {
  const env = {
    ...process.env,
    // ===== 后端运行配置（pydantic-settings：环境变量优先于 .env）=====
    APP_ENV: "dev",                                  // 桌面版走 dev（无 prod 鉴权强制），仅监听回环
    APP_HOST: "127.0.0.1",                           // 绝不暴露局域网
    APP_PORT: String(port),
    DATA_DIR: path.join(userDataDir, "data"),        // 论文库 + settings.json 落用户目录
    LOG_DIR: path.join(userDataDir, "logs"),         // 日志落用户目录（安装目录可能只读）
    SERVE_STATIC_DIR: frontendDir,                   // FastAPI 托管前端静态导出（同源直连）
    // ===== Python 侧编码（中文 Windows 控制台默认 GBK）=====
    PYTHONIOENCODING: "utf-8",
    PYTHONUNBUFFERED: "1",
    // 父进程看护：后端侧等待本进程句柄，Electron 被强杀时自动退出，防孤儿进程
    PAPERPILOT_PARENT_PID: String(process.pid),
  };

  const proc = spawn(backendExe, [], {
    env,
    windowsHide: true, // 不闪控制台窗口
    stdio: ["ignore", "pipe", "pipe"],
  });

  proc.stdout.on("data", (d) => log("[backend]", String(d).trim()));
  proc.stderr.on("data", (d) => log("[backend:err]", String(d).trim()));

  const exited = new Promise((resolve) => {
    proc.once("exit", (code) => {
      log(`backend exited (code=${code})`);
      resolve(code);
    });
  });
  proc.exited = exited;

  proc.on("exit", (code) => {
    // 非正常退出（用户主动退出之外）：桌面弹窗告知，避免"白屏无声死"
    if (!quitting && !SMOKE && mainWindow && !mainWindow.isDestroyed()) {
      dialog.showErrorBox(
        "PaperPilot 后端服务已停止",
        `后端进程异常退出（code=${code}）。\n\n` +
          `日志位置：${path.join(userDataDir, "logs")}\n` +
          `请重新启动应用；若反复出现请把日志反馈给开发者。`
      );
    }
  });

  return proc;
}

/** GET /api/health，2xx → resolve，否则 reject（带状态码） */
function pingHealth(port) {
  return new Promise((resolve, reject) => {
    const req = http.get(
      { host: "127.0.0.1", port, path: "/api/health", timeout: 2000 },
      (res) => {
        res.resume(); // 丢弃 body，只看状态码
        if (res.statusCode && res.statusCode >= 200 && res.statusCode < 300) resolve();
        else reject(new Error(`health 返回 ${res.statusCode}`));
      }
    );
    req.on("timeout", () => req.destroy(new Error("health 请求超时")));
    req.on("error", reject);
  });
}

/** 轮询健康检查；后端先退出则立即失败（不傻等超时） */
async function waitForHealth(port, proc, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (proc.exitCode !== null) {
      throw new Error(`后端进程已退出（code=${proc.exitCode}），详见日志`);
    }
    try {
      await pingHealth(port);
      return;
    } catch (e) {
      if (Date.now() > deadline) {
        throw new Error(`后端 ${timeoutMs / 1000}s 内未就绪：${e.message}`);
      }
      await new Promise((r) => setTimeout(r, HEALTH_POLL_INTERVAL_MS));
    }
  }
}

/** 冒烟模式附加验证：首页（静态导出 index.html）可达 */
function pingIndex(port) {
  return new Promise((resolve, reject) => {
    const req = http.get(
      { host: "127.0.0.1", port, path: "/", timeout: 5000 },
      (res) => {
        res.resume();
        if (res.statusCode === 200) resolve();
        else reject(new Error(`首页返回 ${res.statusCode}`));
      }
    );
    req.on("timeout", () => req.destroy(new Error("首页请求超时")));
    req.on("error", reject);
  });
}

/** Windows 下杀整棵进程树（uvicorn 不再 fork，纯保险）；其他平台 SIGTERM。
 *  返回 Promise：冒烟模式需要 await 它再 exit，否则孤儿检查可能跑赢 taskkill。 */
function killBackendTree() {
  if (!backendProc || backendProc.exitCode !== null) return Promise.resolve();
  const pid = backendProc.pid;
  return new Promise((resolve) => {
    if (process.platform === "win32") {
      const tk = spawn(
        "taskkill",
        ["/pid", String(pid), "/T", "/F"],
        { stdio: "ignore", windowsHide: true }
      );
      tk.once("exit", () => resolve());
      tk.once("error", () => resolve());
    } else {
      backendProc.kill("SIGTERM");
      resolve();
    }
  });
}

function createWindow(port) {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1024,
    minHeight: 640,
    show: false, // ready-to-show 再显示，避免白屏闪烁
    autoHideMenuBar: true,
    backgroundColor: "#0a0a0a",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  mainWindow.once("ready-to-show", () => mainWindow.show());

  // 外部链接交给系统浏览器；本机应用页面才允许在窗口内打开
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    try {
      const u = new URL(url);
      if (u.hostname === "127.0.0.1" || u.hostname === "localhost") {
        return { action: "allow" };
      }
    } catch {
      /* 非法 URL 一律走外部 */
    }
    shell.openExternal(url);
    return { action: "deny" };
  });
  mainWindow.webContents.on("will-navigate", (event, url) => {
    try {
      const u = new URL(url);
      if (u.hostname !== "127.0.0.1" && u.hostname !== "localhost") {
        event.preventDefault();
        shell.openExternal(url);
      }
    } catch {
      event.preventDefault();
    }
  });

  mainWindow.loadURL(`http://127.0.0.1:${port}/`);
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

// ===== 单实例锁：重复启动时聚焦已有窗口 =====
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  app.whenReady().then(async () => {
    // 资源缺失（忘记 assemble / 打包配置错）直接报错退出，比黑屏好排查
    if (!fs.existsSync(backendExe)) {
      dialog.showErrorBox(
        "PaperPilot 缺少后端资源",
        `未找到后端程序：${backendExe}\n\n` +
          (app.isPackaged
            ? "安装包不完整，请重新安装。"
            : "开发模式请先运行 npm run assemble（组装 backend/frontend 资源）。")
      );
      app.exit(1);
      return;
    }

    const port = await findFreePort();
    log(`启动后端 127.0.0.1:${port}（静态目录 ${frontendDir}）`);
    backendProc = spawnBackend(port);

    try {
      await waitForHealth(port, backendProc, HEALTH_TIMEOUT_MS);
    } catch (e) {
      log(`健康检查失败：${e.message}`);
      killBackendTree();
      if (!SMOKE) {
        dialog.showErrorBox("PaperPilot 启动失败", String(e.message));
      }
      app.exit(1);
      return;
    }
    log("后端就绪");

    if (SMOKE) {
      // 冒烟模式：首页可达即通过，退出码作为 CI 信号。
      // 注意 app.exit() 不触发 before-quit，必须显式清理后端进程。
      try {
        await pingIndex(port);
        log("SMOKE: OK（后端健康 + 首页 200）");
        await killBackendTree();
        app.exit(0);
      } catch (e) {
        log(`SMOKE: FAIL（${e.message}）`);
        await killBackendTree();
        app.exit(1);
      }
      return;
    }

    createWindow(port);

    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow(port);
    });
  });
}

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  quitting = true;
  killBackendTree();
});
