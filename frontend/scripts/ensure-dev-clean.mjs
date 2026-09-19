// dev 启动前检查：如果 .next 里残留生产构建标记（BUILD_ID），
// 说明上一次跑过 npm run build 覆盖了 dev 缓存。dev 与生产共用 .next 目录，
// 交叉构建会让浏览器请求的 dev 路径（/_next/static/chunks/app/page.js 等）全部 404
// （表现：页面 HTML 正常但 CSS/JS 全丢 → 布局全部丢失）。
// 检测到生产标记就删除 .next，避免 404 复发。
// 通过 package.json 的 predev 钩子自动执行。
import { existsSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const nextDir = join(root, ".next");
const buildIdFile = join(nextDir, "BUILD_ID");

// BUILD_ID 是生产构建独有标记（dev 模式不生成该文件）
if (existsSync(buildIdFile)) {
  console.log("[ensure-dev-clean] 检测到生产构建残留（.next/BUILD_ID），删除 .next 以清理 dev 缓存");
  rmSync(nextDir, { recursive: true, force: true });
} else if (!existsSync(nextDir)) {
  console.log("[ensure-dev-clean] .next 不存在，无需清理");
} else {
  console.log("[ensure-dev-clean] .next 为 dev 缓存，无需清理");
}
