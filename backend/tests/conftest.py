"""
Sprint 4 / R2：让 tests/test_e2e_*.py 能 `from test_e2e import ...` 找到共享的
test_e2e.py（基类 + helpers + TestFullLifecycle + main）。

pytest 默认把 rootdir 加到 sys.path（这里是 backend/），但 test_e2e.py 在
backend/tests/ 子目录，所以绝对 import `test_e2e` 找不到。

在 conftest.py 里把 tests/ 显式加到 sys.path 最不侵入（不动 pytest.ini，
不要求 tests/ 必须是 package）。
"""
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

# ===== 测试数据目录隔离（P0：防止测试清空真实 backend/data）=====
# 背景：test_e2e 的 clean_data_dirs() 会对 papers/ppts 目录做 rmtree 级清理。
# 此前 DATA_DIR 未被注入，settings.data_dir 解析到真实 backend/data，
# 跑一次 pytest 就会把用户论文库连同分析结果全部删掉（已发生过真实数据损失）。
# pydantic-settings 中环境变量优先级高于 .env 文件，因此这里注入的绝对路径
# 临时目录必然覆盖 .env 里的 DATA_DIR=./data，且先于一切 app.* import 生效。
_TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="paperpilot-pytest-data-"))
os.environ["DATA_DIR"] = str(_TEST_DATA_DIR)


@atexit.register
def _cleanup_test_data_dir():
    """进程退出时尽力清理本次 pytest 的临时数据目录（失败不影响退出码）"""
    shutil.rmtree(_TEST_DATA_DIR, ignore_errors=True)


# ===== 测试环境变量注入（pytest 模式下唯一权威来源）=====
# pytest 会先 import conftest.py，再 import 任何 test 模块；因此这里的赋值必然
# 先于一切 `from app.config import settings`（config.py:136 创建进程级单例），
# settings 在创建时就拿到这组值 —— 与 pytest 的模块收集顺序无关，任意顺序都确定。
# 用直接赋值而非 setdefault：覆盖 CI job env / shell 里可能残留的旧值，避免
# test_auth_ratelimit 与 test_e2e 对同一份 env 各写各的造成 import 竞态。
os.environ["APP_API_KEY"] = "e2e-test-api-key-2026"   # 全测试统一 key（鉴权开启）
os.environ["RATE_LIMIT_GENERAL_PER_MIN"] = "5"        # 限流测试需要小值
os.environ["RATE_LIMIT_EXPENSIVE_PER_MIN"] = "3"
os.environ["LLM_API_KEY"] = ""                       # e2e 不调真实 LLM（兼容老 DEEPSEEK_API_KEY 别名）
os.environ["TAVILY_API_KEY"] = ""
# 测试环境固定用 tavily provider：conftest/e2e 里 mock 的是 TavilyClient.search_related_papers，
# 若默认 arxiv provider 则 mock 不生效（arXiv 无需 key，测试不应打外网）
os.environ["SEARCH_PROVIDER"] = "tavily"
# 说明：脚本模式（python -m tests.test_xxx）不经过 conftest，env 由各文件头部
# 自带的 os.environ.setdefault 兜底，见各文件顶部注释。

# 把 tests/ 目录加到 sys.path（process-wide，影响所有测试模块的 import）
_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
