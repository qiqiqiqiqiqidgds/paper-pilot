# -*- mode: python ; coding: utf-8 -*-
"""PaperPilot 后端 PyInstaller 打包配置（onedir 模式）。

构建（在 backend 的 venv 中执行）：
    pyinstaller paperpilot-backend.spec --noconfirm --clean

产物：dist/paperpilot-backend/（整个目录需一起分发，exe 不能脱离目录运行）

要点：
  - onedir 而非 onefile：启动快 2~5 秒、杀软误报率显著更低
  - collect_submodules('app')：main.py 的 router 用 importlib 动态导入，
    静态分析收集不到，这里整包收集（desktop_entry.py 的显式 import 是双保险）
  - UPX 关闭：压缩壳是杀软误报的重灾区
"""
from PyInstaller.utils.hooks import collect_submodules

a = Analysis(
    ["desktop_entry.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=collect_submodules("app"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 桌面版用不到的重量级模块，减小体积。
        # 注意：不要排除 uvicorn.* / watchfiles —— uvicorn/main.py 顶层无条件
        # 导入 supervisors（其中又拉 watchfiles），排除会直接启动崩溃。
        "tkinter",
        "pydoc_data",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="paperpilot-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # 保留 stdout 便于排查；Electron spawn 时用 windowsHide 隐藏窗口
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="paperpilot-backend",
)
