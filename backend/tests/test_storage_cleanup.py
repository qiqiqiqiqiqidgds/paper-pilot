"""
PPT 孤儿清理回归测试（防止 cleanup_orphan_ppts 误删合法 PPT 的 bug 复发）

背景：app/utils/storage.py::cleanup_orphan_ppts 曾用 stem.split("_",1)[0] 提取
paper_id，对形如 "p_2026_01_01_abcd1234_mydeck.pptx" 的文件恒得到 "p"，
导致所有以 "p" 开头的论文目录都被误判为"论文不存在"→ 误删全部 PPT。

回归点：
- 合法 paper_id（generate_paper_id / 固定合法 id）对应的 PPT 必须被保留；
- 论文目录不存在（真正孤儿）的 PPT 必须被删除；
- 命名不合法的 PPT 应被跳过（不误删、不抛异常）。

注意：本测试用 monkeypatch 把 settings.data_dir 指向 tmp_path，不污染真实数据目录。
"""
import json
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings
from app.utils.storage import (
    cleanup_orphan_ppts,
    generate_paper_id,
    get_paper_dir,
    save_analysis_result,
    save_text_json,
)


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    """把 settings.data_dir 指向临时目录（papers/ + ppts/），避免污染真实数据"""
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    (tmp_path / "papers").mkdir(parents=True, exist_ok=True)
    (tmp_path / "ppts").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _make_ppt(ppts_dir: Path, name: str) -> Path:
    """在临时 ppts 目录写一个假 PPT 文件"""
    ppt = ppts_dir / name
    ppt.write_bytes(b"fake pptx content for cleanup test")
    return ppt


def test_cleanup_keeps_ppt_with_generated_paper_id(tmp_data_dir):
    """回归 1：合法 generate_paper_id() 对应的 PPT 必须保留（原 bug 场景）"""
    paper_id = generate_paper_id()  # 形如 p_2026_08_03_abcd1234
    get_paper_dir(paper_id)         # 创建合法论文目录

    ppt = _make_ppt(tmp_data_dir / "ppts", f"{paper_id}_mydeck.pptx")

    removed = cleanup_orphan_ppts()

    assert removed == 0, f"合法 paper_id 的 PPT 不应被删除，实际清理 {removed} 个"
    assert ppt.exists(), "合法 paper_id 的 PPT 不应被当作孤儿删除"


def test_cleanup_keeps_ppt_with_fixed_legal_paper_id(tmp_data_dir):
    """回归 2：固定合法 id（p_2026_01_01_abcd1234）对应的 PPT 必须保留"""
    paper_id = "p_2026_01_01_abcd1234"
    get_paper_dir(paper_id)

    ppt = _make_ppt(tmp_data_dir / "ppts", f"{paper_id}_slides.pptx")

    removed = cleanup_orphan_ppts()

    assert removed == 0, f"固定合法 paper_id 的 PPT 不应被删除，实际清理 {removed} 个"
    assert ppt.exists(), "固定合法 paper_id 的 PPT 不应被当作孤儿删除"


def test_cleanup_removes_orphan_ppt(tmp_data_dir):
    """回归 3：论文目录不存在的 PPT → 被当孤儿删除"""
    # 用合法生成的 paper_id 命名（p_日期_uuid8），但该论文目录不存在 → 真孤儿
    orphan_ppt = _make_ppt(tmp_data_dir / "ppts", "p_2099_99_99_abcdef12_deck.pptx")

    removed = cleanup_orphan_ppts()

    assert removed == 1, f"应清理 1 个孤儿 PPT，实际清理 {removed} 个"
    assert not orphan_ppt.exists(), "孤儿 PPT 应被删除"


def test_cleanup_skips_invalid_named_ppt(tmp_data_dir):
    """回归 4：paper_id 前缀不合法的 PPT → 跳过（不误删、不抛异常）"""
    # 前缀含空格/非法字符，不可能是合法 paper_id
    invalid_ppt = _make_ppt(tmp_data_dir / "ppts", "my deck notes.pptx")

    removed = cleanup_orphan_ppts()

    assert removed == 0, "命名不合法的 PPT 应被跳过"
    assert invalid_ppt.exists(), "命名不合法的 PPT 不应被误删"


def test_cleanup_keeps_old_ppt_when_paper_exists(tmp_data_dir):
    """回归 5：论文还在时，超老的 PPT 也必须保留（不按 mtime 无差别清理）"""
    import os
    import time as time_lib

    paper_id = "p_2026_01_01_aaaa1111"
    get_paper_dir(paper_id)

    old_ppt = _make_ppt(tmp_data_dir / "ppts", f"{paper_id}_old_deck.pptx")
    # 把 mtime 拨到 400 天前，模拟"很久以前生成的 PPT"
    old_ts = time_lib.time() - 400 * 24 * 3600
    os.utime(old_ppt, (old_ts, old_ts))

    removed = cleanup_orphan_ppts()

    assert removed == 0, f"论文还在时不应按时间清理 PPT，实际清理 {removed} 个"
    assert old_ppt.exists(), "论文还在时老 PPT 不应被删除"


def test_cleanup_mixed_scenario(tmp_data_dir):
    """回归 6：合法 + 孤儿混合时只删孤儿，保留合法（最贴近真实数据）"""
    paper_id = "p_2026_05_05_aaaa1111"
    get_paper_dir(paper_id)

    kept_ppt = _make_ppt(tmp_data_dir / "ppts", f"{paper_id}_deck.pptx")
    orphan_ppt = _make_ppt(tmp_data_dir / "ppts", "p_2000_01_01_bbbb2222_stale.pptx")

    removed = cleanup_orphan_ppts()

    assert removed == 1, f"应只清理 1 个孤儿，实际清理 {removed} 个"
    assert kept_ppt.exists(), "合法 PPT 应保留"
    assert not orphan_ppt.exists(), "孤儿 PPT 应被删除"


