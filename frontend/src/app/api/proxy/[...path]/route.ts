// BFF 反向代理：把前端 API 请求转发到后端服务，并在服务端附加鉴权密钥。
//
// 为什么需要它：
//   之前 API Key 通过 NEXT_PUBLIC_API_KEY 打进浏览器 bundle，任何访问者都能
//   在 DevTools 里拿到后端共享密钥。现在密钥只存在于服务端环境变量
//   （BACKEND_API_KEY），由本代理统一附加 X-API-Key，前端不再接触密钥。
//
// 支持 GET / POST / DELETE，转发 body、query、headers；
// SSE（/api/analyze/stream）与文件上传（/api/upload）都走透传。

import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";
const BACKEND_API_KEY = process.env.BACKEND_API_KEY || "";

/**
 * 跨站防护（CSRF）：multipart/form-data 是 CORS simple request，不触发预检——
 * 任意网页可以跨站向本代理投递上传请求，代理会替它附上后端密钥。
 * 校验 Origin（缺失时回退 Referer，再缺失视为同源工具/curl 放行）：
 * 必须与本请求的 Host 同源才转发。
 *
 * P2-2：反代部署（Nginx/CDN 终结 TLS 并改写 Host）时，浏览器看到的域名在
 * x-forwarded-host 里，而请求的 Host 可能已被改写为内部地址——只比 Host 会把
 * 所有带 Origin 的同源写请求误判成跨站（全站 403）。故 Host 不匹配时回退对比
 * x-forwarded-host（多值时取第一个，即客户端可见域名）；仍不匹配才拒绝。
 * 信任 x-forwarded-host 的取舍：该头由我们自己的反代层设置/转发；且本代理
 * 本身无 cookie 透传、后端 API Key 只在服务端附加，伪造它绕过的仅是 CSRF
 * 防线而没有可盗用的凭据，风险低。开发环境直连 localhost（无该头，且
 * Origin host === Host）走第一道判断放行，行为完全不变。
 */
function isSameOrigin(req: NextRequest): boolean {
  const origin = req.headers.get("origin") || req.headers.get("referer");
  if (!origin) return true; // 同源 fetch 部分场景不带 Origin（GET 导航等），放行
  try {
    const originHost = new URL(origin).host;
    const host = req.headers.get("host");
    if (host && originHost === host) return true;
    const forwardedHost = req.headers.get("x-forwarded-host")?.split(",")[0]?.trim();
    if (forwardedHost) return originHost === forwardedHost;
    return false;
  } catch {
    return false;
  }
}

async function proxy(req: NextRequest, { params }: { params: { path: string[] } }) {
  if (!isSameOrigin(req)) {
    return Response.json(
      { detail: "跨站请求被拒绝（Origin 与站点不匹配）" },
      { status: 403 }
    );
  }

  const path = params.path.join("/");
  const url = `${BACKEND_URL}/${path}${req.nextUrl.search}`;

  const headers = new Headers();
  const contentType = req.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  const accept = req.headers.get("accept");
  if (accept) headers.set("accept", accept);
  // 服务端附加鉴权密钥（不暴露给浏览器）
  if (BACKEND_API_KEY) headers.set("X-API-Key", BACKEND_API_KEY);

  // 请求体统一缓冲后透传（上传文件/JSON 都适用；避免流式请求体在代理层踩坑）
  const body: BodyInit | undefined =
    req.method === "GET" || req.method === "HEAD" ? undefined : (await req.arrayBuffer()) as BodyInit;

  let res: Response;
  try {
    res = await fetch(url, {
      method: req.method,
      headers,
      body,
      // 客户端断开时中止上游请求，避免代理侧流悬挂
      signal: req.signal,
      cache: "no-store",
    });
  } catch {
    return Response.json({ detail: "后端服务不可用，请稍后重试" }, { status: 502 });
  }

  // 透传关键响应头；SSE 的 text/event-stream 通过 new Response(upstream.body) 原样流式返回
  const resHeaders = new Headers();
  const upstreamContentType = res.headers.get("content-type");
  if (upstreamContentType) resHeaders.set("content-type", upstreamContentType);
  const contentDisposition = res.headers.get("content-disposition");
  if (contentDisposition) resHeaders.set("content-disposition", contentDisposition);
  const retryAfter = res.headers.get("retry-after");
  if (retryAfter) resHeaders.set("retry-after", retryAfter);

  return new Response(res.body, { status: res.status, statusText: res.statusText, headers: resHeaders });
}

export async function GET(req: NextRequest, ctx: { params: { path: string[] } }) {
  return proxy(req, ctx);
}

export async function POST(req: NextRequest, ctx: { params: { path: string[] } }) {
  return proxy(req, ctx);
}

export async function DELETE(req: NextRequest, ctx: { params: { path: string[] } }) {
  return proxy(req, ctx);
}
