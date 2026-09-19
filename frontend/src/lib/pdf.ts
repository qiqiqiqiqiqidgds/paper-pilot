"use client";
/**
 * PDF.js Worker 单点配置（懒加载 / SSR 安全）
 *
 * 背景：
 *  1. react-pdf 顶层 import 副作用：pdfjs.GlobalWorkerOptions.workerSrc = 'pdf.worker.mjs'
 *     （相对路径，部署后会 404）。原方案是在这里再赋一次绝对路径覆盖。
 *  2. pdfjs-dist 4+ 在模块加载时会触碰 DOMMatrix / Path2D 等浏览器 API，
 *     顶层 `import { pdfjs } from "react-pdf"` 会在 Next.js SSR / 预编译阶段
 *     抛出 `ReferenceError: DOMMatrix is not defined`（见 frontend.log）。
 *
 * 方案：
 *  - 不再顶层 import react-pdf；改为在浏览器侧 useEffect 内通过动态 import
 *    按需加载（dynamic import 只在浏览器执行 chunk，永远不会触碰 SSR）。
 *  - 调用方（PDFViewer）在挂载时 `await initPdfJs()` 完成 workerSrc 覆盖，
 *    然后再渲染 <Document>，确保 <Document> 内部使用我们覆盖过的 workerSrc。
 *  - 多次调用 initPdfJs 安全（结果缓存到 initPromise，幂等）。
 *
 * worker 文件由 predev/prebuild 钩子（scripts/copy-pdf-worker.mjs）从
 * node_modules/pdfjs-dist/build/pdf.worker.min.mjs 复制到 public/pdf.worker.min.mjs
 * （纯静态资源，无 CDN，离线 / CSP 严格环境可用）。
 */

// 类型仅用，编译期擦除（typeof import() 不发出 import 语句，SSR 安全）
type Pdfjs = typeof import("react-pdf").pdfjs;

let initPromise: Promise<Pdfjs> | null = null;

/**
 * 初始化 PDF.js：动态加载 react-pdf 并在浏览器侧设置 workerSrc。
 * 多次调用安全（结果缓存）。必须在浏览器环境的 useEffect / 事件处理中调用，
 * 不要在模块顶层 / SSR 阶段调用。
 */
export async function initPdfJs(): Promise<Pdfjs> {
  if (!initPromise) {
    initPromise = import("react-pdf")
      .then((mod) => {
        if (typeof window !== "undefined") {
          mod.pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";
        }
        return mod.pdfjs;
      })
      .catch((err) => {
        // F14: 失败时清掉缓存的 rejected promise，否则重试时拿到的永远是同一次失败，
        // UI 的"重试"按钮无法真正重新初始化
        initPromise = null;
        throw err;
      });
  }
  return initPromise;
}
