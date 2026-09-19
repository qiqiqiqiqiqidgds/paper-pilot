// 一次性脚本：自托管 Noto Serif SC 600/900（unicode-range 分片，浏览器按需加载）
// 产物：public/fonts/noto-serif-sc/*.woff2 + src/app/noto-serif-sc.css
import { mkdir, writeFile } from "node:fs/promises";
import { readFileSync } from "node:fs";

const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36";
const OUT_DIR = "public/fonts/noto-serif-sc";
const CSS_PATH = "src/app/noto-serif-sc.css";
const WEIGHTS = [600, 900];

await mkdir(OUT_DIR, { recursive: true });

async function fetchCss(weight) {
  const url = `https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@${weight}&display=swap`;
  const res = await fetch(url, { headers: { "User-Agent": UA } });
  if (!res.ok) throw new Error(`css HTTP ${res.status}`);
  return res.text();
}

// 解析 @font-face 块：unicode-range + woff2 url
function parseFaces(css) {
  const faces = [];
  const re = /@font-face\s*\{([^}]+)\}/g;
  let m;
  while ((m = re.exec(css))) {
    const block = m[1];
    const url = block.match(/url\((https:\/\/[^)]+)\)\s*format\('woff2'\)/)?.[1];
    const range = block.match(/unicode-range:\s*([^;]+);/)?.[1]?.trim();
    if (url && range) faces.push({ url, range });
  }
  return faces;
}

let cssOut = `/* 自动生成：Noto Serif SC 自托管分片（勿手改；node _fetch_full_fonts.mjs 重新生成） */\n`;
let total = 0;

for (const weight of WEIGHTS) {
  const css = await fetchCss(weight);
  const faces = parseFaces(css);
  console.log(`weight ${weight}: ${faces.length} subsets`);
  let i = 0;
  const queue = [...faces];
  const workers = Array.from({ length: 8 }, async () => {
    while (queue.length) {
      const face = queue.shift();
      i += 1;
      const name = `noto-serif-sc-${weight}-${String(i).padStart(3, "0")}.woff2`;
      const res = await fetch(face.url, { headers: { "User-Agent": UA } });
      if (!res.ok) throw new Error(`font HTTP ${res.status} for ${name}`);
      const buf = Buffer.from(await res.arrayBuffer());
      await writeFile(`${OUT_DIR}/${name}`, buf);
      total += buf.length;
      cssOut += `@font-face{font-family:'Noto Serif SC';font-style:normal;font-weight:${weight};font-display:swap;src:url('/fonts/noto-serif-sc/${name}') format('woff2');unicode-range:${face.range};}\n`;
    }
  });
  await Promise.all(workers);
  console.log(`weight ${weight} done`);
}

await writeFile(CSS_PATH, cssOut, "utf8");
console.log(`saved ${CSS_PATH}; total ${(total / 1024 / 1024).toFixed(1)} MB`);
console.log("FONT_OK");
