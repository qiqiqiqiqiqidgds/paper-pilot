"""
Pydantic 数据模型

P2-23: paper_language 用 Literal 限定白名单，避免任意字符串进入 LLM prompt
"""
from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field


# P2-23: 论文输出语言白名单（仅允许有限语言，避免污染 LLM prompt）
PaperLanguage = Literal["中文", "English", "日本語"]


# ===== 通用响应 =====
class ApiResponse(BaseModel):
    """统一响应结构"""
    code: int = 0
    message: str = "ok"
    data: Optional[Any] = None


# ===== 论文相关 =====
class Quote(BaseModel):
    """原文引用"""
    section: str
    text: str
    page: int = 0  # LLM 漏输出页码时给默认 0（前端跳转会夹取到合法范围）
    bbox: Optional[Dict[str, float]] = None


class PaperMeta(BaseModel):
    """论文元数据"""
    title: str = ""
    authors: List[str] = Field(default_factory=list)
    abstract: str = ""
    keywords: List[str] = Field(default_factory=list)
    year: Optional[int] = None
    venue: Optional[str] = None
    doi: Optional[str] = None


class PaperInfo(BaseModel):
    """论文信息"""
    paper_id: str
    filename: str
    size: int
    pages: int
    file_type: str = "pdf"  # pdf / docx
    title: str = ""
    authors: List[str] = Field(default_factory=list)
    abstract: str = ""
    uploaded_at: str
    has_breakdown: bool = False
    has_innovation: bool = False
    has_flaws: bool = False
    has_compare: bool = False


class UploadResponse(BaseModel):
    """上传响应"""
    paper_id: str
    filename: str
    size: int
    pages: int
    file_type: str = "pdf"
    title: str
    authors: List[str]
    abstract: str
    uploaded_at: str


# ===== 分析相关 =====
class AnalyzeRequest(BaseModel):
    """分析请求"""
    paper_id: str = Field(
        ...,
        pattern=r"^[A-Za-z0-9_\-]{1,64}$",
        description="论文 ID（字母数字 + 短横线 + 下划线，1-64 字符）",
    )
    type: Literal["breakdown", "innovation", "flaws"] = Field(
        ..., description="分析类型: breakdown / innovation / flaws"
    )
    paper_language: PaperLanguage = Field(default="中文", description="输出语言（P2-23 限定）")


class BreakdownResult(BaseModel):
    """拆解结果（summary/background/goal/method/experiment/conclusion）

    P1-P0: 所有字段带默认值 —— LLM 输出小瑕疵（漏字段）时也能校验通过，
    校验后 model_dump() 的字段名必须与旧 raw dict 完全一致（前端依赖）。
    """
    summary: str = ""
    background: str = ""
    goal: str = ""
    method: str = ""
    experiment: str = ""
    conclusion: str = ""
    key_points: List[str] = Field(default_factory=list)
    quotes: List[Quote] = Field(default_factory=list)


class InnovationItem(BaseModel):
    """单个创新点"""
    title: str = ""
    description: str = ""
    evidence: str = ""
    page_ref: int = 0


class InnovationResult(BaseModel):
    """创新点分析结果"""
    core_innovations: List[InnovationItem] = Field(default_factory=list)
    innovation_level: str = ""
    level_reasoning: str = ""
    applicable_scenarios: List[str] = Field(default_factory=list)
    quotes: List[Quote] = Field(default_factory=list)


class FlawItem(BaseModel):
    """单个局限性"""
    description: str = ""
    evidence: str = ""
    page_ref: int = 0
    severity: str = ""


class ImprovementItem(BaseModel):
    """改进建议"""
    flaw_ref: int = 0
    suggestion: str = ""
    feasibility: str = ""


class FlawsResult(BaseModel):
    """局限性分析结果"""
    method_level: List[FlawItem] = Field(default_factory=list)
    experiment_level: List[FlawItem] = Field(default_factory=list)
    writing_level: List[FlawItem] = Field(default_factory=list)
    improvements: List[ImprovementItem] = Field(default_factory=list)
    overall_assessment: str = ""
    quotes: List[Quote] = Field(default_factory=list)


# ===== 对比分析（/api/compare 与 /api/compare-papers 共用） =====
# 输出结构严格对齐 app/agent/prompts/compare.py 的 JSON 示例：
# 之前两个端点直接透传 LLM 原始 dict（无 response_model），compare_table 畸形
# 会直接破坏前端表格渲染；加模型后走 _validate_with_model 容错归一化。
class CompareMainPaper(BaseModel):
    """主论文卡片"""
    title: str = ""
    year: Optional[int] = None
    method_summary: str = ""


class CompareRelatedPaper(BaseModel):
    """相关工作卡片（多篇库内对比时带 paper_id，联网搜时可能没有）"""
    title: str = ""
    year: Optional[int] = None
    url: str = ""
    method: str = ""
    dataset: str = ""
    result: str = ""
    pros: str = ""
    cons: str = ""
    relation_to_main: str = ""
    paper_id: Optional[str] = None


class CompareResult(BaseModel):
    """对比分析结果"""
    main_paper: Optional[CompareMainPaper] = None
    related_papers: List[CompareRelatedPaper] = Field(default_factory=list)
    compare_table: List[List[str]] = Field(default_factory=list)
    summary: str = ""
    main_advantages: List[str] = Field(default_factory=list)
    main_disadvantages: List[str] = Field(default_factory=list)


class AnalyzeResponse(BaseModel):
    """分析响应"""
    type: str
    result: Dict[str, Any]
    elapsed_ms: int
