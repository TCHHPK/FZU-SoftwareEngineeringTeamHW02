"""对外 HTTP 响应模型。

前端按这里的字段名对接，命名风格统一为 snake_case。
"""

from __future__ import annotations

from datetime import date
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


# --------------------------------------------------------------------------
# 智能自测（U14）
# --------------------------------------------------------------------------
class SelfTestCreate(BaseModel):
    """组卷请求。question_count 限 1~20：太少没意义，太多一次做完不现实。"""

    session_id: int = Field(gt=0)
    question_count: int = Field(default=5, ge=1, le=20)
    scope_text: str = Field(default="", max_length=200)


class AnswerIn(BaseModel):
    item_id: int = Field(gt=0)
    answer: str = Field(default="", max_length=200)


class SelfTestSubmit(BaseModel):
    """交卷请求。answers 允许缺题（未作答按错处理，不报错）。"""

    answers: list[AnswerIn] = Field(default_factory=list)


# --------------------------------------------------------------------------
# v1.3.0（Beta）新增模型
#
# 契约：docs/契约-v1.3.md 3.1–3.5。本文件由沈文驰统一写入（C5 裁决：
# 模型先行，路由后接），其他人只提交字段片段，不直接改这里。
# 五组依次为：自测 target/actual、复习包、冲刺计划、到期队列、出处原文。
# --------------------------------------------------------------------------
class SelfTestOut(BaseModel):
    """自测取卷/交卷响应（A32 修复口径）。

    question_count 语义固定为「用户要的题量」（target），
    实际出了几道看 actual_count，差额用 shortfall 标记；
    不再把 target 静默改写成实际条数。
    """

    test_id: int
    course_name: str = ""
    question_count: int = 0
    target_count: int = 0
    actual_count: int = 0
    shortfall: bool = False
    total_score: float = 100.0
    score: float = 0.0
    correct_count: int = 0
    error_message: str = ""
    created_at: str = ""
    submitted_at: str | None = None
    status: str = "draft"
    wrong_count: int = 0
    items: list[dict] = Field(default_factory=list)


# ---- 复习包（K1）----
class ReviewPackRequest(BaseModel):
    """生成复习包的可选参数；无 body 时按默认值聚合。"""

    include_mindmap: bool = True


class ReviewPackChapter(BaseModel):
    key: str  # notes / points / mindmap / quiz / wrong
    title: str
    item_count: int = 0
    empty: bool = False


class ReviewPackOut(BaseModel):
    pack_id: int
    chapters: list[ReviewPackChapter] = Field(default_factory=list)
    generated_at: str = ""


# ---- 考前冲刺计划（K2）----
class ReviewPlanRequest(BaseModel):
    """冲刺计划请求。

    exam_date 用字符串接收入口参数，由服务层统一校验并返回 400（契约 3.3：
    日期格式错误也是 400，而不是 pydantic 默认的 422）；
    daily_minutes ≤ 0 同样由服务层判定为 400。
    """

    exam_date: str = Field(description="考试日期，ISO 格式 YYYY-MM-DD")
    daily_minutes: int = 60


class PlanItem(BaseModel):
    knowledge_name: str
    minutes: int = 10
    reason: str = ""


class PlanDay(BaseModel):
    date: date
    total_minutes: int = 0
    items: list[PlanItem] = Field(default_factory=list)


class ReviewPlanOut(BaseModel):
    days: list[PlanDay] = Field(default_factory=list)
    exam_date: date
    weights: dict[str, float] = Field(
        default_factory=lambda: {"weakness": 0.5, "importance": 0.3, "urgency": 0.2})


# ---- 今日待复习队列（K4）----
class DueWrongQuestionOut(WrongQuestionOut):
    """现有错题字段 + 四个调度字段（契约 3.4）。"""

    state: str = "new"
    due_at: str | None = None
    review_count: int = 0
    is_due: bool = True


class DueQueueOut(BaseModel):
    items: list[DueWrongQuestionOut] = Field(default_factory=list)
    total: int = 0


# ---- 出处原文（K3）----
class ChunkDetailOut(BaseModel):
    chunk_key: str
    text: str
    page_num: int | None = None
    before: str = ""
    after: str = ""
    source_file: str = ""
