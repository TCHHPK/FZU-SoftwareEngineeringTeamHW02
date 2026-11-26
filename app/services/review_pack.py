"""复习包（K1）业务逻辑：五章聚合、快照落库与 Word 导出。

契约：docs/契约-v1.3.md 3.1 / 3.2。几条写死的口径：
    1. 五章固定为 notes / points / mindmap / quiz / wrong；
    2. 某章无数据时 empty=True，导出写「本次未生成此项」，不报错（C4 裁决）；
    3. 导出只渲染「生成时冻结的快照」，不临时生成导图、不补内容；
    4. 单章渲染失败只降级该章，整体仍可导出，并在文档里标注该章生成失败；
    5. 同一 session 正在生成中（generating）时再次请求返回 409。

本文件主责：沈文驰（文件归属表见契约 2.2）。

为什么 pack 要落库而不是内存里拼：
    POST 生成返回 pack_id，GET 导出要按 pack_id 取回同一份内容。
    进程重启、多请求之间都要对得上，所以用 review_packs 表存快照。
    表由本模块首次使用时幂等创建（ddl 在 db/migrations 之外，避免动
    徐张睿的迁移目录；且契约里没有为 review_packs 定义迁移）。
"""

from __future__ import annotations

import io
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

from app.db.conn import transaction

# 五章顺序与标题（导出时的章标题；前端按 key 对接）
CHAPTERS: tuple[tuple[str, str], ...] = (
    ("notes", "第一章　结构化笔记"),
    ("points", "第二章　重点清单"),
    ("mindmap", "第三章　知识结构导图"),
    ("quiz", "第四章　自测题"),
    ("wrong", "第五章　错题回顾"),
)

# 「生成中」状态的判定窗口：进程若在生成途中崩溃，这一行会一直停在
# generating，必须有自愈窗口，否则该 session 永远 409。
_GENERATING_STALE_SECONDS = 120

GREY = RGBColor(0x66, 0x66, 0x66)
LIGHT_GREY = RGBColor(0x90, 0x93, 0x99)
FAIL_RED = RGBColor(0xC7, 0x25, 0x4E)

# XML 1.0 不允许的控制字符（保留 \t \n \r）；PPT 抽出的文本常带 \x0b 等
_CTRL_TO_DROP = {c: None for c in range(0x20) if c not in (0x09, 0x0A, 0x0D)}


class ReviewError(Exception):
    """业务错误：带 HTTP 状态码，由路由层转成 HTTPException。"""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


