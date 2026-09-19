/** @type {import('next').NextConfig} */
import path from "node:path";
import { fileURLToPath } from "node:url";

const nextConfig = {
  reactStrictMode: true,
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
    return config;
  },
};

export default nextConfig;
