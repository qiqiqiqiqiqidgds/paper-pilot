"""
PPT 生成服务（基于 python-pptx）

P1-11: 单 bullet 长度限制 + 控制字符过滤
P1-12: authors 长度限制（防解析异常撑爆标题页）
"""
import re
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE

from app.utils.logger import logger


# 长度限制（防 LLM 输出异常撑爆 PPT）
MAX_BULLET_LEN = 200          # 单条 bullet 最大字符
MAX_TITLE_LEN = 120            # 标题最大字符
MAX_SUBTITLE_LEN = 150         # 副标题最大字符
MAX_AUTHORS_DISPLAY = 80       # 作者列表总长
MIN_SLIDES = 8                 # README 宣称 8-15 页：页数下限（_ensure_min_slides）
MAX_SLIDES = 15                # 页数上限（含致谢页，超出裁剪末尾内容页）
# P1-1: 内容页预算上限 = MAX_SLIDES - 标题页 - 致谢页。
# 组装阶段就在此截断（_add_content_slide 内守卫），运行时裁剪（_trim_over_max_slides）
# 仅作兜底 —— 预算内生成时根本不会触发裁剪，从源头避免孤儿 slide part
MAX_CONTENT_SLIDES = MAX_SLIDES - 2
# 控制字符（保留 \t \n；过滤其他）
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")


def _sanitize_text(text: str, max_len: int = MAX_BULLET_LEN) -> str:
    """
    清洗 LLM 输出：过滤控制字符 + 截断长度
    """
    if not text:
        return ""
    cleaned = _CONTROL_CHARS_RE.sub("", text)
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len - 1] + "…"
    return cleaned


