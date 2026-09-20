# PaperPilot 桌面版（Electron）

把 PaperPilot 的 FastAPI 后端（PyInstaller 打包）与 Next.js 前端（静态导出）装进一个
Electron 壳，产出一个可安装的 Windows 桌面应用。架构与设计依据见仓库根的
《可行性报告-Electron打包-2026-09-20.md》。

## 架构

```
paperpilot.exe (Electron 主进程)
  1. 单实例锁 → 探测空闲端口（127.0.0.1）
  2. spawn resources/backend/paperpilot-backend.exe，注入环境变量：
       APP_HOST=127.0.0.1  APP_PORT=<动态>
       DATA_DIR=<userData>/data   LOG_DIR=<userData>/logs
       SERVE_STATIC_DIR=resources/frontend
  3. 轮询 /api/health 就绪 → BrowserWindow 加载 http://127.0.0.1:<port>/
  4. 退出时 taskkill /T /F 杀后端进程树
```

前端页面与 API 同源（都由后端进程提供），无 CORS、无 BFF；LLM Key 等配置用应用内
"设置"对话框填写（存 `userData/data/settings.json`，即时生效）。

## 目录

```
desktop/
├── src/main.js            # Electron 主进程（生命周期 / 进程管理）
├── src/preload.js         # 最小 contextBridge
├── scripts/assemble.mjs   # 组装 backend/dist + frontend/out → resources/
├── resources/             # assemble 产物（git 忽略；打包时进 extraResources）
├── release/               # electron-builder 输出（git 忽略）
└── package.json           # electron-builder 配置（NSIS，per-user 安装）
```

## 构建全流程

前置：Windows x64 + Python 3.12（`py -3.12`）+ Node 18+。

```powershell
# 1. 后端：PyInstaller onedir（首次先建 venv 装依赖）
cd backend
py -3.12 -m venv venv
.\venv\Scripts\pip install -r requirements.txt pyinstaller
.\venv\Scripts\pyinstaller paperpilot-backend.spec --noconfirm --clean

# 2. 前端：静态导出（自动排除 BFF 路由并恢复）
cd ..\frontend
npm install
npm run build:desktop

# 3. 组装 + 冒烟（不起窗口：健康检查 + 首页 200 → exit 0）
cd ..\desktop
npm install
npm run assemble
npm run smoke

# 4. 打包安装程序（NSIS；仅要免安装目录用 dist:dir）
npm run dist        # → release/PaperPilot Setup 1.0.0.exe
npm run dist:dir    # → release/win-unpacked/PaperPilot.exe
```

## 开发调试

- `npm start`：用 `resources/` 里的产物直接起完整桌面应用；
- 后端业务改动：重跑步骤 1 + assemble（前端无需重建）；
- 前端改动：重跑步骤 2 + assemble；
- 后端实时日志：`%APPDATA%\paperpilot-desktop\logs\app.log`（JSON 结构化）。

## 用户数据位置

| 内容 | 路径 |
|------|------|
| 论文库 / 上传 / settings.json | `%APPDATA%\paperpilot-desktop\data\` |
| 后端日志 | `%APPDATA%\paperpilot-desktop\logs\` |

卸载应用不会删除上述目录（用户论文数据安全）。

## 已知注意事项

- **winCodeSign 符号链接问题（本机构建已绕过）**：electron-builder 的 winCodeSign
  工具包含 macOS dylib 符号链接，无开发者模式/管理员权限的 Windows 解压必失败。
  已在 `build.win.signAndEditExecutable: false` 关闭 exe 元数据编辑来跳过该依赖
  （代价：exe 属性显示 Electron 默认产品名/图标）。想恢复：开启 Windows
  「开发者模式」后删掉该配置项。
- **二进制下载卡住**：Electron / NSIS 等二进制默认从 GitHub 下载，国内网络易卡。
  构建前设置镜像环境变量：
  `ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/`
  `ELECTRON_BUILDER_BINARIES_MIRROR=https://npmmirror.com/mirrors/electron-builder-binaries/`
- **npm ≥11.16 allow-scripts**：electron 的 postinstall 会被白名单拦截，需
  `npm approve-scripts electron` 放行后再 `npm rebuild electron`。
- **杀软误报**：PyInstaller 产物常见误报。已用 onedir + 关闭 UPX 缓解；彻底解决需
  代码签名证书（electron-builder `win.signingHashAlgorithms` / cert 配置）。
- **SmartScreen**：未签名 exe 首次运行会提示"Windows 已保护你的电脑"，选择
  "更多信息 → 仍要运行"。
- **图标**：当前用 Electron 默认图标；替换时放 `desktop/assets/icon.ico`（≥256px）
  并在 package.json `build.win.icon` 里引用（需恢复 rcedit，见第一条）。
- **跨平台**：PyInstaller 与 Electron 均不支持交叉编译，macOS/Linux 需在对应平台
  执行同一流程。
