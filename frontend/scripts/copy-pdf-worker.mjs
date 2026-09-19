// 把 pdfjs 的运行时资源复制到 public/ 作为纯静态资源，避免 webpack 编译/压缩 ESM worker。
// pdfjs-dist 4.x/5.x 的 worker 是 ESM .mjs，Next.js 14 的 ?url / new URL 方案都有坑
// （SSR 阶段 default export 缺失 / Terser 解析失败），静态复制最稳。
// 通过 package.json 的 predev / prebuild 钩子自动执行。
//
// 复制三样东西：
// 1. pdf.worker.min.mjs          —— 渲染 worker
// 2. cmaps/                      —— CJK PDF 必需的 CMap 映射表：未内嵌字体的中文论文
//                                   缺了它整页文字渲染成空白/豆腐块，getTextContent()
//                                   也抽不出正确文本（引用跳转高亮随之失效）
// 3. standard_fonts/             —— 14 种标准字体替代文件，同样是非内嵌字体 PDF 的兜底
//
// 校验：复制后核对产物存在且体积正常（源 worker 约 1MB），
// 防止 node_modules 里 pdfjs-dist 缺失/版本异常时静默产出坏文件。
import { copyFileSync, cpSync, existsSync, mkdirSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const pdfjsDir = join(root, "node_modules", "pdfjs-dist");
const publicDir = join(root, "public");

// ---- worker ----
const workerSrc = join(pdfjsDir, "build", "pdf.worker.min.mjs");
const workerDest = join(publicDir, "pdf.worker.min.mjs");
const MIN_EXPECTED_BYTES = 100 * 1024; // 100KB（正常约 1MB；低于此值视为复制异常）

mkdirSync(publicDir, { recursive: true });
copyFileSync(workerSrc, workerDest);

const size = statSync(workerDest).size;
if (size < MIN_EXPECTED_BYTES) {
  console.error(`[copy-pdf-worker] worker 产物异常偏小（${size} bytes < ${MIN_EXPECTED_BYTES}），检查 pdfjs-dist 版本`);
  process.exit(1);
}
console.log(`[copy-pdf-worker] ${workerDest} (${(size / 1024 / 1024).toFixed(2)} MB)`);

// ---- cmaps / standard_fonts ----
for (const name of ["cmaps", "standard_fonts"]) {
  const src = join(pdfjsDir, name);
  const dest = join(publicDir, name);
  if (!existsSync(src)) {
    console.warn(`[copy-pdf-worker] pdfjs-dist 缺少 ${name}/，跳过（中文 PDF 渲染可能受影响）`);
    continue;
  }
  cpSync(src, dest, { recursive: true });
  console.log(`[copy-pdf-worker] ${dest}/ 已更新`);
}
