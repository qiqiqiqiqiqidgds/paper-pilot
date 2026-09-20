/** @type {import('next').NextConfig} */
import path from "node:path";
import { fileURLToPath } from "node:url";

// 桌面版（Electron）构建：BUILD_TARGET=desktop 时静态导出到 out/，
// 由 FastAPI（SERVE_STATIC_DIR）托管，页面与 /api/* 同源，无 CORS / BFF。
// Web 模式不加 output，行为与原来完全一致。
const isDesktop = process.env.BUILD_TARGET === "desktop";

const nextConfig = {
  reactStrictMode: true,
  ...(isDesktop ? { output: "export" } : {}),
  // 用 config env 做内联（官方保证写入浏览器 bundle）。
  // 直接传空字符串的环境变量不会被 DefinePlugin 内联成 ""，运行时会
  // 退回 ?? 的默认值 /api/proxy，导致桌面版请求打到不存在的 BFF 路径。
  ...(isDesktop ? { env: { NEXT_PUBLIC_API_BASE: "" } } : {}),
  experimental: {
    optimizePackageImports: ["lucide-react"],
  },
  // 解决 pdf.js worker 跨域
  webpack: (config) => {
    config.resolve.alias.canvas = false;
    // pdfjs-dist 的 pdf.mjs 内嵌 webpack runtime，内部 var __webpack_exports__ 在
    // dev eval 模式下会遮蔽 webpack 注入的导出对象导致渲染崩溃（见脚本注释）
    config.module.rules.push({
      test: /pdf\.mjs$/,
      use: [{ loader: path.join(path.dirname(fileURLToPath(import.meta.url)), "scripts/pdfjs-exports-patch.cjs") }],
    });
    if (isDesktop) {
      // 桌面版把 API_BASE 内联为空串（同源直连后端）。
      // 空字符串的 NEXT_PUBLIC_* 环境变量 / config env 在 Windows 下都不会被
      // Next 的 DefinePlugin 内联（保留运行时查找，浏览器里 undefined 回退默认值），
      // 所以直接改 DefinePlugin 定义，最可靠。
      const dp = config.plugins.find((p) => p?.constructor?.name === "DefinePlugin");
      if (!dp) throw new Error("未找到 DefinePlugin，无法注入桌面版 API_BASE");
      dp.definitions["process.env.NEXT_PUBLIC_API_BASE"] = JSON.stringify("");
    }
    return config;
  },
};

export default nextConfig;
