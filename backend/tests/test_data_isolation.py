"""
测试数据目录隔离防回归（P0：防止 pytest 清空真实 backend/data 的事故复发）

背景：conftest.py 曾未注入 DATA_DIR，test_e2e 的 clean_data_dirs() 直接对
真实 backend/data/papers 做 rmtree，跑一次 pytest 就清空用户论文库
（2026-09-06 已发生过真实数据损失）。

本文件的三条防线：
1. pytest 进程内 settings.data_dir 必须指向临时目录（conftest 注入生效）；
2. test_e2e.clean_data_dirs 对真实数据目录必须拒绝执行（双保险 raise）；
3. 真实 backend/data/papers 下（除 test_samples）必须保持 pytest 不碰。
"""
import os
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings


def test_settings_data_dir_is_not_real_data_dir():
    """防线 1：pytest 进程的 settings.data_dir 不得指向真实 backend/data"""
    real_data_dir = (BACKEND_DIR / "data").resolve()
    test_data_dir = Path(settings.data_dir).resolve()
    assert test_data_dir != real_data_dir, (
        f"settings.data_dir 指向了真实数据目录 {test_data_dir}！"
        "conftest.py 的 DATA_DIR 注入失效，继续跑会清空用户论文库。"
    )
    assert Path(settings.papers_dir) == test_data_dir / "papers"


def test_settings_data_dir_env_is_injected():
    """防线 1b：DATA_DIR 环境变量已被 conftest 注入为绝对路径临时目录"""
    env_data_dir = os.environ.get("DATA_DIR")
    assert env_data_dir, "DATA_DIR 未被 conftest.py 注入"
    assert Path(env_data_dir).is_absolute(), f"DATA_DIR 应为绝对路径，实际: {env_data_dir}"
    assert Path(env_data_dir).resolve() != (BACKEND_DIR / "data").resolve()


def test_clean_data_dirs_refuses_real_data_dir(tmp_path, monkeypatch):
    """防线 2：clean_data_dirs 对"真实数据目录"必须 raise（双保险验证）

    安全设计：不把真实 backend/data 当靶子——若双保险逻辑本身坏掉
    （判不出来、就地执行清理），本测试就会亲手删库（2026-09-06 实际发生过）。
    因此把 test_e2e 的 REAL_* 常量 monkeypatch 成 tmp 假目录，验证的是
    「路径与 REAL_* 相等 → raise」这条逻辑，靶子永远是假目录。
    """
    import test_e2e

    # 在 tmp 里伪造一个"看起来真实"的数据目录，并塞一个论文进去
    fake_real_data = tmp_path / "fake-real-data"
    fake_papers = fake_real_data / "papers"
    fake_ppts = fake_real_data / "ppts"
    fake_papers.mkdir(parents=True)
    fake_ppts.mkdir(parents=True)
    victim = fake_papers / "p_2026_01_01_deadbeef"
    victim.mkdir()
    (victim / "text.json").write_text("{}", encoding="utf-8")

    original = (test_e2e.PAPERS_DIR, test_e2e.PPTS_DIR, test_e2e.DATA_DIR,
                test_e2e.REAL_DATA_DIR, test_e2e.REAL_PAPERS_DIR, test_e2e.REAL_PPTS_DIR)
    try:
        monkeypatch.setattr(test_e2e, "REAL_DATA_DIR", fake_real_data)
        monkeypatch.setattr(test_e2e, "REAL_PAPERS_DIR", fake_papers)
        monkeypatch.setattr(test_e2e, "REAL_PPTS_DIR", fake_ppts)
        monkeypatch.setattr(test_e2e, "PAPERS_DIR", fake_papers)
        monkeypatch.setattr(test_e2e, "PPTS_DIR", fake_ppts)
        monkeypatch.setattr(test_e2e, "DATA_DIR", fake_real_data)

        with pytest.raises(RuntimeError, match="拒绝执行"):
            test_e2e.clean_data_dirs()

        # raise 发生在清理之前：靶子里的"论文"必须完好
        assert victim.exists(), "clean_data_dirs 应在删除任何文件前 raise"
    finally:
        (test_e2e.PAPERS_DIR, test_e2e.PPTS_DIR, test_e2e.DATA_DIR,
         test_e2e.REAL_DATA_DIR, test_e2e.REAL_PAPERS_DIR, test_e2e.REAL_PPTS_DIR) = original
