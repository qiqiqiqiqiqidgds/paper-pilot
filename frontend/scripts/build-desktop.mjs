/**
 * 桌面版（Electron）前端构建脚本：产出静态导出到 out/。
 *
 * 做三件事：
 *  1. 临时把 src/app/api（BFF 代理路由，force-dynamic 与静态导出不兼容）
 *     移到 _api_desktop_backup —— App Router 下下划线前缀目录不参与路由；
 *  2. 以 BUILD_TARGET=desktop + NEXT_PUBLIC_API_BASE="" 执行 next build
 *     （前者开 output: 'export'，后者让 API_BASE 直连同源后端）；
 *  3. 无论成败恢复 api 目录（try/finally），避免污染工作区。
 *
 * 用法：node scripts/build-desktop.mjs
 * 产物：out/（纯静态，含 public/ 资源如 pdf.worker.min.mjs）
 */
import { execSync } from "node:child_process";
import { existsSync, renameSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendDir = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const apiDir = path.join(frontendDir, "src", "app", "api");
const backupDir = path.join(frontendDir, "src", "app", "_api_desktop_backup");
const outDir = path.join(frontendDir, "out");

if (existsSync(backupDir)) {
  // 上次构建异常中断没恢复：先清掉备份，把 api 目录还原成干净状态
  if (existsSync(apiDir)) {
    rmSync(backupDir, { recursive: true, force: true });
  } else {
    renameSync(backupDir, apiDir);
  }
}

rmSync(outDir, { recursive: true, force: true });
renameSync(apiDir, backupDir);

try {
  // 先复制 pdf worker：本脚本直接调用 next build，不会触发 npm 的 prebuild
  // 钩子；而 worker 文件被 gitignore（由 copy-pdf-worker.mjs 生成），
  // fresh clone 直接跑本脚本会产出 PDF 渲染 404 的静态包。
  execSync("node scripts/copy-pdf-worker.mjs", { cwd: frontendDir, stdio: "inherit" });
  execSync("npx next build", {
    cwd: frontendDir,
    stdio: "inherit",
    env: {
      ...process.env,
      BUILD_TARGET: "desktop",
      // 空串而非删除键：确保 Next 把 "" 内联进 bundle（?? 只对 undefined 回退）
      NEXT_PUBLIC_API_BASE: "",
    },
  });
} finally {
  renameSync(backupDir, apiDir);
}

console.log(`\n[build-desktop] 静态导出完成：${outDir}`);
