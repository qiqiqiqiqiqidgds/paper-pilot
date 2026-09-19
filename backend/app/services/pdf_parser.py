"""
PDF 解析服务：基于 PyMuPDF
"""
import fitz  # PyMuPDF
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict

from app.utils.logger import logger


@dataclass
class BBox:
    """PDF 文本框坐标"""
    x0: float
    y0: float
    x1: float
    y1: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PageContent:
    """单页内容"""
    page_num: int        # 1-based
    text: str
    width: float
    height: float
    blocks: List[Dict[str, Any]]  # 文本块，含 bbox


@dataclass
class PaperMeta:
    """论文元数据"""
    title: str
    authors: List[str]
    abstract: str
    keywords: List[str]
    year: Optional[int] = None
    venue: Optional[str] = None
    doi: Optional[str] = None


class PDFParser:
    """PDF 解析器"""

    def __init__(self, pdf_path: str | Path):
        self.pdf_path = Path(pdf_path)
        if not self.pdf_path.exists():
            raise FileNotFoundError(f"PDF 不存在: {self.pdf_path}")

        self.doc = fitz.open(str(self.pdf_path))
        self.page_count = len(self.doc)
        logger.info(f"打开 PDF: {self.pdf_path.name} ({self.page_count} 页)")

    def close(self):
        self.doc.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # ============ 元数据提取 ============

    def extract_metadata(self) -> PaperMeta:
        """从首页提取标题、作者、摘要（合并前 2 页，避免跨页丢失）"""
        if self.page_count == 0:
            return PaperMeta(title="", authors=[], abstract="", keywords=[])

        # 合并前 2 页文本，处理跨页场景
        max_pages = min(2, self.page_count)
        combined_text = "\n".join(self.doc[i].get_text() for i in range(max_pages))
        first_page_text = self.doc[0].get_text()

        # 标题：通常是首页第一行最长的文本
        lines = [ln.strip() for ln in first_page_text.split("\n") if ln.strip()]
        title = self._extract_title(lines)

        # 作者：标题之后到 "Abstract" 之间的内容（在合并文本里找）
        authors = self._extract_authors(combined_text, title)

        # 摘要：从 "Abstract" 开始到 "Introduction" 之前
        abstract = self._extract_abstract(combined_text)

        # 关键词
        keywords = self._extract_keywords(combined_text)

        # 年份
        year = self._extract_year(combined_text)

        return PaperMeta(
            title=title,
            authors=authors,
            abstract=abstract,
            keywords=keywords,
            year=year,
        )

    def _extract_title(self, lines: List[str]) -> str:
        """提取标题（首页最长的几行）"""
        # 简单策略：前 5 行里最长的那行
        candidates = lines[:5] if len(lines) >= 5 else lines
        if not candidates:
            return ""
        # 排除明显是噪音的行（如纯数字、邮箱、单字符）
        candidates = [ln for ln in candidates if len(ln) > 10 and not ln.isdigit()]
        if not candidates:
            return lines[0] if lines else ""
        return max(candidates, key=len)

    def _extract_authors(self, text: str, title: str) -> List[str]:
        """提取作者"""
        # 简单策略：找包含 "," 或 "and" 的行
        lines = text.split("\n")
        authors = []
        capture = False
        for line in lines:
            line = line.strip()
            if title and title in line:
                capture = True
                continue
            if capture:
                if "abstract" in line.lower() or len(line) < 3:
                    break
                if "," in line or " and " in line.lower() or "·" in line:
                    # 拆分成多个作者
                    parts = line.replace(" and ", ",").split(",")
                    for p in parts:
                        p = p.strip().rstrip(".").rstrip("*").rstrip("†")
                        if p and 2 < len(p) < 50 and not p.isdigit():
                            authors.append(p)
                    if authors:
                        break
        return authors[:10]  # 最多 10 个

    def _extract_abstract(self, text: str) -> str:
        """提取摘要"""
        import re
        # 找 Abstract 开头
        match = re.search(r"\babstract\b[:.\s]?", text, re.IGNORECASE)
        if not match:
            return ""

        start = match.end()
        # 摘要到 "Introduction" / "1. " / "I. " 之前
        end_match = re.search(
            r"\n\s*(?:1\.\s*introduction|introduction|i\.\s*introduction|index terms)",
            text[start:].lower(),
        )
        end = start + end_match.start() if end_match else start + 2000

        abstract = text[start:end].strip()
        # 清理多余空白
        abstract = re.sub(r"\s+", " ", abstract)
        return abstract[:2000]  # 限制长度

    def _extract_keywords(self, text: str) -> List[str]:
        """提取关键词"""
        import re
        match = re.search(r"keywords?[:.\s]+(.*?)(?:\n\n|introduction|1\.)", text, re.IGNORECASE | re.DOTALL)
        if not match:
            return []
        kw_text = match.group(1).strip()
        # 拆分
        keywords = re.split(r"[,;·\n]+", kw_text)
        return [k.strip() for k in keywords if k.strip() and len(k.strip()) < 50][:10]

    def _extract_year(self, text: str) -> Optional[int]:
        """提取年份"""
        import re
        # 匹配 1900-2099
        matches = re.findall(r"\b(19\d{2}|20\d{2})\b", text[:3000])
        if not matches:
            return None
        # 返回最常见的年份
        from collections import Counter
        return int(Counter(matches).most_common(1)[0][0])

    # ============ 文本提取 ============

    def extract_pages(self) -> List[PageContent]:
        """提取所有页的文本和坐标"""
        pages = []
        for i in range(self.page_count):
            page = self.doc[i]
            text = page.get_text("text")
            rect = page.rect
            blocks = self._extract_blocks(page)

            pages.append(PageContent(
                page_num=i + 1,
                text=text,
                width=rect.width,
                height=rect.height,
                blocks=blocks,
            ))
        return pages

    def _extract_blocks(self, page) -> List[Dict[str, Any]]:
        """提取文本块（含 bbox）"""
        blocks = []
        # 使用 dict 格式获取
        page_dict = page.get_text("dict")
        for block in page_dict.get("blocks", []):
            if block.get("type") != 0:  # 跳过图片
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    bbox = span.get("bbox", [0, 0, 0, 0])
                    text = span.get("text", "").strip()
                    if not text:
                        continue
                    blocks.append({
                        "text": text,
                        "bbox": {
                            "x0": bbox[0], "y0": bbox[1],
                            "x1": bbox[2], "y1": bbox[3],
                        },
                        "font_size": span.get("size", 0),
                        "font_name": span.get("font", ""),
                    })
        return blocks

    def extract_full_text(self) -> str:
        """提取全文（按页拼接）"""
        texts = []
        for i in range(self.page_count):
            page_text = self.doc[i].get_text("text")
            texts.append(f"\n\n=== Page {i+1} ===\n\n{page_text}")
        return "\n".join(texts)

    # ============ 一站式解析 ============

    def extract_toc(self) -> List[List]:
        """提取 PDF 大纲（目录）

        Returns:
            List of [level, title, page_num]，如 [[1, "Introduction", 1], [2, "1.1 Background", 1]]
            没有大纲时返回 []
        """
        # P0-1 事故（2026-09-08）：此前用 get_toc(simple=False)，条目第 4 元素是 dest dict
        # （其 "to" 字段为 fitz.Point 对象，不可 JSON 序列化），随 parse() 结果经
        # storage.save_text_json 落盘时 json.dumps 抛 "TypeError: Object of type Point is
        # not JSON serializable"，带书签的 PDF（arXiv / IEEE 出版版几乎都带）上传必现 500，
        # 且已保存的 raw 文件被联动删除。下游 chapter_splitter 只消费 [level, title, page]
        # 三列，simple=False 毫无必要 —— 必须用 simple=True：条目恒为 [int, str, int]，
        # 天然 JSON 可序列化。
        try:
            toc = self.doc.get_toc(simple=True)
        except Exception as e:
            logger.warning(f"提取 PDF 大纲失败: {e}")
            return []

        # 二次防线：防御性归一化，保证返回值每条目恰好是 [int level, str title, int page]
        # 三元素。即使未来 PyMuPDF 行为变化或个别 PDF 目录损坏（页码无指向 / 标题缺失等），
        # 也绝不让不可序列化或结构异常的条目流进 text.json。异常条目跳过的代价可控：
        # 章节切分少一个边界只影响切分粒度，而落盘 TypeError 是整个上传 500。
        normalized: List[List] = []
        for entry in toc:
            if not isinstance(entry, (list, tuple)) or len(entry) < 3:
                logger.debug(f"跳过异常 TOC 条目（不足三元素）: {entry!r}")
                continue
            try:
                level = int(entry[0])
                # 标题缺失时归一化为空串（下游 _normalize_title 会过滤空标题），
                # 而非 str(None) = "None" 这种脏数据
                title = "" if entry[1] is None else str(entry[1])
                page = int(entry[2])
            except (TypeError, ValueError):
                logger.debug(f"跳过异常 TOC 条目（字段不可转换）: {entry!r}")
                continue
            if level < 1 or page < 1:
                # get_toc 页码恒为 1-based；无有效指向的条目 page 会是 0/-1
                logger.debug(f"跳过异常 TOC 条目（level/page 非法）: {entry!r}")
                continue
            normalized.append([level, title, page])
        return normalized

    def parse(self) -> Dict[str, Any]:
        """完整解析：返回元数据 + 每页内容 + 目录"""
        meta = self.extract_metadata()
        pages = self.extract_pages()
        full_text = self.extract_full_text()
        toc = self.extract_toc()

        return {
            "meta": {
                "title": meta.title,
                "authors": meta.authors,
                "abstract": meta.abstract,
                "keywords": meta.keywords,
                "year": meta.year,
                "venue": meta.venue,
                "doi": meta.doi,
            },
            "page_count": self.page_count,
            "full_text": full_text,
            "toc": toc,
            "pages": [
                {
                    "page_num": p.page_num,
                    "text": p.text,
                    "width": p.width,
                    "height": p.height,
                    "blocks": p.blocks,
                }
                for p in pages
            ],
        }


def parse_pdf(pdf_path: str | Path) -> Dict[str, Any]:
    """便捷函数：解析 PDF"""
    with PDFParser(pdf_path) as parser:
        return parser.parse()
