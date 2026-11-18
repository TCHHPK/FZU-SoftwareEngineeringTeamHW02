"""对外 HTTP 响应模型。

前端按这里的字段名对接，命名风格统一为 snake_case。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.agent_io import AnswerResult, Evidence, NoteResult, QualityScore

Status = Literal["pending", "running", "success", "partial", "failed"]


# --------------------------------------------------------------------------
# 统一响应包络
# --------------------------------------------------------------------------
class Envelope(BaseModel):
    """所有接口的统一返回结构：{code, message, data}。code=0 表示成功。"""

    code: int = 0
    message: str = "ok"
    data: Any = None


class PageMeta(BaseModel):
    total: int = 0
    limit: int = 20
    offset: int = 0


# --------------------------------------------------------------------------
# 认证
# --------------------------------------------------------------------------
class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_\u4e00-\u9fff]+$")
    password: str = Field(min_length=6, max_length=64)
    nickname: str = Field(default="", max_length=32)


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    user_id: int
    username: str
    nickname: str = ""
    role: Literal["student", "admin"] = "student"
    created_at: str = ""


class LoginOut(BaseModel):
    token: str
    user: UserOut


# --------------------------------------------------------------------------
# 文档
# --------------------------------------------------------------------------
class DocumentOut(BaseModel):
    doc_id: int
    course_name: str = ""
    source_file: str = ""
    file_type: str = ""
    page_count: int = 0
    text_chars: int = 0
    is_public: bool = False
    parse_status: Status = "pending"
    parse_message: str = ""
    chunk_count: int = 0
    created_at: str = ""


class UploadOut(BaseModel):
    document: DocumentOut
    warnings: list[str] = Field(default_factory=list)
    chapters: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# 任务与产物
# --------------------------------------------------------------------------
class SessionCreateRequest(BaseModel):
    doc_ids: list[int] = Field(min_length=1, description="参与整理的材料")
    course_name: str = ""
    task_type: Literal["note", "example", "exam_scope"] = "note"
    exam_scope: str | None = Field(default=None, description="OP-05 考试范围原文")


class SessionOut(BaseModel):
    session_id: int
    course_name: str = ""
    source_file: str = ""
    doc_ids: list[int] = Field(default_factory=list)
    task_type: str = "note"
    status: Status = "pending"
    progress: int = 0
    stage_message: str = ""
    error_message: str | None = None
    note_count: int = 0
    created_at: str = ""
    finished_at: str | None = None


class EvidenceOut(Evidence):
    pass


class NoteItemOut(BaseModel):
    item_id: int
    name: str
    definition: str = ""
    key_points: list[str] = Field(default_factory=list)
    formula_latex: str | None = None
    importance: int = 3
    evidence: list[Evidence] = Field(default_factory=list)
    verified: bool = False
    user_edited: bool = False


class NoteView(BaseModel):
    """结果页一次性拿到的全部内容（FR-03 + FR-04 + OP-03 + OP-06）。"""

    session_id: int
    course_name: str = ""
    status: Status = "pending"
    outline: list[dict] = Field(default_factory=list)
    items: list[NoteItemOut] = Field(default_factory=list)
    key_points: list[str] = Field(default_factory=list)
    mindmap_text: str = ""
    quality: QualityScore | None = None
    dropped_items: int = 0
    warnings: list[str] = Field(default_factory=list, description="材料/结果本身的问题")
    notices: list[str] = Field(default_factory=list, description="实现说明，不影响任务状态")
    result: NoteResult | None = None


class AskOut(AnswerResult):
    course_name: str = ""


# --------------------------------------------------------------------------
# 检索（管理端与调试用，也在答辩演示「证据是怎么找出来的」时很有用）
# --------------------------------------------------------------------------
class ChunkHit(BaseModel):
    chunk_key: str
    text: str
    source_file: str = ""
    chapter_title: str = ""
    section_title: str = ""
    page_num: int | None = None
    slide_index: int | None = None
    relevance: float = 0.0
    coverage: float = 0.0
    low_confidence: bool = False


class FeaturesOut(BaseModel):
    features: dict[str, bool]
    max_upload_mb: int
    allowed_extensions: list[str]


# --------------------------------------------------------------------------
# 错题本（U13）：列表 / 详情 / 重做
# --------------------------------------------------------------------------
class WrongQuestionOut(BaseModel):
    wrong_id: int
    knowledge_name: str
    source_type: str
    source_id: int
    question_stem: str
    correct_answer: str
    analysis: str
    evidence_chunk_key: str
    evidence_page: int | None
    wrong_count: int
    correct_streak: int
    mastered: bool
    last_wrong_at: str
    created_at: str


class WeakPointOut(BaseModel):
    """按知识点聚合的薄弱度：错题数 + 掌握状态。"""

    knowledge_name: str
    wrong_count: int
    mastered_count: int
    unmastered_count: int
    last_wrong_at: str
    weakness: str


class WrongQuestionListOut(BaseModel):
    items: list[WrongQuestionOut] = Field(default_factory=list)
    weak_points: list[WeakPointOut] = Field(default_factory=list)
    total: int = 0


class RetryRequest(BaseModel):
    answer: str = ""


class RetryOut(BaseModel):
    is_correct: bool
    correct_answer: str
    analysis: str
    evidence_chunk_key: str
    evidence_page: int | None
    correct_streak: int
    mastered: bool
    mastery_threshold: int
