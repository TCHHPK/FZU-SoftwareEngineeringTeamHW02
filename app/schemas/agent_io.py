"""Agent 输入输出契约。

这三个模型是「后端 ↔ Agent ↔ 前端」的接口边界：定下来之后三方就能并行开发。
改动需在群里同步，并同步更新 app/schemas/api_io.py 里的响应模型。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Difficulty = Literal["基础", "进阶", "挑战"]
ContentType = Literal["note", "key_points", "mindmap"]
TaskType = Literal["note", "example", "exam_scope"]
SessionStatus = Literal["pending", "running", "success", "partial", "failed"]


# --------------------------------------------------------------------------
# 证据与知识点
# --------------------------------------------------------------------------
class Evidence(BaseModel):
    """一条出处。chunk_key 必须真实存在于 chunks 表，否则该知识点会被丢弃。"""

    chunk_key: str = Field(description="分块编号，形如 d12-p7-c3")
    source_file: str = Field(default="", description="来源文件名")
    chapter_title: str = Field(default="", description="章节标题")
    page_num: int | None = Field(default=None, description="PDF 页码")
    slide_index: int | None = Field(default=None, description="PPT 幻灯片序号")
    quote: str = Field(default="", description="原文引文，用于核对，建议不超过 120 字")


class KnowledgeItem(BaseModel):
    """一个结构化知识点。evidence 为空的知识点在入库前会被 verifier 丢弃。"""

    name: str
    definition: str = ""
    key_points: list[str] = Field(default_factory=list)
    formula_latex: str | None = None
    importance: int = Field(default=3, ge=1, le=5, description="重要度 1-5")
    evidence: list[Evidence] = Field(default_factory=list)
    verified: bool = False
    user_edited: bool = False


class QualityScore(BaseModel):
    """OP-06 固定权重质量自评（85% / 10% / 5%）。"""

    total: float = Field(ge=0, le=100)
    core: float = Field(ge=0, le=100, description="核心功能完成度，权重 85%")
    structure: float = Field(ge=0, le=100, description="结构化与规范性，权重 10%")
    extension: float = Field(ge=0, le=100, description="拓展关联，权重 5%")
    reasons: list[str] = Field(default_factory=list, description="各维度扣分理由")

    @classmethod
    def from_dimensions(cls, core: float, structure: float, extension: float,
                        reasons: list[str] | None = None) -> "QualityScore":
        """按固定权重合成总分，避免依赖模型自己算对算术。"""
        total = round(core * 0.85 + structure * 0.10 + extension * 0.05, 1)
        return cls(total=total, core=core, structure=structure,
                   extension=extension, reasons=reasons or [])


class OutlineNode(BaseModel):
    """结构化笔记的层级节点。"""

    title: str
    level: int = Field(default=1, ge=1, le=4)
    summary: str = ""
    items: list[KnowledgeItem] = Field(default_factory=list)


class NoteResult(BaseModel):
    """FR-03 + FR-04 的完整产物。"""

    course_name: str = ""
    outline: list[OutlineNode] = Field(default_factory=list)
    key_points: list[str] = Field(default_factory=list, description="重点清单")
    mindmap_text: str = Field(default="", description="文本版思维导图")
    quality: QualityScore | None = None
    dropped_items: int = 0
    # warnings：材料/结果本身的问题（如某页解析失败、部分内容无法核验）→ 任务状态判为 partial
    warnings: list[str] = Field(default_factory=list)
    # notices：实现说明（如「当前为占位实现」）→ 只展示，不影响任务状态
    notices: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# 抽取阶段：LLM 逐块输出的原始结构（不含 verified，由代码回填）
# --------------------------------------------------------------------------
class ExtractInput(BaseModel):
    course_name: str = ""
    chapter_title: str = ""
    page_num: int | None = None
    slide_index: int | None = None
    chunk_key: str
    text: str


class ExtractOutput(BaseModel):
    """prompts/extract.txt 的期望输出。模型的 evidence 由代码回填 chunk_key，模型只需给 quote。"""

    items: list[KnowledgeItem] = Field(default_factory=list)


# --------------------------------------------------------------------------
# 问答阶段
# --------------------------------------------------------------------------
class AskRequest(BaseModel):
    course_name: str = ""
    doc_id: int | None = None
    question: str = Field(min_length=1, max_length=500)


class AnswerResult(BaseModel):
    answer: str = ""
    evidence: list[Evidence] = Field(default_factory=list)
    insufficient: bool = Field(default=False, description="True = 材料未涉及，未编造")


# --------------------------------------------------------------------------
# 例题与考试范围
# --------------------------------------------------------------------------
class ExampleItem(BaseModel):
    knowledge_name: str = ""
    difficulty: Difficulty = "基础"
    question: str = ""
    answer: str = ""
    analysis: str = ""
    source: Literal["检索例题库", "Agent生成"] = "Agent生成"
    evidence: list[Evidence] = Field(default_factory=list)


class ExampleResult(BaseModel):
    examples: list[ExampleItem] = Field(default_factory=list)


class ExamScopeResult(BaseModel):
    """OP-05：按考试范围筛选后的复习笔记。"""

    outline: list[OutlineNode] = Field(default_factory=list)
    key_points: list[str] = Field(default_factory=list)
    out_of_scope_note: str = Field(default="", description="被排除的内容说明，避免学生误以为漏整理")
    evidence: list[Evidence] = Field(default_factory=list)