class PPTGenerator:
    """PPT 生成器"""

    def __init__(self, template: str = "default"):
        self.template = template
        self.prs = Presentation()
        # 16:9 宽屏
        self.prs.slide_width = Inches(13.333)
        self.prs.slide_height = Inches(7.5)
        # P1-1: 内容页计数（预算控制），generate_from_analysis 开始时重置
        self._content_slides = 0
        logger.info(f"PPT 生成器初始化: template={template}")

    def _add_title_slide(self, title: str, subtitle: str = ""):
        """标题页"""
        slide = self.prs.slides.add_slide(self.prs.slide_layouts[6])  # 空白
        # 背景色
        background = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, 0, 0, self.prs.slide_width, self.prs.slide_height
        )
        background.fill.solid()
        background.fill.fore_color.rgb = RGBColor(0x1E, 0x40, 0x7A)  # 深蓝
        background.line.fill.background()

        # 标题（P1-12: 清洗 + 限制长度）
        title_box = slide.shapes.add_textbox(
            Inches(1), Inches(2.5), Inches(11.333), Inches(1.5)
        )
        tf = title_box.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        run = p.add_run()
        run.text = _sanitize_text(title, max_len=MAX_TITLE_LEN)
        run.font.size = Pt(44)
        run.font.bold = True
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

        # 副标题
        if subtitle:
            sub_box = slide.shapes.add_textbox(
                Inches(1), Inches(4.2), Inches(11.333), Inches(0.8)
            )
            tf = sub_box.text_frame
            p = tf.paragraphs[0]
            p.alignment = PP_ALIGN.CENTER
            run = p.add_run()
            run.text = _sanitize_text(subtitle, max_len=MAX_SUBTITLE_LEN)
            run.font.size = Pt(20)
            run.font.color.rgb = RGBColor(0xCC, 0xDD, 0xFF)

    def _add_content_slide(self, title: str, bullets: List[str], notes: str = ""):
        """内容页（标题 + 要点）"""
        # P1-1: 内容页预算控制 —— 超过 MAX_CONTENT_SLIDES 时直接跳过（保留靠前的章节，
        # 简单截断）。此守卫生效时总页数恒 <= MAX_SLIDES，_trim_over_max_slides 不会触发
        if self._content_slides >= MAX_CONTENT_SLIDES:
            logger.warning(
                f"内容页已达上限 {MAX_CONTENT_SLIDES}，跳过内容页: {title[:30]}"
            )
            return
        self._content_slides += 1
        slide = self.prs.slides.add_slide(self.prs.slide_layouts[6])

        # 顶部色条
        bar = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, 0, 0, self.prs.slide_width, Inches(0.8)
        )
        bar.fill.solid()
        bar.fill.fore_color.rgb = RGBColor(0x1E, 0x40, 0x7A)
        bar.line.fill.background()

        # 标题（P1-11: 限制长度）
        title_box = slide.shapes.add_textbox(
            Inches(0.5), Inches(0.1), Inches(12.333), Inches(0.6)
        )
        tf = title_box.text_frame
        p = tf.paragraphs[0]
        run = p.add_run()
        run.text = _sanitize_text(title, max_len=MAX_TITLE_LEN)
        run.font.size = Pt(28)
        run.font.bold = True
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

        # 内容
        content_box = slide.shapes.add_textbox(
            Inches(0.8), Inches(1.2), Inches(11.733), Inches(5.8)
        )
        tf = content_box.text_frame
        tf.word_wrap = True

        for i, bullet in enumerate(bullets):
            if i == 0:
                p = tf.paragraphs[0]
            else:
                p = tf.add_paragraph()
            p.alignment = PP_ALIGN.LEFT
            # 圆点
            run = p.add_run()
            run.text = "▸ "
            run.font.size = Pt(20)
            run.font.color.rgb = RGBColor(0x1E, 0x40, 0x7A)
            run.font.bold = True
            # 文本（P1-11: 限制单 bullet 长度 + 过滤控制字符）
            run = p.add_run()
            run.text = _sanitize_text(bullet, max_len=MAX_BULLET_LEN)
            run.font.size = Pt(20)
            run.font.color.rgb = RGBColor(0x22, 0x22, 0x22)
            p.space_after = Pt(12)

        # 备注（P1-11: 也限制长度）
        if notes:
            slide.notes_slide.notes_text_frame.text = _sanitize_text(notes, max_len=500)

    def _add_thanks_slide(self):
        """致谢页"""
        slide = self.prs.slides.add_slide(self.prs.slide_layouts[6])
        background = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, 0, 0, self.prs.slide_width, self.prs.slide_height
        )
        background.fill.solid()
        background.fill.fore_color.rgb = RGBColor(0x1E, 0x40, 0x7A)
        background.line.fill.background()

        box = slide.shapes.add_textbox(
            Inches(1), Inches(3), Inches(11.333), Inches(1.5)
        )
        tf = box.text_frame
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        run = p.add_run()
        run.text = "Thanks for Watching"
        run.font.size = Pt(48)
        run.font.bold = True
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

        box2 = slide.shapes.add_textbox(
            Inches(1), Inches(4.5), Inches(11.333), Inches(0.6)
        )
        tf = box2.text_frame
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        run = p.add_run()
        run.text = "Generated by PaperPilot · AI 论文伴读 Agent"
        run.font.size = Pt(16)
        run.font.color.rgb = RGBColor(0xCC, 0xDD, 0xFF)

    def generate_from_analysis(
        self,
        paper_meta: Dict[str, Any],
        breakdown: Optional[Dict[str, Any]] = None,
        innovation: Optional[Dict[str, Any]] = None,
        flaws: Optional[Dict[str, Any]] = None,
        compare: Optional[Dict[str, Any]] = None,
        include_flaws: bool = False,
        include_compare: bool = False,
    ) -> bytes:
        """
        从分析结果生成 PPT
        """
        # P1-1: 重置内容页预算计数（同一生成器实例可复用）
        self._content_slides = 0
        # 1. 标题页（authors 用 `or` 兜底显式 null：get 默认值只防键缺失，
        # 损坏/旧数据的 meta.authors=null 时 authors[:3] 会 TypeError）
        title = paper_meta.get("title") or "Untitled Paper"
        authors = paper_meta.get("authors") or []
        year = paper_meta.get("year") or ""

        # P1-12: 副标题（作者列表）总长限制，防止解析错误时一行被当作者撑爆
        authors_str = ", ".join(authors[:3])
        if len(authors_str) > MAX_AUTHORS_DISPLAY:
            authors_str = authors_str[:MAX_AUTHORS_DISPLAY - 1] + "…"
        subtitle = authors_str + (f" 等 · {year}" if year else "")
        # 副标题也整体限制
        subtitle = _sanitize_text(subtitle, max_len=MAX_SUBTITLE_LEN)

        self._add_title_slide(title, subtitle)

        # 2. 五段拆解（如有）
        if breakdown:
            if breakdown.get("summary"):
                self._add_content_slide("📌 摘要", [breakdown["summary"]])
            if breakdown.get("background"):
                self._add_content_slide("🔍 研究背景", self._split_text(breakdown["background"]))
            if breakdown.get("goal"):
                self._add_content_slide("🎯 研究目标", [breakdown["goal"]])
            if breakdown.get("method"):
                self._add_content_slide("🛠 方法", self._split_text(breakdown["method"]))
            if breakdown.get("experiment"):
                self._add_content_slide("🧪 实验结果", self._split_text(breakdown["experiment"]))
            if breakdown.get("conclusion"):
                self._add_content_slide("✅ 结论", [breakdown["conclusion"]])

        # 3. 创新点（如有；prompt 上限 5 条，切片双保险；isinstance 过滤损坏数据中的非 dict 元素）
        if innovation and innovation.get("core_innovations"):
            for i, c in enumerate(
                [c for c in innovation["core_innovations"][:5] if isinstance(c, dict)], 1
            ):
                title = f"💡 创新点 #{i}: {c.get('title') or ''}"
                bullets = [c.get("description") or ""]
                self._add_content_slide(title, bullets)

        # 4. 对比（如有）
        if include_compare and compare and compare.get("related_papers"):
            # title 用 get 兜底：LLM 校验兜底路径返回的 dict 不保证补全所有字段，
            # 硬索引 p['title'] 在缺键时会让整个 PPT 生成 500
            self._add_content_slide(
                "📊 相关工作对比",
                [
                    f"• {(p.get('title') or '无标题')} ({p.get('year') or '?'})"
                    for p in compare["related_papers"][:5]
                    if isinstance(p, dict)
                ]
            )
            if compare.get("summary"):
                self._add_content_slide("📝 对比总结", [compare["summary"]])

        # 5. 漏洞（如有）
        if include_flaws and flaws:
            if flaws.get("overall_assessment"):
                self._add_content_slide("⚠️ 局限性", [flaws["overall_assessment"]])

        # 5.5 页数上限保障（README 8-15 页）：全量内容可能 >15（含致谢），裁剪末尾内容页
        self._trim_over_max_slides()

        # 6. 页数下限保障（README 宣称 8-15 页）：内容驱动页数不足时用已有分析结果补页
        self._ensure_min_slides(
            breakdown, innovation, flaws, compare,
            include_flaws=include_flaws, include_compare=include_compare,
            paper_meta=paper_meta,
        )

        # 7. 致谢
        self._add_thanks_slide()

        # 保存
        import io
        buf = io.BytesIO()
        self.prs.save(buf)
        buf.seek(0)
        logger.info(f"PPT 生成完成: {len(self.prs.slides)} 页")
        return buf.getvalue()

    def _trim_over_max_slides(self) -> None:
        """超过 MAX_SLIDES 时从末尾裁剪内容页（保留标题页与靠前内容，为致谢页留位）

        P1-1: 裁剪必须同时用 drop_rel 断开 presentation part → slide part 的关系。
        只摘 _sldIdLst 引用会留下仍被 rels 图引用的孤儿 slide part：
        1) save 时孤儿 part 照样被序列化，文件体积虚高；
        2) 后续 add_slide 按剩余页数推算 partname，复用被裁页的 partname
           → zip 出现同名条目（Duplicate name），PowerPoint 可能提示"需要修复"。
        drop_rel 后孤儿 part 从 rels 图不可达，save 时自动跳过。
        """
        while len(self.prs.slides) >= MAX_SLIDES:
            sld_id_lst = self.prs.slides._sldIdLst
            if len(sld_id_lst) <= 1:
                break
            sld_id = sld_id_lst[-1]
            # 先断关系再摘引用：孤儿 part 不再可达，保存时不会被写入 zip
            self.prs.part.drop_rel(sld_id.rId)
            sld_id_lst.remove(sld_id)
            if len(self.prs.slides) < MAX_SLIDES:
                break

    def _ensure_min_slides(
        self,
        breakdown: Optional[Dict[str, Any]],
        innovation: Optional[Dict[str, Any]],
        flaws: Optional[Dict[str, Any]],
        compare: Optional[Dict[str, Any]],
        include_flaws: bool,
        include_compare: bool,
        paper_meta: Dict[str, Any],
    ):
        """内容驱动的页数可能 <8（如只跑创新点时仅 7 页），用已有分析结果补足下限"""
        MIN_SLIDES = 8
        if len(self.prs.slides) >= MIN_SLIDES:
            return

        def still_short() -> bool:
            return len(self.prs.slides) < MIN_SLIDES

        # 1. 拆解：全文核心要点
        if still_short() and breakdown and breakdown.get("key_points"):
            self._add_content_slide("📌 全文核心要点", list(breakdown["key_points"])[:6])

        # 2. 创新：等级评估
        if still_short() and innovation:
            bullets = []
            if innovation.get("innovation_level"):
                bullets.append(f"创新等级：{innovation['innovation_level']}")
            if innovation.get("level_reasoning"):
                bullets.append(innovation["level_reasoning"])
            if bullets:
                self._add_content_slide("💡 创新等级评估", bullets)

        # 3. 创新：应用场景
        if still_short() and innovation and innovation.get("applicable_scenarios"):
            self._add_content_slide(
                "🚀 应用场景", list(innovation["applicable_scenarios"])[:6]
            )

        # 4. 拆解：原文引用（带页码）
        if still_short() and breakdown and breakdown.get("quotes"):
            quotes = []
            for q in breakdown["quotes"][:6]:
                if not isinstance(q, dict):
                    continue
                page = q.get("page")
                prefix = f"[P{page}] " if page else ""
                quotes.append(prefix + (q.get("text", "") or ""))
            if quotes:
                self._add_content_slide("📖 原文引用", quotes)

        # 5. 漏洞三层（仅当用户勾选了 include_flaws）
        if still_short() and include_flaws and flaws:
            for level, label in (
                ("method_level", "方法层面局限"),
                ("experiment_level", "实验层面局限"),
                ("writing_level", "写作层面局限"),
            ):
                items = flaws.get(level) or []
                if items:
                    self._add_content_slide(
                        f"⚠️ {label}",
                        [i.get("description", "") for i in items[:6] if isinstance(i, dict)],
                    )

        # 6. 对比优劣势（仅当用户勾选了 include_compare）
        if still_short() and include_compare and compare:
            bullets = []
            for a in (compare.get("main_advantages") or [])[:3]:
                bullets.append(f"🟢 {a}")
            for d in (compare.get("main_disadvantages") or [])[:3]:
                bullets.append(f"🔴 {d}")
            if bullets:
                self._add_content_slide("📊 优劣势总结", bullets)

        # 7. 兜底：论文信息 + 静态说明页（保证任何情况下都 >= 8 页）
        if still_short():
            bullets = []
            title = paper_meta.get("title", "")
            if title:
                bullets.append(f"论文标题：{title}")
            authors = ", ".join((paper_meta.get("authors") or [])[:3])
            if authors:
                bullets.append(f"作者：{authors}")
            year = paper_meta.get("year")
            if year:
                bullets.append(f"年份：{year}")
            abstract = paper_meta.get("abstract", "")
            if abstract:
                bullets.append(f"摘要：{abstract[:MAX_BULLET_LEN]}")
            if bullets:
                self._add_content_slide("📄 论文信息", bullets)

        static_pages = [
            (
                "📋 关于本报告",
                ["本报告由 PaperPilot AI 论文伴读智能体自动生成",
                 "基于论文原文的逐章分析汇总，支持点击引用跳转原文"],
            ),
            (
                "🚀 快速导航",
                ["摘要页：快速了解论文做什么",
                 "创新点：本文的核心贡献",
                 "局限性：客观评估论文不足"],
            ),
            (
                "✨ 功能说明",
                ["五段拆解：摘要 / 背景 / 目标 / 方法 / 实验 / 结论",
                 "创新识别：创新点 + 创新等级评估",
                 "联网对比：搜索相关工作生成对比表",
                 "漏洞分析：方法 / 实验 / 写作三层局限"],
            ),
        ]
        # 循环补足到下限（B13: 用集合记录已添加的静态页标题，第二轮只补未用过的，
        # 避免重复添加相同静态页；全部用过仍不足 8 页则不再补）
        added_static_titles = set()
        for _ in range(2):
            for page_title, page_bullets in static_pages:
                if not still_short():
                    break
                if page_title in added_static_titles:
                    continue
                added_static_titles.add(page_title)
                self._add_content_slide(page_title, page_bullets)
            if not still_short():
                break

    def _split_text(self, text: str, max_len: int = 80) -> List[str]:
        """把长文本拆成要点（按中英文句号、换行）"""
        if not text:
            return []
        # 按中英文句号、问号、感叹号、换行拆
        parts = re.split(r'[。.!?！？\n]+', text)
        bullets = [p.strip() for p in parts if p.strip()]
        if not bullets:
            return [text]
        return bullets[:6]  # 最多 6 个要点


