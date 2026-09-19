// Puppeteer 真实浏览器端到端测试
// 跑法（必须用 npx puppeteer-core 接 Edge，或者直接 node 跑）：
//   cd frontend
//   PAPERPILOT_TEST_DOCX=/path/to/paper.docx node tests/browser_upload_test.js
//
// 目的：模拟用户点击"上传文件"按钮 → 选 DOCX → 验证 toast / 列表 / 占位 UI

const puppeteer = require('puppeteer-core');
const path = require('path');
const fs = require('fs');

const FRONTEND_URL = 'http://localhost:3000';
const USER_DOCX = process.env.PAPERPILOT_TEST_DOCX || '';
const SCREENSHOT_DIR = path.join(__dirname, '..', 'tests', 'screenshots');

// Edge 常见位置（按优先级）
const EDGE_PATHS = [
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  process.env.LOCALAPPDATA + '\\Microsoft\\Edge\\Application\\msedge.exe',
];

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

(async () => {
  console.log('=== 启动 Puppeteer (Edge) ===');

  // 找 Edge
  let edgePath = null;
  for (const p of EDGE_PATHS) {
    if (fs.existsSync(p)) {
      edgePath = p;
      break;
    }
  }
  if (!edgePath) {
    console.error('❌ 没找到 Edge，可选位置：');
    EDGE_PATHS.forEach(p => console.error('  - ' + p));
    process.exit(1);
  }
  console.log('Edge 路径: ' + edgePath);

  if (!USER_DOCX || !fs.existsSync(USER_DOCX)) {
    console.error('❌ 未设置 PAPERPILOT_TEST_DOCX 或文件不存在: ' + USER_DOCX);
    process.exit(1);
  }
  console.log('DOCX 存在: ' + USER_DOCX + ' (' + fs.statSync(USER_DOCX).size + ' bytes)');

  if (!fs.existsSync(SCREENSHOT_DIR)) {
    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
  }

  const browser = await puppeteer.launch({
    executablePath: edgePath,
    headless: 'new',           // Edge 109+ 支持 new headless
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
    defaultViewport: { width: 1440, height: 900 },
  });
  console.log('✅ 浏览器已启动');

  const page = await browser.newPage();

  // 监听 console / pageerror 方便调试
  const consoleLogs = [];
  page.on('console', (msg) => {
    const line = `[${msg.type()}] ${msg.text()}`;
    consoleLogs.push(line);
    console.log('  [console] ' + line);
  });
  page.on('pageerror', (err) => {
    console.log('  [pageerror] ' + err.message);
  });

  // 拦截 /api/upload 看请求和响应
  const uploadRequests = [];
  await page.setRequestInterception(true);
  page.on('request', (req) => {
    if (req.url().includes('/api/upload')) {
      console.log('  [request] ' + req.method() + ' ' + req.url());
    }
    req.continue();
  });
  page.on('response', async (res) => {
    if (res.url().includes('/api/upload')) {
      const body = await res.text().catch(() => '<unreadable>');
      uploadRequests.push({ status: res.status(), body: body.slice(0, 500) });
      console.log('  [response] ' + res.status() + ' ' + res.url());
    }
  });

  try {
    // ===== 步骤 1：打开首页 =====
    console.log('\n=== 步骤 1：打开 http://localhost:3000 ===');
    await page.goto(FRONTEND_URL, { waitUntil: 'networkidle0', timeout: 30000 });
    await sleep(2000);
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '01-homepage.png'), fullPage: true });
    console.log('✅ 首页已加载，截图: 01-homepage.png');

    // ===== 步骤 2：检查按钮文案 =====
    console.log('\n=== 步骤 2：检查顶栏按钮文案 ===');
    const buttonText = await page.evaluate(() => {
      const buttons = Array.from(document.querySelectorAll('button'));
      const uploadBtn = buttons.find(b => b.textContent && (b.textContent.includes('上传') || b.textContent.includes('upload')));
      return uploadBtn ? uploadBtn.textContent.trim() : null;
    });
    console.log('按钮文案: ' + JSON.stringify(buttonText));
    if (buttonText && buttonText.includes('上传文件')) {
      console.log('✅ 按钮文案正确（"上传文件"）');
    } else {
      console.log('❌ 按钮文案异常: ' + buttonText);
    }

    // ===== 步骤 3：检查 file input 的 accept 属性 =====
    console.log('\n=== 步骤 3：检查 file input accept ===');
    const inputAccept = await page.evaluate(() => {
      const input = document.querySelector('input[type="file"]');
      return input ? input.getAttribute('accept') : null;
    });
    console.log('accept: ' + inputAccept);
    if (inputAccept && inputAccept.includes('docx')) {
      console.log('✅ input.accept 含 docx');
    } else {
      console.log('❌ input.accept 不含 docx');
    }

    // ===== 步骤 4：点击上传按钮触发 file chooser =====
    console.log('\n=== 步骤 4：点上传按钮 → 选 DOCX ===');
    const [fileChooser] = await Promise.all([
      page.waitForFileChooser({ timeout: 10000 }),
      page.evaluate(() => {
        const buttons = Array.from(document.querySelectorAll('button'));
        const uploadBtn = buttons.find(b => b.textContent && b.textContent.includes('上传文件'));
        if (uploadBtn) uploadBtn.click();
        else {
          // 退而求其次：点整个 dropzone 区域
          const dropzone = document.querySelector('[role="presentation"]');
          if (dropzone) dropzone.click();
        }
      }),
    ]);
    await fileChooser.accept([USER_DOCX]);
    console.log('✅ DOCX 已选择: ' + path.basename(USER_DOCX));

    // ===== 步骤 5：等后端响应 + UI 更新 =====
    console.log('\n=== 步骤 5：等上传完成（最多 15s）===');
    let success = false;
    for (let i = 0; i < 30; i++) {
      await sleep(500);
      const state = await page.evaluate(() => {
        // 看 toaster 区域
        const toasts = Array.from(document.querySelectorAll('[data-sonner-toast], li[data-sonner-toast]'));
        const toastText = toasts.map(t => t.textContent).join(' | ');
        // 看左侧论文列表
        const sidebar = document.querySelector('aside');
        const paperCount = sidebar ? sidebar.querySelectorAll('input[type="checkbox"]').length : 0;
        return { toastText, paperCount };
      });
      if (state.toastText) {
        console.log(`  toast: "${state.toastText}" / 论文数: ${state.paperCount}`);
        if (state.toastText.includes('上传成功') || state.toastText.includes('失败')) {
          success = state.toastText.includes('成功');
          break;
        }
      } else {
        if (i % 4 === 0) console.log(`  等待中… 论文数: ${state.paperCount}`);
      }
    }

    await sleep(2000);
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '02-after-upload.png'), fullPage: true });
    console.log('截图: 02-after-upload.png');

    // ===== 步骤 6：检查列表和占位 UI =====
    console.log('\n=== 步骤 6：检查 UI 状态 ===');
    const uiState = await page.evaluate(() => {
      const sidebar = document.querySelector('aside');
      const paperItems = sidebar ? Array.from(sidebar.querySelectorAll('input[type="checkbox"]')).map(cb => {
        const item = cb.closest('div[class*="rounded"]') || cb.parentElement.parentElement;
        return item ? item.textContent.replace(/\s+/g, ' ').trim().slice(0, 100) : null;
      }).filter(Boolean) : [];
      // 中间 PDF / DOCX 区域
      const main = document.querySelector('main') || document.body;
      const hasPdfCanvas = !!main.querySelector('canvas');
      const hasDownloadLink = !!Array.from(main.querySelectorAll('a, button')).find(el => el.textContent.includes('下载'));
      const hasDocxPlaceholder = main.textContent.includes('DOCX') || main.textContent.includes('Word') || main.textContent.includes('不支持');
      return { paperItems, hasPdfCanvas, hasDownloadLink, hasDocxPlaceholder };
    });
    console.log('论文列表项数: ' + uiState.paperItems.length);
    uiState.paperItems.slice(0, 3).forEach((t, i) => console.log(`  [${i+1}] ${t}`));
    console.log('中间区域 PDF canvas: ' + uiState.hasPdfCanvas);
    console.log('中间区域下载链接/按钮: ' + uiState.hasDownloadLink);
    console.log('中间区域含 DOCX/Word/不支持 字样: ' + uiState.hasDocxPlaceholder);

    // ===== 步骤 7：点击新上传的 DOCX 看占位 UI =====
    console.log('\n=== 步骤 7：点击刚上传的 DOCX ===');
    const clicked = await page.evaluate(() => {
      const sidebar = document.querySelector('aside');
      if (!sidebar) return false;
      const items = Array.from(sidebar.querySelectorAll('input[type="checkbox"]'));
      if (items.length === 0) return false;
      // 最新上传的在最上面
      const target = items[0].closest('div[class*="rounded"]') || items[0].parentElement.parentElement;
      if (target) {
        target.click();
        return true;
      }
      return false;
    });
    console.log('点击结果: ' + clicked);
    await sleep(3000);
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '03-docx-selected.png'), fullPage: true });
    console.log('截图: 03-docx-selected.png');

    const finalState = await page.evaluate(() => {
      const main = document.querySelector('main') || document.body;
      return {
        bodyText: main.textContent.replace(/\s+/g, ' ').slice(0, 500),
        hasDownload: !!Array.from(main.querySelectorAll('a[download], a[href*="/file"]')).find(a => a.href.includes('/file')),
      };
    });
    console.log('选中后主区域文本（前 500 字）: ' + finalState.bodyText);
    console.log('有下载链接: ' + finalState.hasDownload);

    // ===== 总结 =====
    console.log('\n=== 总结 ===');
    console.log('上传请求数: ' + uploadRequests.length);
    uploadRequests.forEach((r, i) => {
      console.log(`  [${i+1}] HTTP ${r.status} body=${r.body.slice(0, 200)}`);
    });
    if (uploadRequests.length > 0) {
      const last = uploadRequests[uploadRequests.length - 1];
      if (last.status === 200) {
        console.log('✅ 浏览器真实上传成功（HTTP 200）');
      } else {
        console.log('❌ 浏览器上传失败 HTTP ' + last.status);
      }
    } else {
      console.log('❌ 浏览器根本没发出 /api/upload 请求（前端拦了）');
    }

  } catch (e) {
    console.error('💥 测试过程出错: ' + e.message);
    console.error(e.stack);
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'error.png'), fullPage: true });
  } finally {
    await browser.close();
    console.log('\n浏览器已关闭');
  }
})();
