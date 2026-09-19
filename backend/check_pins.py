"""
依赖版本检查脚本

从 requirements.txt 解析 pin（支持 ==, >=, <=, ~=），到 PyPI 验证版本存在 + 显示最新版本。
每次改 requirements.txt 不用改本脚本。

用法：
    python check_pins.py                  # 检查所有
    python check_pins.py --check fastapi  # 传 env: CHECK="fastapi,openai"
    CHECK=fastapi,openai python check_pins.py
"""
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

REQUIREMENTS = Path(__file__).parent / "requirements.txt"

# 匹配 pin 格式：pkg==1.2.3 / pkg>=1.2.3 / pkg<=1.2.3 / pkg~=1.2.3
# 跳过：注释行（# 开头）、-r / -e 开头的引用行、空白行
PIN_RE = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*(==|>=|<=|~=)\s*([A-Za-z0-9_.\-+]+)\s*(?:#.*)?$")


def parse_requirements(path: Path) -> dict:
    """从 requirements.txt 解析 {pkg: pin_str}"""
    pins = {}
    if not path.exists():
        print(f"❌ 找不到 {path}")
        sys.exit(1)
    for line in path.read_text(encoding="utf-8").splitlines():
        # 跳过空行 / 注释 / 引用
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-") or line.startswith("git+"):
            continue
        m = PIN_RE.match(line)
        if m:
            pkg, op, ver = m.group(1), m.group(2), m.group(3)
            pins[pkg] = f"{op}{ver}"
    return pins


def fetch_pypi_versions(pkg: str, timeout: int = 20) -> tuple:
    """从 PyPI 拿 (versions_set, latest_version)"""
    url = f"https://pypi.org/pypi/{pkg}/json"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = json.load(r)
        versions = set(data["releases"].keys())
        latest = data["info"]["version"]
        return versions, latest
    except Exception as e:
        return None, str(e)


def main():
    pins = parse_requirements(REQUIREMENTS)

    # 通过环境变量 CHECK 过滤子集
    selected = os.environ.get("CHECK", "").strip()
    if selected:
        keys = [k.strip() for k in selected.split(",") if k.strip()]
        missing = [k for k in keys if k not in pins]
        if missing:
            print(f"⚠️  CHECK 中以下包不在 requirements.txt: {missing}")
        pins = {k: pins[k] for k in keys if k in pins}

    if not pins:
        print("❌ requirements.txt 里没有可检查的包")
        sys.exit(1)

    print(f"📋 从 {REQUIREMENTS.name} 解析到 {len(pins)} 个包\n")
    print(f"{'package':<30} {'pin':<12} {'status':<10} {'latest':<12}")
    print("-" * 65)

    ok = 0
    bad = 0
    for pkg, pin in pins.items():
        # 拿掉操作符，只验证版本号
        ver = pin.lstrip(">=<=~")
        versions, latest = fetch_pypi_versions(pkg)
        if versions is None:
            print(f"{pkg:<30} {pin:<12} {'ERR':<10} {latest}")
            bad += 1
            continue
        if ver in versions:
            status = "OK"
            ok += 1
        else:
            status = "MISSING"
            bad += 1
        print(f"{pkg:<30} {pin:<12} {status:<10} {latest}")

    print("-" * 65)
    print(f"📊 结果: {ok} OK / {bad} 有问题 / 共 {ok + bad}")
    return bad == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