def save_ppt(ppt_bytes: bytes, paper_id: str, filename: str) -> Path:
    """保存 PPT 到磁盘"""
    from app.config import settings
    save_dir = Path(settings.data_dir) / "ppts"
    save_dir.mkdir(parents=True, exist_ok=True)

    # ===== 路径穿越防护 =====
    # paper_id 必须只含安全字符（UUID / 字母数字 + 短横线）
    # 防止 "../../etc/passwd\x00" 类输入逃逸 save_dir
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", paper_id):
        raise ValueError(f"非法的 paper_id（仅允许字母数字、短横线、下划线）: {paper_id[:50]}")
    if len(paper_id) > 64:
        raise ValueError(f"paper_id 过长（>{64} 字符）")

    # 文件名清洗
    safe_filename = re.sub(r'[^\w\-_]', '_', filename)[:50]

    save_path = save_dir / f"{paper_id}_{safe_filename}.pptx"

    # ===== 二次防线：resolve 后必须仍在 save_dir 内 =====
    # 即使上游校验失效，最后一道安全网保证不会写到 save_dir 之外
    save_dir_resolved = save_dir.resolve()
    save_path_resolved = save_path.resolve()
    if not str(save_path_resolved).startswith(str(save_dir_resolved)):
        raise ValueError(f"路径穿越检测：{save_path_resolved} 超出 {save_dir_resolved}")

    # 原子写：写临时文件再 rename，防止半截文件
    # B12: 临时文件名加随机后缀，避免并发生成同名 PPT 时互相覆盖；失败时清理
    tmp_path = save_path.with_suffix(
        save_path.suffix + f".{uuid.uuid4().hex[:8]}.tmp"
    )
    try:
        tmp_path.write_bytes(ppt_bytes)
        tmp_path.replace(save_path)
    except BaseException:
        # 清理失败的临时文件。清理自身的异常（如 Windows 上文件被占用）只记 warning，
        # 绝不能再抛 —— 否则会替换掉真正的失败原因，排障信息丢失
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            logger.warning(f"清理临时 PPT 文件失败: {tmp_path.name}")
        raise
    return save_path
