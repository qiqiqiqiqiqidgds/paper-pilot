"""
文件读取端到端测试（P1 修复后验收）

测试流程：
1. 从 storage 读取已上传的 PDF 文件
2. 用 PDFParser 解析（验证 P0-4 / P1-11/12 修复后的解析逻辑）
3. 验证返回的元数据 / 文本 / 页数
4. 验证 save_ppt 的 paper_id 白名单校验（P0-4）
5. 验证 validators 模块的 paper_id / magic number 校验

用法：
    cd backend
    python -m pytest tests/test_file_reading_e2e.py -v
"""
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings
from app.utils.logger import logger
from app.utils.validators import (
    validate_paper_id,
    validate_analysis_type,
    validate_filename,
    check_file_magic,
    PAPER_ID_PATTERN,
    ALLOWED_ANALYSIS_TYPES,
)
from app.services.pdf_parser import PDFParser
from app.utils.storage import (
    file_exists,
    get_paper_path,
    load_text_json,
    generate_paper_id,
)

PASS = "✅"
FAIL = "❌"

# 仓库自带的真实样本（只读）
REPO_SAMPLE_PDF = BACKEND_DIR / "data" / "papers" / "test_samples" / "transformer_sample.pdf"


def check(name: str, condition: bool, detail: str = ""):
    icon = PASS if condition else FAIL
    suffix = f" — {detail}" if detail else ""
    print(f"  {icon} {name}{suffix}")
    return condition


def test_validators():
    """测试共享 validators（P1-4/5/2）"""
    print(f"\n{'='*60}\n1️⃣  validators 模块（P1-4/5/2）\n{'='*60}")

    ok = True

    # paper_id 校验
    ok &= check("paper_id 合法", validate_paper_id("p_2026_07_19_abc12345") == "p_2026_07_19_abc12345")
    ok &= check("paper_id 短横线合法", validate_paper_id("abc-def-123") == "abc-def-123")
    ok &= check("paper_id 路径穿越拦截", _raises_http(lambda: validate_paper_id("../etc/passwd")))
    ok &= check("paper_id 空拦截", _raises_http(lambda: validate_paper_id("")))
    ok &= check("paper_id 含特殊字符拦截", _raises_http(lambda: validate_paper_id("abc/def")))
    ok &= check("paper_id 超长（>64）拦截", _raises_http(lambda: validate_paper_id("a" * 65)))

    # analysis_type 校验
    ok &= check("analysis_type breakdown 合法", validate_analysis_type("breakdown") == "breakdown")
    ok &= check("analysis_type 注入拦截", _raises_http(lambda: validate_analysis_type("../breakdown")))
    ok &= check("analysis_type 未知拦截", _raises_http(lambda: validate_analysis_type("unknown")))
    ok &= check(f"ALLOWED_ANALYSIS_TYPES = {sorted(ALLOWED_ANALYSIS_TYPES)}",
                ALLOWED_ANALYSIS_TYPES == frozenset({"breakdown", "innovation", "flaws", "compare"}))

    # filename 校验
    ok &= check("filename 合法", validate_filename("paper_abc12345.pptx") == "paper_abc12345.pptx")
    ok &= check("filename ../ 拦截", _raises_http(lambda: validate_filename("../etc/passwd")))
    ok &= check("filename / 拦截", _raises_http(lambda: validate_filename("a/b.pptx")))
    ok &= check("filename 隐藏文件拦截", _raises_http(lambda: validate_filename(".bashrc")))

    # Magic Number 校验
    pdf_content = b"%PDF-1.4\nhello"
    docx_content = b"PK\x03\x04hello"
    fake_pdf = b"<html>not a pdf</html>"
    ok &= check("Magic: 真 PDF 识别", check_file_magic(pdf_content, ".pdf"))
    ok &= check("Magic: 真 DOCX 识别", check_file_magic(docx_content, ".docx"))
    ok &= check("Magic: HTML 伪装 PDF 拦截", not check_file_magic(fake_pdf, ".pdf"))
    ok &= check("Magic: 空内容拦截", not check_file_magic(b"", ".pdf"))

    assert ok


def _raises_http(fn):
    """检查 fn 是否抛 HTTPException"""
    from fastapi import HTTPException
    try:
        fn()
        return False
    except HTTPException:
        return True
    except Exception:
        return False


def test_pdf_parsing():
    """测试 PDF 解析（P0-4 修复后）"""
    print(f"\n{'='*60}\n2️⃣  PDF 解析（已有样本 + 解析逻辑）\n{'='*60}")

    # 用仓库内已提交的真实样本定位，不依赖 CWD（Path(__file__) 推导绝对路径）
    if not REPO_SAMPLE_PDF.exists():
        print(f"  ⚠️  未找到测试样本 PDF，跳过解析测试: {REPO_SAMPLE_PDF}")
        pytest.skip(f"测试样本 PDF 不存在: {REPO_SAMPLE_PDF}")

    pdf_path = REPO_SAMPLE_PDF
    print(f"  📄 使用样本: {pdf_path}")

    ok = True
    try:
        with PDFParser(pdf_path) as parser:
            ok &= check("解析无异常", True)

            # 元数据
            meta = parser.extract_metadata()
            title = meta.title or ""
            print(f"     标题: {title[:60]}")
            print(f"     作者: {', '.join(meta.authors[:3])}")
            print(f"     年份: {meta.year}")
            ok &= check("标题非空", len(title) > 0)
            ok &= check("作者解析成功（list 类型）", isinstance(meta.authors, list))

            # 页数
            ok &= check("页数 >= 1", parser.page_count >= 1)
            print(f"     页数: {parser.page_count}")

            # 文本提取
            pages = parser.extract_pages()
            ok &= check("页面列表长度匹配页数", len(pages) == parser.page_count)

            if pages:
                first_page = pages[0]
                print(f"     首页字符数: {len(first_page.text)}")
                ok &= check("首页文本非空", len(first_page.text) > 50)

            # 全文本
            full_text = parser.extract_text() if hasattr(parser, "extract_text") else "\n".join(p.text for p in pages)
            ok &= check("全文非空", len(full_text) > 100)
            print(f"     全文总字符数: {len(full_text)}")

    except Exception as e:
        ok &= check(f"解析异常捕获: {type(e).__name__}: {e}", False)
        logger.exception("PDF 解析异常")

    assert ok


