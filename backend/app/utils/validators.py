"""
共享验证工具：路径参数、白名单、文件 magic number 等

集中放置，避免在多个 endpoint 重复实现。
"""
import re

from fastapi import HTTPException


# paper_id 允许的字符集：字母数字 + 短横线 + 下划线
# （与 utils/storage.py 的 generate_paper_id 输出一致；用户输入的 paper_id 也应满足）
PAPER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")

# 允许的分析类型（与前端 AnalysisType 对齐）
ALLOWED_ANALYSIS_TYPES = frozenset({"breakdown", "innovation", "flaws", "compare"})

# 允许的文件后缀（小写）
ALLOWED_FILE_EXTENSIONS = frozenset({".pdf", ".docx"})

# 文件 magic number（防止扩展名伪装）
# PDF: "%PDF-"
PDF_MAGIC = b"%PDF-"
# DOCX 是 ZIP：PK\x03\x04
DOCX_MAGIC = b"PK\x03\x04"

# P3-2: 删除未使用的 MAX_FILE_SIZE 常量（单一来源是
# app.config.settings.max_upload_size_bytes，upload.py 等处均直读 settings）。

# P2-4: 回显白名单 —— 校验失败时 400 detail 会被回显进 HTTP 响应 / SSE error
# 事件（analyze.py 的 _event_stream 直接把 he.detail 放进 error 事件 payload）。
# 任意输入（HTML、控制字符、日志注入换行）原样回显存在注入面，回显前先清洗：
# 只保留 paper_id 合法字符集内的可见字符，其余一律替换为 "?"（保留部分内容
# 线索便于调试定位，但不可注入）；再截断长度，防超长输入撑爆响应。
_ECHO_SAFE_RE = re.compile(r"[^A-Za-z0-9_\-]")


def _safe_echo(value: str, max_len: int = 32) -> str:
    """P2-4: 清洗要回显进错误信息的原始输入（白名单替换 + 长度截断）"""
    if not value:
        return ""
    return _ECHO_SAFE_RE.sub("?", value)[:max_len]


def validate_paper_id(paper_id: str) -> str:
    """
    校验 paper_id 格式（路径参数/请求体）
    防止路径穿越 + 不合法字符注入

    :return: 校验后的 paper_id（原值）
    :raises: HTTPException 400
    """
    if not paper_id or not isinstance(paper_id, str):
        raise HTTPException(status_code=400, detail="paper_id 不能为空")

    if not PAPER_ID_PATTERN.fullmatch(paper_id):
        raise HTTPException(
            status_code=400,
            # P2-4: 回显前清洗 —— 不得把 HTML/控制字符/超长输入原样写进 400 响应
            detail=f"非法的 paper_id（仅允许字母数字、短横线、下划线，长度 1-64）：{_safe_echo(paper_id)}",
        )
    return paper_id


def validate_analysis_type(analysis_type: str) -> str:
    """
    校验分析类型（路径参数/请求体）
    防止任意字符串注入 LLM 调用或文件系统
    """
    if analysis_type not in ALLOWED_ANALYSIS_TYPES:
        raise HTTPException(
            status_code=400,
            # P2-4: 同上，回显前清洗（该 detail 也会被 SSE error 事件携带）
            detail=f"不支持的分析类型: {_safe_echo(analysis_type)}，允许: {sorted(ALLOWED_ANALYSIS_TYPES)}",
        )
    return analysis_type


def validate_filename(filename: str) -> str:
    """
    校验下载文件名（防止路径穿越）

    :raises: HTTPException 400
    """
    if not filename:
        raise HTTPException(status_code=400, detail="filename 不能为空")
    # 禁止任何路径分隔符、相对路径前缀
    if ".." in filename or "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(status_code=400, detail="非法文件名")
    if len(filename) > 128:
        raise HTTPException(status_code=400, detail="文件名过长")
    return filename


def check_file_magic(content: bytes, suffix: str) -> bool:
    """
    校验文件 magic number 是否与扩展名一致
    防止 ".pdf" 实际是恶意脚本

    :return: True if valid
    """
    if not content or len(content) < 8:
        return False
    if suffix == ".pdf":
        return content[:5] == PDF_MAGIC
    if suffix == ".docx":
        # DOCX 是 ZIP 格式
        return content[:4] == DOCX_MAGIC
    return False


def sanitize_filename_for_display(filename: str, max_len: int = 80) -> str:
    """
    用于展示/日志的清洗（不用于文件系统操作）
    移除控制字符 + 截断长度
    """
    # 移除控制字符（包括 \n \r \t 等日志注入向量）
    cleaned = re.sub(r"[\x00-\x1f\x7f]", "", filename)
    return cleaned[:max_len]