def test_save_analysis_result_does_not_revive_deleted_paper(tmp_data_dir):
    """B2 回归：论文删除后 save_analysis_result 返回 False 且不复活目录"""
    paper_id = "p_2026_05_05_cccc3333"
    paper_dir = get_paper_dir(paper_id)
    (paper_dir / "text.json").write_text("{}", encoding="utf-8")

    # 模拟"分析期间用户删除论文"
    from app.utils.storage import delete_paper
    delete_paper(paper_id)

    result = save_analysis_result(paper_id, "breakdown", {"summary": "x"})

    assert result is False, "论文已删除时 save_analysis_result 应返回 False"
    assert not (Path(settings.papers_dir) / paper_id).exists(), (
        "保存分析结果不应复活已删除的论文目录"
    )


def test_save_analysis_result_writes_when_paper_exists(tmp_data_dir):
    """B2 反向用例：论文存在（目录 + text.json）时保存仍正常"""
    paper_id = "p_2026_05_05_dddd4444"
    paper_dir = get_paper_dir(paper_id)
    (paper_dir / "text.json").write_text("{}", encoding="utf-8")

    result = save_analysis_result(paper_id, "breakdown", {"summary": "x"})

    assert result is not False, "论文存在时应返回结果文件路径"
    assert result.exists(), "分析结果文件应已写入"
    assert result.name == "analysis_breakdown.json"


def test_generate_paper_id_avoids_existing_dir(tmp_data_dir):
    """B7 回归：生成的 paper_id 不与已有目录冲突（存在即重试避开）"""
    papers_dir = Path(settings.papers_dir)
    # 构造一个"已存在"目录，生成 50 个 id，断言都不与任何已存在目录重名且不重复
    (papers_dir / "p_2026_05_05_aaaa1111").mkdir()
    seen = set()
    for _ in range(50):
        pid = generate_paper_id()
        assert not (papers_dir / pid).exists(), f"生成的 paper_id {pid} 已存在（应重试避开）"
        seen.add(pid)
    assert len(seen) == 50, "生成的 paper_id 不应重复"


# ===== P2-3：JSON 落盘原子写（tmp + replace）回归 =====

def _patch_json_dumps_boom(monkeypatch):
    """把全局 json.dumps 替换为必抛异常（模拟序列化失败，如 P0-1 的 Point 不可序列化）"""
    import json as json_lib

    def _boom(*args, **kwargs):
        raise ValueError("模拟序列化失败（Object of type Point is not JSON serializable）")

    monkeypatch.setattr(json_lib, "dumps", _boom)


def test_save_text_json_atomic_keeps_original_on_dump_failure(tmp_data_dir, monkeypatch):
    """P2-3 回归：text.json 序列化抛错时原文件不被破坏、不留半截 tmp 文件

    复现 P0-1 的受害链路：get_toc(simple=False) 的 Point 对象让 json.dumps 抛
    TypeError，旧实现 write_text 前半程可能留下半截 JSON / 空文件。
    """
    paper_id = "p_2026_05_05_eeee5555"
    paper_dir = get_paper_dir(paper_id)
    text_json = paper_dir / "text.json"
    text_json.write_text('{"keep": true}', encoding="utf-8")

    _patch_json_dumps_boom(monkeypatch)

    with pytest.raises(ValueError):
        save_text_json(paper_id, {"toc": [[1, "Introduction", {"dest": "bad"}]]})

    assert text_json.read_text(encoding="utf-8") == '{"keep": true}', (
        "序列化失败后原 text.json 内容不得被破坏"
    )
    assert not list(paper_dir.glob("*.tmp")), "失败后不应残留 .tmp 临时文件"


def test_save_analysis_result_atomic_keeps_original_on_dump_failure(tmp_data_dir, monkeypatch):
    """P2-3 回归：analysis_*.json 序列化抛错时原文件不被破坏、不留半截 tmp 文件"""
    paper_id = "p_2026_05_05_ffff6666"
    paper_dir = get_paper_dir(paper_id)
    (paper_dir / "text.json").write_text("{}", encoding="utf-8")
    analysis_file = paper_dir / "analysis_breakdown.json"
    analysis_file.write_text('{"old": 1}', encoding="utf-8")

    _patch_json_dumps_boom(monkeypatch)

    with pytest.raises(ValueError):
        save_analysis_result(paper_id, "breakdown", {"summary": "new"})

    assert analysis_file.read_text(encoding="utf-8") == '{"old": 1}', (
        "序列化失败后原分析结果文件不得被破坏"
    )
    assert not list(paper_dir.glob("*.tmp")), "失败后不应残留 .tmp 临时文件"


def test_save_text_json_atomic_overwrite_happy_path(tmp_data_dir):
    """P2-3 反向用例：正常路径下 tmp+replace 覆盖旧内容生效（Windows replace 语义）"""
    paper_id = "p_2026_05_05_aaaa7777"
    save_text_json(paper_id, {"v": 1})
    text_json = Path(settings.papers_dir) / paper_id / "text.json"
    assert json.loads(text_json.read_text(encoding="utf-8")) == {"v": 1}

    save_text_json(paper_id, {"v": 2})
    assert json.loads(text_json.read_text(encoding="utf-8")) == {"v": 2}, "第二次保存应覆盖旧内容"
    assert not list(text_json.parent.glob("*.tmp")), "成功后不应残留 .tmp 临时文件"
