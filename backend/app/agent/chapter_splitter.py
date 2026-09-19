"""
章节识别器

策略优先级：
1. PDF 大纲（toc）—— 100% 准（如果有）
2. 文本模式匹配 —— 80% 准（标准论文）
3. 兜底 —— 整篇作为一章
"""
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from app.utils.logger import logger


# 章节关键词（按论文常见顺序排列，用于 Reduce 时排序和识别）
SECTION_KEYWORDS = [
    "Abstract",
    "Introduction",
    "Background",
    "Related Work",
    "Related Works",
    "Preliminary",
    "Preliminaries",
    "Method",
    "Methods",
    "Methodology",
    "Approach",
    "Model",
    "Framework",
    "Experiment",
    "Experiments",
    "Experimental Setup",
    "Evaluation",
    "Results",
    "Discussion",
    "Conclusion",
    "Conclusions",
    "References",
    "Acknowledgment",
    "Acknowledgments",
    "Appendix",
]

# 构建正则（关键词按长度倒序，避免 "Related Work" 被当成 "Work"）
_KEYWORDS_SORTED = sorted(SECTION_KEYWORDS, key=len, reverse=True)
_KW_GROUP = "|".join(re.escape(kw) for kw in _KEYWORDS_SORTED)

# 模式 1: "1 Introduction" / "1. Introduction" / "1 INTRODUCTION" / "2.1 Background"
SECTION_PATTERNS = [
    re.compile(
        r'(?:^|\n)\s*\d+(?:\.\d+){0,2}\.?\s+(' + _KW_GROUP + r')\b[^\n]*\n',
        re.IGNORECASE | re.MULTILINE
    ),
    # 模式 2: 纯关键词一行（少见）
    re.compile(
        r'(?:^|\n)\s*(' + _KW_GROUP + r')\s*\n\s*\n',
        re.IGNORECASE | re.MULTILINE
    ),
]

# 附录类章节（B9）：目录切分时过滤，不作为分析章节
# 用"归一化小写后子串匹配"，可命中 References / Bibliography / Appendix /
# Acknowledgments / 参考文献 / 致谢 / 附录 等及带编号的变体
_APPENDIX_KEYWORDS = (
    "references",
    "bibliography",
    "appendix",
    "acknowledgment",   # 同时命中 acknowledgements
    "参考文献",
    "致谢",
    "附录",
)

# P1-2: 章节数上限 —— 目录/模式识别出的章节数超过该值时合并尾部为单章。
# 无上限时书式长文（几百条 level-1 目录）会引发 Map 雪崩：N 次 LLM 调用
# 难以在 llm_timeout_seconds 内完成，Reduce 输入也随之超上下文
MAX_CHAPTERS = 16


@dataclass
class Chapter:
    """识别出的章节"""
    name: str           # 章节名（已归一化）
    text: str           # 章节内容
    page_start: int     # 起始页（1-based）
    page_end: int       # 结束页
    level: int = 1      # 层级


