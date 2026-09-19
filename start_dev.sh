#!/bin/bash
# PaperPilot 一键启动脚本（macOS / Linux 开发模式）
# 用法：bash start_dev.sh
# 行为：后台启动后端 (8000) 和前端 (3000)，日志写入 backend.log / frontend.log

set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

# 停掉之前的进程
echo "==> 清理旧进程..."
lsof -ti:8000 2>/dev/null | xargs kill -9 2>/dev/null || true
lsof -ti:3000 2>/dev/null | xargs kill -9 2>/dev/null || true

# 启动后端
echo "==> 启动后端 (8000)..."
cd "$BACKEND"
if [ ! -d "venv" ] || [ ! -f "venv/bin/python" ]; then
  echo "    检测到 venv 异常，重建..."
  rm -rf venv
  python3 -m venv venv
  ./venv/bin/pip install --upgrade pip >/dev/null
  # 按平台选依赖清单：macOS 用适配版（Python 3.14 wheel 兼容），其他平台用原版
  # 注意：set -e 下不能用 `[ "$(uname)" = "Darwin" ] && REQ_FILE=...`，
  # 非 macOS 时该语句返回非零会直接退出脚本，必须用 if/else。
  if [ "$(uname)" = "Darwin" ]; then
    REQ_FILE="requirements-mac.txt"
  else
    REQ_FILE="requirements.txt"
  fi
  ./venv/bin/pip install -r "$REQ_FILE"
fi
nohup ./venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload > "$ROOT/backend.log" 2>&1 &
echo "    PID: $!  日志: $ROOT/backend.log"

# 启动前端
echo "==> 启动前端 (3000)..."
cd "$FRONTEND"
if [ ! -d "node_modules" ]; then
  echo "    安装前端依赖..."
  npm install
fi
nohup npm run dev > "$ROOT/frontend.log" 2>&1 &
echo "    PID: $!  日志: $ROOT/frontend.log"

echo ""
echo "==> 等待 5-10 秒后访问："
echo "    前端: http://localhost:3000"
echo "    后端: http://localhost:8000/docs"
echo ""
echo "==> 看日志："
echo "    tail -f $ROOT/backend.log"
echo "    tail -f $ROOT/frontend.log"