def test_storage_roundtrip():
    """测试 storage 读写闭环（在测试沙箱里自建论文，不读真实用户数据）"""
    print(f"\n{'='*60}\n3️⃣  storage 读写闭环\n{'='*60}")

    ok = True

    if not REPO_SAMPLE_PDF.exists():
        pytest.skip(f"仓库样本不存在: {REPO_SAMPLE_PDF}")

    # 在测试数据目录（conftest 已把 DATA_DIR 指向临时目录）自建一篇论文
    import json
    import shutil as _shutil

    paper_id = generate_paper_id()
    paper_dir = Path(settings.papers_dir) / paper_id
    paper_dir.mkdir(parents=True, exist_ok=True)
    try:
        _shutil.copyfile(REPO_SAMPLE_PDF, paper_dir / "raw.pdf")
        (paper_dir / "text.json").write_text(
            json.dumps(
                {
                    "meta": {"title": "Attention Is All You Need", "authors": [], "year": 2017},
                    "full_text": "We propose Transformer, based solely on attention.",
                    "page_count": 4,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"  📄 沙箱测试论文: {paper_id}")

        # 1. file_exists
        ok &= check("file_exists() 返回 True", file_exists(paper_id))

        # 2. get_paper_path 返回正确
        file_path = get_paper_path(paper_id)
        ok &= check("get_paper_path() 返回有效路径", file_path is not None and file_path.exists())
        if file_path:
            print(f"     文件: {file_path.name} ({file_path.stat().st_size} bytes)")

        # 3. load_text_json
        data = load_text_json(paper_id)
        ok &= check("load_text_json() 返回 dict", isinstance(data, dict))
        if data:
            ok &= check("text.json 含 meta 字段", "meta" in data)
            ok &= check("text.json 含 full_text 字段", "full_text" in data)
            ok &= check("text.json 含 page_count 字段", "page_count" in data)
            if "page_count" in data:
                print(f"     页数（缓存）: {data['page_count']}")
            if "full_text" in data:
                print(f"     文本长度（缓存）: {len(data['full_text'])}")

        # 4. validate_paper_id 应该接受合法的 paper_id
        try:
            validate_paper_id(paper_id)
            ok &= check(f"validate_paper_id({paper_id}) 接受", True)
        except Exception as e:
            ok &= check(f"validate_paper_id({paper_id}) 失败: {e}", False)

        # 5. 测试不存在的 paper_id
        fake_id = "p_9999_99_99_nonexistent"
        ok &= check("file_exists() 对不存在的 paper_id 返回 False", not file_exists(fake_id))
    finally:
        _shutil.rmtree(paper_dir, ignore_errors=True)

    assert ok


@pytest.fixture
def tmp_ppts_dir(tmp_path, monkeypatch):
    """把 settings.data_dir 指向临时目录，save_ppt 不写真实 data/ppts"""
    from app.config import settings
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    return tmp_path


def test_save_ppt_validation(tmp_ppts_dir):
    """测试 save_ppt 的 paper_id 白名单校验（P0-4）"""
    print(f"\n{'='*60}\n4️⃣  save_ppt paper_id 白名单（P0-4）\n{'='*60}")

    from app.services.ppt_generator import save_ppt

    ok = True
    fake_ppt = b"fake pptx content for testing"

    # 合法 paper_id
    try:
        test_id = "p_2026_07_29_test_0001"
        result = save_ppt(fake_ppt, test_id, "test.pptx")
        ok &= check(f"合法 paper_id 接受: {test_id}", result.exists())
    except Exception as e:
        ok &= check(f"合法 paper_id 异常: {e}", False)

    # 非法 paper_id 应被拒绝
    bad_ids = [
        "../etc/passwd",
        "../../tmp/evil",
        "abc/def",
        "abc def",
        "abc\x00null",
        "a" * 100,
    ]
    for bad in bad_ids:
        try:
            save_ppt(fake_ppt, bad, "test.pptx")
            ok &= check(f"非法 paper_id 拦截: {bad[:30]!r}", False)
        except ValueError as e:
            ok &= check(f"非法 paper_id 拦截: {bad[:30]!r}", True, str(e)[:50])
        except Exception as e:
            ok &= check(f"非法 paper_id 拦截: {bad[:30]!r}", True, f"({type(e).__name__})")

    assert ok


def test_generate_paper_id():
    """测试 paper_id 生成"""
    print(f"\n{'='*60}\n5️⃣  paper_id 生成\n{'='*60}")

    ok = True
    ids = [generate_paper_id() for _ in range(5)]
    print(f"  样本: {ids[0]}, {ids[1]}, ...")

    for pid in ids:
        ok &= check(f"格式合法: {pid}", bool(PAPER_ID_PATTERN.fullmatch(pid)))

    ok &= check("生成 5 个不重复", len(set(ids)) == 5)

    assert ok


def main():
    """手动运行入口：直接以 pytest 运行本文件（保证与 CI 行为一致）"""
    import pytest as _pytest
    sys.exit(_pytest.main([str(Path(__file__).resolve())]))


if __name__ == "__main__":
    main()