class ChapterSplitter:
    """基于 PDF 大纲 + 文本模式的章节识别器"""

    def __init__(
        self,
        pages: List[Dict[str, Any]],
        toc: Optional[List] = None,
        full_text: str = "",
    ):
        self.pages = pages or []
        self.toc = toc or []
        self.full_text = full_text
        self.total_pages = len(self.pages)

    def split(self) -> List[Chapter]:
        """识别章节，返回 List[Chapter]"""
        # 策略 1: PDF 大纲（最准）
        chapters = self._split_by_toc()
        if len(chapters) >= 3:
            chapters = self._cap_chapters(chapters)  # P1-2: 章节数上限
            logger.info(f"使用 PDF 大纲识别章节: {len(chapters)} 章")
            return chapters

        # 策略 2: 文本模式匹配
        chapters = self._split_by_pattern()
        if len(chapters) >= 3:
            chapters = self._cap_chapters(chapters)  # P1-2: 章节数上限
            logger.info(f"使用文本模式识别章节: {len(chapters)} 章")
            return chapters

        # 兜底：整篇作为一章
        logger.warning("未识别到章节（<3），整篇作为单章处理")
        return [Chapter(
            name="全文",
            text=self.full_text or "\n".join(p.get("text", "") for p in self.pages),
            page_start=1,
            page_end=self.total_pages,
        )]

    def _cap_chapters(self, chapters: List[Chapter]) -> List[Chapter]:
        """P1-2: 章节数超上限时把尾部合并为单章（确定性策略）

        取舍：保头不保尾 —— 前 MAX_CHAPTERS-1 章原样保留（论文核心章节
        集中在前部，被截断丢弃的往往是讨论/附录类内容），其余章节文本合并进
        最后一章"其余章节"。合并优于硬截断：靠后章节仍有机会进入分析而非
        直接丢失；合并章的文本在 Map 阶段仍受单章 20K 字符截断约束，不会
        撑爆 Map prompt。各章文本自带 === Page N === 标记，页码定位不受影响。
        """
        if len(chapters) <= MAX_CHAPTERS:
            return chapters
        head = chapters[: MAX_CHAPTERS - 1]
        tail = chapters[MAX_CHAPTERS - 1:]
        merged = Chapter(
            name="其余章节",
            text="\n".join(ch.text for ch in tail),
            page_start=tail[0].page_start,
            page_end=max(ch.page_end for ch in tail),
        )
        logger.info(f"章节数 {len(chapters)} 超上限 {MAX_CHAPTERS}，尾部 {len(tail)} 章合并为单章")
        return head + [merged]

    def _split_by_toc(self) -> List[Chapter]:
        """基于 PDF 大纲切分（PyMuPDF doc.get_toc()）"""
        if not self.toc:
            return []

        # toc 格式: [[level, title, page], ...]
        # 取 level=1 的章节（保留全部条目用于计算内容边界，附录类在下方跳过）
        level1 = [
            (t[0], t[1], t[2])
            for t in self.toc
            if len(t) >= 3 and t[0] == 1
        ]
        if len(level1) < 2:
            return []

        chapters = []
        # B9: 归一化去重（参照 _split_by_pattern：同章节名只保留第一次出现）
        seen: set = set()
        for i, (level, title, page) in enumerate(level1):
            normalized = self._normalize_title(title)
            if not normalized:
                continue

            # B9: 过滤附录类章节（References / Appendix / 致谢 等，大小写不敏感）
            lower = normalized.lower()
            if any(kw in lower for kw in _APPENDIX_KEYWORDS):
                continue

            if normalized in seen:
                continue
            seen.add(normalized)

            # 内容范围：从本章开始到下一章开始（不包含下一章）
            start_page = max(1, page)
            if i + 1 < len(level1):
                end_page = max(start_page, level1[i + 1][2] - 1)
            else:
                end_page = self.total_pages

            text = self._extract_text_by_page_range(start_page, end_page)
            if not text.strip():
                continue

            chapters.append(Chapter(
                name=normalized,
                text=text,
                page_start=start_page,
                page_end=end_page,
                level=1,
            ))

        return chapters

    def _split_by_pattern(self) -> List[Chapter]:
        """基于文本模式匹配切分"""
        if not self.pages:
            return []

        # 找所有匹配的章节标题
        matches = []
        for page in self.pages:
            page_num = page["page_num"]
            text = page["text"]
            # P2-1: 同页允许命中多个 level-1 标题。旧实现用 found_in_page 标志
            # 命中即 break 两层，"5 Results" 与 "6 Conclusion" 同页时必丢后面的
            # 章（其内容被并入前一章，边界错切）。现在逐模式逐命中全部收集，
            # 既有去重 / 相似度归一化（_normalize_title）逻辑语义不变
            for pattern in SECTION_PATTERNS:
                for m in pattern.finditer(text):
                    keyword = m.group(1)
                    if not keyword:
                        continue
                    normalized = self._normalize_title(keyword)
                    if not normalized:
                        continue
                    matches.append({
                        "keyword": normalized,
                        "page": page_num,
                        "offset": m.start(),
                    })

        if not matches:
            return []

        # P2-1: 先按页号 + offset 排序再去重 —— "第一次出现"严格按文档位置计
        # （同页多标题时位置序才是阅读序；跨页重复场景结果与旧行为一致）
        matches.sort(key=lambda x: (x["page"], x["offset"]))

        # 去重（同章节名跨页时只保留第一次出现）
        seen = set()
        unique_matches = []
        for m in matches:
            if m["keyword"] in seen:
                continue
            seen.add(m["keyword"])
            unique_matches.append(m)

        if len(unique_matches) < 2:
            return []

        # 构造章节
        chapters = []
        for i, m in enumerate(unique_matches):
            start_page = m["page"]
            if i + 1 < len(unique_matches):
                end_page = max(start_page, unique_matches[i + 1]["page"] - 1)
            else:
                end_page = self.total_pages

            text = self._extract_text_by_page_range(start_page, end_page)
            if not text.strip():
                continue

            chapters.append(Chapter(
                name=m["keyword"],
                text=text,
                page_start=start_page,
                page_end=end_page,
            ))

        return chapters

    def _extract_text_by_page_range(self, start: int, end: int) -> str:
        """提取指定页范围的文本（每页带页码标记，供 LLM 定位引文页码）"""
        texts = []
        for page in self.pages:
            if start <= page["page_num"] <= end:
                texts.append(f"\n\n=== Page {page['page_num']} ===\n\n{page.get('text', '')}")
        return "\n".join(texts)

    def _normalize_title(self, title: str) -> str:
        """归一化章节标题"""
        if not title:
            return ""
        cleaned = title.strip()
        # 去掉前导数字编号 "1 Introduction" -> "Introduction"
        cleaned = re.sub(r'^\d+(?:\.\d+)*\.?\s+', '', cleaned).strip()
        # 完全匹配已知关键词
        for kw in SECTION_KEYWORDS:
            if cleaned.lower() == kw.lower():
                return kw
        # 包含匹配：选最长的（即最具体的，如 "Experimental Setup" 优于 "Experimental"）
        lower = cleaned.lower()
        candidates = [kw for kw in SECTION_KEYWORDS if kw.lower() in lower]
        if candidates:
            return max(candidates, key=len)
        # 未知章节，截断保留
        return cleaned[:40]


def split_chapters(
    pages: List[Dict[str, Any]],
    toc: Optional[List] = None,
    full_text: str = "",
) -> List[Chapter]:
    """便捷函数：识别章节"""
    splitter = ChapterSplitter(pages=pages, toc=toc, full_text=full_text)
    return splitter.split()
