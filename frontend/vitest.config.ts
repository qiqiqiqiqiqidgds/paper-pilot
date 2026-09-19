/// <reference types="vitest" />
/**
 * Vitest 配置（Sprint 4 / R3）
 * - jsdom 环境：支持 React 组件渲染测试
 * - @/ alias：与 tsconfig.json 一致，让测试能 import "@/lib/utils"
 * - setupFiles：加载 jest-dom 断言（toBeInTheDocument 等）
 * - css: false：避免拉 Tailwind 解析器干扰（测试中不验证样式）
 */
import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    css: false,
    include: ["tests/**/*.test.{ts,tsx}"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
