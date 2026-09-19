# PaperPilot 一键启动脚本（Windows / 开发模式）
# 用法：在本脚本所在目录（即项目根目录）的 PowerShell 中执行
#   powershell -ExecutionPolicy Bypass -File .\start_dev.ps1
#
# 行为：开两个后台窗口分别跑后端 (8000) 和前端 (3000)，并在当前窗口做健康检查。
# 说明：全脚本使用合法 PowerShell 语法（Set-Location / & 调用 / 分步命令），
#       不含 cmd/bash 的 cd /d 或 && 混写。

$root = $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$venvPython = Join-Path $backend "venv\Scripts\python.exe"

# ---- 1. 停掉旧进程（占用 8000 / 3000 端口的进程）----
Write-Host "==> 清理旧进程 (8000 / 3000)..." -ForegroundColor Yellow
Get-NetTCPConnection -LocalPort 8000, 3000 -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
    Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
}

# ---- 2. 后端 venv 检测 / 创建 + 安装依赖 ----
if (-not (Test-Path $venvPython)) {
    Write-Host "==> 检测到后端 venv 不存在，正在创建..." -ForegroundColor Yellow
    Set-Location $backend
    python -m venv venv
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -r (Join-Path $backend "requirements.txt")
    Set-Location $root
} else {
    Write-Host "==> 后端 venv 已存在，跳过安装" -ForegroundColor Green
}

# ---- 3. 前端依赖检查 ----
if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
    Write-Host "==> 安装前端依赖 (npm install)..." -ForegroundColor Yellow
    Set-Location $frontend
    npm install
    Set-Location $root
} else {
    Write-Host "==> 前端 node_modules 已存在，跳过安装" -ForegroundColor Green
}

# ---- 4. 启动后端 (8000) ----
Write-Host "==> 启动后端 (8000)..." -ForegroundColor Cyan
$backendCmd = "`$env:PYTHONIOENCODING='utf-8'; Set-Location '$backend'; .\venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendCmd

# ---- 5. 启动前端 (3000) ----
Write-Host "==> 启动前端 (3000)..." -ForegroundColor Cyan
$frontendCmd = "Set-Location '$frontend'; npm run dev"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontendCmd

# ---- 6. 健康检查（最多等 60 秒）----
Write-Host ""
Write-Host "==> 等待服务就绪（最多 60 秒）..." -ForegroundColor Yellow
$backendReady = $false
$frontendReady = $false
for ($i = 1; $i -le 60; $i++) {
    Start-Sleep -Seconds 1
    try {
        # 探 /api/health 而非 /docs：prod 环境（APP_ENV=prod）下 /docs 已关闭，探它会永远误报未就绪
        $r = Invoke-WebRequest -Uri "http://localhost:8000/api/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($r.StatusCode -eq 200) { $backendReady = $true }
    } catch {}
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:3000" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($r.StatusCode -eq 200) { $frontendReady = $true }
    } catch {}
    if ($backendReady -and $frontendReady) { break }
}

Write-Host ""
if ($backendReady) {
    Write-Host "  - 后端就绪: http://localhost:8000（接口文档 /docs，prod 下关闭）" -ForegroundColor Green
} else {
    Write-Host "  - 后端未就绪（请查看后端窗口日志）" -ForegroundColor Red
}
if ($frontendReady) {
    Write-Host "  - 前端就绪: http://localhost:3000" -ForegroundColor Green
} else {
    Write-Host "  - 前端未就绪（请查看前端窗口日志）" -ForegroundColor Red
}
Write-Host ""
Write-Host "浏览器打开 http://localhost:3000 即可" -ForegroundColor Yellow
