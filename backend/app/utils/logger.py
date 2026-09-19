"""
日志工具（Sprint 2 / I1+I2 升级）

输出 JSON 结构化日志（python-json-logger），自动注入 request_id
（来自 contextvars，通过 RequestIDFilter）。

调用方无须改：
  logger.info("分析完成")  # 输出 {"ts": "...", "level": "INFO", "request_id": "abc...", "message": "分析完成"}

推荐用 extra 注入自定义字段（结构化可索引）：
  logger.info("分析完成", extra={"paper_id": pid, "type": "breakdown"})
"""
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from pythonjsonlogger import jsonlogger

from app.config import settings
from app.utils.request_context import get_request_id


class RequestIDFilter(logging.Filter):
    """每条日志 record 注入 request_id（从 contextvars 取）"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


def setup_logger(name: str = "paperpilot", level: Optional[str] = None) -> logging.Logger:
    """配置并返回 logger（控制台 + 文件双 handler，JSON 格式）"""
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    # 日志级别：显式传入优先，否则用 settings.log_level（P1 修复：不再硬编码 INFO）
    # 兼容非法级别：getattr 找不到就回退 INFO
    raw_level = (level or settings.log_level or "INFO").upper()
    numeric_level = getattr(logging, raw_level, logging.INFO)
    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO
    logger.setLevel(numeric_level)
    # 阻止向 root logger 传播（避免与 uvicorn/access log 重复）
    logger.propagate = False

    # JSON formatter：常用字段重命名为 ELK/Loki 友好的短名
    fmt = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(module)s %(lineno)d %(message)s",
        rename_fields={
            "asctime": "ts",
            "levelname": "level",
            "name": "logger",
            "lineno": "line",
        },
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    # 共享 filter：每条 record 注入 request_id
    rid_filter = RequestIDFilter()

    # 控制台 handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(fmt)
    console_handler.addFilter(rid_filter)
    logger.addHandler(console_handler)

    # 文件 handler（用绝对路径，避免 cwd 不一致）
    # B18: RotatingFileHandler 防止 app.log 无限增长（单文件 10MB，保留 5 个备份）
    log_dir = Path(__file__).resolve().parent.parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    file_handler = RotatingFileHandler(
        log_dir / "app.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(fmt)
    file_handler.addFilter(rid_filter)
    logger.addHandler(file_handler)

    return logger


# 全局 logger（级别由 settings.log_level 控制）
logger = setup_logger(level=settings.log_level)
