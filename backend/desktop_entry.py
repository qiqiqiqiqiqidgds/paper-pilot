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


def run() -> None:
    uvicorn.run(
        app_main.app,
        host=app_main.settings.app_host,
        port=app_main.settings.app_port,
        log_level=app_main.settings.log_level.lower(),
        access_log=False,  # 桌面版减噪；结构化业务日志照常写 LOG_DIR/app.log
    )


if __name__ == "__main__":
    run()
