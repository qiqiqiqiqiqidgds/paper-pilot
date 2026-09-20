/**
 * 组装桌面版资源：把 PyInstaller 后端产物与前端静态导出复制到 desktop/resources/。
 *
 * 前置（分别执行过后再跑本脚本）：
 *   backend : pyinstaller paperpilot-backend.spec --noconfirm --clean
 *   frontend: npm run build:desktop
 *
 * 用法：desktop/ 下执行 npm run assemble
 */
import { cpSync, existsSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const desktopDir = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const root = path.dirname(desktopDir);

const backendDist = path.join(root, "backend", "dist", "paperpilot-backend");
const frontendOut = path.join(root, "frontend", "out");

const targets = [
  { from: backendDist, to: path.join(desktopDir, "resources", "backend"), label: "后端 onedir" },
  { from: frontendOut, to: path.join(desktopDir, "resources", "frontend"), label: "前端静态导出" },
];

for (const { from, to, label } of targets) {
  if (!existsSync(from)) {
    console.error(`[assemble] 缺少 ${label}：${from} 不存在。请先完成对应构建（见本文件头注释）。`);
    process.exit(1);
  }
  rmSync(to, { recursive: true, force: true });
  cpSync(from, to, { recursive: true });
  console.log(`[assemble] ${label}: ${from} -> ${to}`);
}
console.log("[assemble] 完成。现在可以 npm start（开发运行）或 npm run smoke（冒烟验证）。");
