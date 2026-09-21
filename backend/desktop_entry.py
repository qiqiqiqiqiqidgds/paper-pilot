"""
PaperPilot 桌面版后端入口（PyInstaller 打包用）。

与 `python -m uvicorn app.main:app` 等价，但做了三点适配：

1. 直接传 app 对象而非 import 字符串 —— frozen 环境下避免 uvicorn 内部
   importlib 动态导入 "app.main:app" 的兼容坑；
2. 关闭 reload / 多 worker —— 桌面单实例场景用不到，且两者在 frozen 下不可用；
3. 静态导入 main 与全部 router 模块 —— main.py 里 router 是
   importlib.import_module 动态导入，PyInstaller 静态分析看不见；
   这里显式 import 一遍保证收集（spec 里 collect_submodules('app') 双保险）。

所有运行配置（APP_HOST / APP_PORT / DATA_DIR / LOG_DIR / SERVE_STATIC_DIR /
LLM_* 等）由 Electron 壳通过环境变量注入，pydantic-settings 的
环境变量优先级高于 .env，天然支持。
"""
from __future__ import annotations

import os

import uvicorn

# 静态导入：PyInstaller 依赖入口脚本的 import 图收集模块。
# 注意用 as 别名：下面入口函数若命名为 main 会把模块名遮蔽掉
# （from app import main + def main() → main.app 报 AttributeError）。
import app.main as app_main  # noqa: F401  导入即完成路由注册 / lifespan 挂载
from app.api import (  # noqa: F401
    analyze,
    compare_papers,
    health,
    ppt,
    search,
    settings as settings_api,  # 避免与 config 的 settings 混淆
    upload,
)


def _watch_parent_windows() -> None:
    """父进程看护（防孤儿后端）：Electron 主进程退出时本进程立即自杀。

    背景：Electron 被任务管理器强杀 / 崩溃时，before-quit 里的 taskkill
    不会执行，后端将永久存活并锁住 DATA_DIR，下次启动出现双实例并发写。
    通过 PAPERPILOT_PARENT_PID（由 Electron 注入）在子线程等待父进程句柄，
    父进程一消失即 os._exit —— 不走优雅关闭（避免 lifespan 清理在异常
    状态下悬挂）。仅 Windows；拿不到句柄（权限/已退出）则退回无看护。
    """
    raw = os.environ.get("PAPERPILOT_PARENT_PID", "")
    if not raw.isdigit() or os.name != "nt":
        return
    import ctypes
    import threading

    SYNCHRONIZE = 0x00100000
    INFINITE = 0xFFFFFFFF
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(SYNCHRONIZE, False, int(raw))
    if not handle:
        return

    def _wait_parent() -> None:
        kernel32.WaitForSingleObject(handle, INFINITE)
        kernel32.CloseHandle(handle)
        os._exit(0)

    threading.Thread(target=_wait_parent, name="parent-watchdog", daemon=True).start()


def run() -> None:
    _watch_parent_windows()
    uvicorn.run(
        app_main.app,
        host=app_main.settings.app_host,
        port=app_main.settings.app_port,
        log_level=app_main.settings.log_level.lower(),
        access_log=False,  # 桌面版减噪；结构化业务日志照常写 LOG_DIR/app.log
    )


if __name__ == "__main__":
    run()