# --------------------------------------------------------------------------
# 快照表（幂等建表）
# --------------------------------------------------------------------------
def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS review_packs (
            pack_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            session_id    INTEGER NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
            status        TEXT    NOT NULL DEFAULT 'generating',
            payload_json  TEXT    NOT NULL DEFAULT '{}',
            error_message TEXT    NOT NULL DEFAULT '',
            created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
            generated_at  TEXT    NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_review_pack_session
            ON review_packs (session_id, pack_id);
        """
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _age_seconds(created_at: Any) -> float:
    """SQLite CURRENT_TIMESTAMP（UTC，无时区后缀）距今秒数；解析失败按很旧处理。"""
    try:
        created = datetime.strptime(str(created_at), "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return float("inf")
    return (datetime.now(timezone.utc).replace(tzinfo=None) - created).total_seconds()


def _loads(raw: Any, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


def _evidence_list(raw: Any) -> list[dict]:
    parsed = _loads(raw, [])
    if not isinstance(parsed, list):
        return []
    return [e for e in parsed if isinstance(e, dict)]


# --------------------------------------------------------------------------
# 生成：五章聚合
# --------------------------------------------------------------------------
def build(conn: sqlite3.Connection, *, user_id: int, session_id: int,
          include_mindmap: bool = True) -> dict:
    """生成复习包快照，返回 {pack_id, chapters, generated_at}。

    聚合本身只读库（毫秒级），所以同步完成；「generating」状态用于挡住
    同一 session 的并发重复点击（契约 3.1 的 409）。
    """
    _ensure_table(conn)
    session = conn.execute(
        "SELECT session_id, user_id, course_name FROM sessions WHERE session_id = ?",
        (int(session_id),),
    ).fetchone()
    # 越权一律 404，不区分「不存在」与「不属于你」
    if session is None or int(session["user_id"]) != int(user_id):
        raise ReviewError("任务不存在或无权访问", 404)

    with transaction(conn):
        latest = conn.execute(
            "SELECT pack_id, status, created_at FROM review_packs"
            " WHERE session_id = ? ORDER BY pack_id DESC LIMIT 1",
            (int(session_id),),
        ).fetchone()
        if (latest is not None and latest["status"] == "generating"
                and _age_seconds(latest["created_at"]) < _GENERATING_STALE_SECONDS):
            raise ReviewError("该任务的复习包正在生成中，请稍后重试", 409)
        cursor = conn.execute(
            "INSERT INTO review_packs (user_id, session_id, status)"
            " VALUES (?, ?, 'generating')",
            (int(user_id), int(session_id)),
        )
        pack_id = int(cursor.lastrowid)

    try:
        payload = _aggregate(conn, user_id=int(user_id), session_id=int(session_id),
                             include_mindmap=include_mindmap)
    except Exception as exc:  # noqa: BLE001 - 记录失败状态后原样抛出
        with transaction(conn):
            conn.execute(
                "UPDATE review_packs SET status = 'failed', error_message = ?"
                " WHERE pack_id = ?",
                (f"{type(exc).__name__}: {exc}"[:300], pack_id),
            )
        raise

    generated_at = _now_iso()
    payload["generated_at"] = generated_at
    payload["course_name"] = session["course_name"] or ""
    payload["session_id"] = int(session_id)

    with transaction(conn):
        conn.execute(
            "UPDATE review_packs SET status = 'ready', payload_json = ?, generated_at = ?"
            " WHERE pack_id = ?",
            (json.dumps(payload, ensure_ascii=False), generated_at, pack_id),
        )

    return {
        "pack_id": pack_id,
        "chapters": _chapter_meta(payload["chapters"]),
        "generated_at": generated_at,
    }


def _chapter_meta(chapters: list[dict]) -> list[dict]:
    return [{
        "key": c["key"],
        "title": c["title"],
        "item_count": len(c["items"]),
        "empty": not c["items"],
    } for c in chapters]


def _aggregate(conn: sqlite3.Connection, *, user_id: int, session_id: int,
               include_mindmap: bool) -> dict:
    """按契约固定顺序聚合五章内容（只读，不生成新内容）。"""
    by_key = {
        "notes": _note_items(conn, session_id),
        "points": _key_points(conn, session_id),
        "mindmap": _mindmap_lines(conn, session_id) if include_mindmap else [],
        "quiz": _quiz_items(conn, user_id, session_id),
        "wrong": _wrong_items(conn, user_id, session_id),
    }
    return {
        "chapters": [
            {"key": key, "title": title, "items": by_key[key]}
            for key, title in CHAPTERS
        ]
    }


def _note_items(conn: sqlite3.Connection, session_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT ni.name, ni.definition, ni.key_points_json, ni.formula_latex,"
        " ni.importance, ni.evidence_json, n.chapter_title"
        "  FROM note_items ni"
        "  JOIN notes n ON n.note_id = ni.note_id"
        " WHERE n.session_id = :sid AND n.content_type = 'note'"
        " ORDER BY n.note_id, ni.sort_order, ni.item_id",
        {"sid": int(session_id)},
    ).fetchall()
    return [{
        "chapter": r["chapter_title"] or "",
        "name": r["name"] or "",
        "definition": r["definition"] or "",
        "key_points": [str(p) for p in _loads(r["key_points_json"], [])],
        "formula_latex": r["formula_latex"] or "",
        "importance": int(r["importance"] or 3),
        "evidence": _evidence_list(r["evidence_json"]),
    } for r in rows]


def _key_points(conn: sqlite3.Connection, session_id: int) -> list[str]:
    row = conn.execute(
        "SELECT content FROM notes"
        " WHERE session_id = :sid AND content_type = 'key_points'"
        " ORDER BY note_id LIMIT 1",
        {"sid": int(session_id)},
    ).fetchone()
    if row is None:
        return []
    raw = (row["content"] or "").strip()
    if not raw:
        return []
    if raw.startswith("["):
        parsed = _loads(raw, [])
        if isinstance(parsed, list):
            return [str(x) for x in parsed if str(x).strip()]
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _mindmap_lines(conn: sqlite3.Connection, session_id: int) -> list[str]:
    """取已经存在的导图（文本导图优先，其次是 mindmap_nodes 树）。

    只读已有数据：C4 裁决明确禁止在导出时临时生成导图，
    所以这里绝不调用 mindmap.build_tree。
    """
    row = conn.execute(
        "SELECT content FROM notes"
        " WHERE session_id = :sid AND content_type = 'mindmap'"
        " ORDER BY note_id LIMIT 1",
        {"sid": int(session_id)},
    ).fetchone()
    if row is not None and (row["content"] or "").strip():
        return [line for line in row["content"].splitlines() if line.strip()]

    nodes = conn.execute(
        "SELECT name, level FROM mindmap_nodes"
        " WHERE session_id = :sid ORDER BY node_id",
        {"sid": int(session_id)},
    ).fetchall()
    return ["　" * max(0, int(n["level"] or 1) - 1) + (n["name"] or "")
            for n in nodes if (n["name"] or "").strip()]


def _quiz_items(conn: sqlite3.Connection, user_id: int, session_id: int) -> list[dict]:
    """本 session 的自测题。答案与解析只在已判分（graded）时写入快照。"""
    tests = conn.execute(
        "SELECT test_id, status FROM self_tests"
        " WHERE session_id = :sid AND user_id = :uid ORDER BY test_id",
        {"sid": int(session_id), "uid": int(user_id)},
    ).fetchall()
    items: list[dict] = []
    for test in tests:
        graded = (test["status"] or "") == "graded"
        rows = conn.execute(
            "SELECT knowledge_name, question_type, stem, options_json, answer,"
            " analysis, evidence_page FROM self_test_items"
            " WHERE test_id = :tid ORDER BY seq",
            {"tid": int(test["test_id"])},
        ).fetchall()
        for r in rows:
            options = _loads(r["options_json"], [])
            items.append({
                "test_id": int(test["test_id"]),
                "knowledge_name": r["knowledge_name"] or "",
                "question_type": r["question_type"] or "single",
                "stem": r["stem"] or "",
                "options": [str(o) for o in options] if isinstance(options, list) else [],
                "answer": (r["answer"] or "") if graded else "",
                "analysis": (r["analysis"] or "") if graded else "",
                "evidence_page": r["evidence_page"],
            })
    return items


def _wrong_items(conn: sqlite3.Connection, user_id: int, session_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT w.knowledge_name, w.question_stem, w.correct_answer, w.analysis,"
        " w.wrong_count, w.mastered, w.evidence_page, w.state"
        "  FROM wrong_questions w"
        " WHERE w.user_id = :uid AND w.source_type = 'self_test'"
        "   AND w.source_id IN ("
        "       SELECT i.item_id FROM self_test_items i"
        "        JOIN self_tests t ON t.test_id = i.test_id"
        "       WHERE t.session_id = :sid AND t.user_id = :uid)"
        " ORDER BY w.wrong_count DESC, w.wrong_id DESC",
        {"uid": int(user_id), "sid": int(session_id)},
    ).fetchall()
    return [{
        "knowledge_name": r["knowledge_name"] or "",
        "question_stem": r["question_stem"] or "",
        "correct_answer": r["correct_answer"] or "",
        "analysis": r["analysis"] or "",
        "wrong_count": int(r["wrong_count"] or 0),
        "mastered": bool(r["mastered"]),
        "evidence_page": r["evidence_page"],
        "state": r["state"] or "new",
    } for r in rows]


# --------------------------------------------------------------------------
# 导出
# --------------------------------------------------------------------------
def export(conn: sqlite3.Connection, *, pack_id: int, user_id: int,
           fmt: str = "docx") -> tuple[bytes, str]:
    """按 pack_id 导出复习包，返回 (文件字节, 文件名)。

    只支持 docx（契约 3.2）；其他 fmt 返回 400。
    """
    if (fmt or "").strip().lower() != "docx":
        raise ReviewError("fmt 目前只支持 docx", 400)

    _ensure_table(conn)
    row = conn.execute(
        "SELECT payload_json, status FROM review_packs"
        " WHERE pack_id = ? AND user_id = ?",
        (int(pack_id), int(user_id)),
    ).fetchone()
    if row is None:
        raise ReviewError("复习包不存在", 404)
    if row["status"] != "ready":
        raise ReviewError("复习包尚未生成完成，请稍后再试", 409)

    payload = _loads(row["payload_json"], {})
    if not isinstance(payload, dict):
        payload = {}
    content = _render_docx(payload)
    course = (payload.get("course_name") or "课程").strip()
    return content, f"{_safe_stem(course)}-复习包-v1.3.docx"


def _safe_stem(name: str) -> str:
    keep = [ch for ch in (name or "") if ch.isalnum() or ch in "-_"]
    return ("".join(keep) or "course")[:40]


# ---- docx 渲染（单章失败只降级该章）----
def _tidy(text: Any) -> str:
    s = str(text or "")
    s = s.replace("\x0b", "\n").replace("\x0c", "\n").replace("\x00", "")
    return s.translate(_CTRL_TO_DROP).strip()


def _set_cjk(run, name: str = "宋体") -> None:
    run.font.name = name
    run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), name)


def _heading(doc, text: str, level: int) -> None:
    para = doc.add_heading(level=level)
    _set_cjk(para.add_run(_tidy(text)), "微软雅黑")


def _para(doc, text: str, *, size: float = 10.5, bold: bool = False,
          color: RGBColor | None = None, mono: bool = False) -> None:
    para = doc.add_paragraph()
    run = para.add_run(_tidy(text))
    run.font.size = Pt(size)
    run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color
    _set_cjk(run, "Consolas" if mono else "宋体")


def _bullet(doc, text: str, *, size: float = 10) -> None:
    para = doc.add_paragraph(style="List Bullet")
    run = para.add_run(_tidy(text))
    run.font.size = Pt(size)
    _set_cjk(run)


def _evidence_label(ev: dict) -> str:
    page = ev.get("page_num")
    slide = ev.get("slide_index")
    if page:
        return f"第 {page} 页"
    if slide:
        return f"第 {slide} 张幻灯片"
    return str(ev.get("chunk_key") or "出处未知")


def _render_docx(payload: dict) -> bytes:
    doc = Document()

    normal = doc.styles["Normal"]
    normal.font.size = Pt(10.5)
    normal.font.name = "宋体"
    normal.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "宋体")

    course = (payload.get("course_name") or "课程").strip() or "课程"
    title = doc.add_heading(level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_cjk(title.add_run(_tidy(f"{course} · 期末复习包")), "微软雅黑")
    _para(doc, f"版本 v1.3.0　｜　生成时间 {payload.get('generated_at') or '—'}　｜　"
               "由「课程课件笔记整理 Agent」生成",
          size=9, color=GREY)

    chapters = payload.get("chapters") or []
    for chapter in chapters:
        title_text = chapter.get("title") or chapter.get("key") or "未命名章节"
        _heading(doc, title_text, 1)
        items = chapter.get("items") or []
        if not items:
            # C4 裁决：空章写一句说明，不报错、不现场补生成
            _para(doc, "本次未生成此项。", size=9.5, color=LIGHT_GREY)
            continue
        try:
            _render_chapter(doc, str(chapter.get("key") or ""), items)
        except Exception as exc:  # noqa: BLE001 - 单章失败降级，整体仍导出
            _para(doc, f"该章生成失败（{type(exc).__name__}），其余章节不受影响。",
                  size=9, color=FAIL_RED)

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _render_chapter(doc, key: str, items: list[dict]) -> None:
    if key == "notes":
        _render_notes(doc, items)
    elif key == "points":
        for point in items:
            _bullet(doc, str(point))
    elif key == "mindmap":
        for line in items:
            _para(doc, str(line), size=9.5, mono=True)
    elif key == "quiz":
        _render_quiz(doc, items)
    elif key == "wrong":
        _render_wrong(doc, items)
    else:  # 未知章按通用列表兜底，不让整份导出失败
        for item in items:
            _para(doc, json.dumps(item, ensure_ascii=False))


def _render_notes(doc, items: list[dict]) -> None:
    current_chapter = None
    for item in items:
        chapter = item.get("chapter") or "未标注章节"
        if chapter != current_chapter:
            _heading(doc, chapter, 2)
            current_chapter = chapter

        _para(doc, item.get("name") or "（未命名知识点）", bold=True, size=11)
        definition = (item.get("definition") or "").strip()
        if definition:
            _para(doc, definition)
        for point in item.get("key_points") or []:
            _bullet(doc, str(point))
        formula = (item.get("formula_latex") or "").strip()
        if formula:
            _para(doc, f"公式：{formula}", mono=True, color=RGBColor(0xC7, 0x25, 0x4E))
        evidence = item.get("evidence") or []
        if evidence:
            labels = "、".join(_evidence_label(ev) for ev in evidence[:3])
            _para(doc, f"【出处】{labels}", size=9, color=LIGHT_GREY)
            quote = str(evidence[0].get("quote") or "").strip()
            if quote:
                _para(doc, f"「{quote[:120]}」", size=9, color=LIGHT_GREY)
        _para(doc, "", size=4)


def _render_quiz(doc, items: list[dict]) -> None:
    for idx, item in enumerate(items, start=1):
        _para(doc, f"{idx}. {item.get('stem') or '（题干缺失）'}", bold=True)
        options = item.get("options") or []
        for letter, option in zip("ABCD", options):
            _para(doc, f"　{letter}. {option}", size=10)
        if item.get("answer"):
            _para(doc, f"答案：{item['answer']}", size=9.5, color=GREY)
        if item.get("analysis"):
            _para(doc, f"解析：{item['analysis']}", size=9.5, color=GREY)


def _render_wrong(doc, items: list[dict]) -> None:
    for idx, item in enumerate(items, start=1):
        knowledge = item.get("knowledge_name") or "未标注知识点"
        _para(doc, f"{idx}. [{knowledge}] {item.get('question_stem') or ''}", bold=True)
        _para(doc, f"正确答案：{item.get('correct_answer') or '—'}", size=10)
        if item.get("analysis"):
            _para(doc, f"解析：{item['analysis']}", size=9.5, color=GREY)
        status = "已掌握" if item.get("mastered") else "未掌握"
        _para(doc, f"累计答错 {int(item.get('wrong_count') or 0)} 次　｜　{status}",
              size=9, color=LIGHT_GREY)
