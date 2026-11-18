"""把整理结果渲染成 Word（.docx）。

为什么要有这个导出：
    作业与课程材料本身都是 Word 交付，学生把笔记直接粘进作业文档是真实需求。
    Markdown 适合贴博客，LaTeX 适合排公式，Word 适合交作业——使用场景不同。

数据结构提醒（踩过的坑）：
    repo.session_result() 返回的是 NoteResult，知识点挂在 **outline 树** 上
    （OutlineNode.title / .summary / .items），并没有扁平的 .items 字段。
    第一版按 .items 渲染，导出的 Word 只有重点清单和导图，结构化笔记整段是空的。

排版原则（不追求花哨，只求结构清楚、可直接改）：
    1. 课程名做标题，自评做小字说明；
    2. 章节用「标题 1」，知识点用「标题 2」；
    3. 定义、要点、公式、出处依次排列，出处明确到页码或幻灯片序号；
    4. 末尾附重点清单、文本思维导图与质量自评。
"""

from __future__ import annotations

import io
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

GREY = RGBColor(0x66, 0x66, 0x66)
LIGHT_GREY = RGBColor(0x90, 0x93, 0x99)
FORMULA_RED = RGBColor(0xC7, 0x25, 0x4E)

# XML 1.0 不允许的控制字符（保留 \t \n \r）。
# PPT 抽出的文本经常带 \x0b（PPT 里的软换行）和 \x07 之类，
# 直接塞进 python-docx 会抛 ValueError: All strings must be XML compatible，
# 表现就是线上「导出 Word」返回 500 —— 这是线上实测踩到的坑。
_CTRL_TO_DROP = {c: None for c in range(0x20) if c not in (0x09, 0x0A, 0x0D)}


def _tidy(text: Any) -> str:
    """清掉 XML 不允许的控制字符，并把 PPT 的软换行统一成换行符。"""
    s = str(text or "")
    s = s.replace("\x0b", "\n").replace("\x0c", "\n").replace("\x00", "")
    return s.translate(_CTRL_TO_DROP).strip()


def _set_cjk(run, name: str = "宋体") -> None:
    """python-docx 默认只设西文字体，中文需单独设 eastAsia 才生效。

    注意：rPr / rFonts 节点可能不存在，必须 get_or_add_*，
    直接访问 run._element.rPr.rFonts 在干净文档上会 AttributeError。
    """
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


def _evidence_label(ev: Any) -> str:
    page = getattr(ev, "page_num", None)
    slide = getattr(ev, "slide_index", None)
    chapter = getattr(ev, "chapter_title", "") or ""
    if page:
        return f"第 {page} 页"
    if slide:
        return f"第 {slide} 张幻灯片"
    return chapter or "出处未知"


def render_note_docx(result: Any, *, course_name: str = "") -> bytes:
    """返回 .docx 字节内容。result 为 NoteResult（含 outline 树）。"""
    doc = Document()

    normal = doc.styles["Normal"]
    normal.font.size = Pt(10.5)
    normal.font.name = "宋体"
    normal.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "宋体")

    title = doc.add_heading(level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_cjk(title.add_run(_tidy(course_name or getattr(result, "course_name", "") or "课程笔记")),
             "微软雅黑")

    meta_bits = []
    quality = getattr(result, "quality", None)
    if quality is not None:
        meta_bits.append(f"质量自评 {getattr(quality, 'total', '')} / 100")
    meta_bits.append("由「课程课件笔记整理 Agent」生成，结论均带原文出处")
    _para(doc, "　｜　".join(meta_bits), size=9, color=GREY)

    # ---- 结构化笔记：遍历 outline 树 ----
    outline = list(getattr(result, "outline", None) or [])
    for node in outline:
        _heading(doc, getattr(node, "title", "") or "未命名章节", 1)
        summary = (getattr(node, "summary", "") or "").strip()
        if summary:
            _para(doc, summary, size=9.5, color=GREY)

        for item in getattr(node, "items", None) or []:
            _heading(doc, getattr(item, "name", "") or "（未命名）", 2)

            definition = (getattr(item, "definition", "") or "").strip()
            if definition:
                _para(doc, definition)

            for point in getattr(item, "key_points", None) or []:
                bullet = doc.add_paragraph(style="List Bullet")
                run = bullet.add_run(_tidy(point))
                run.font.size = Pt(10)
                _set_cjk(run)

            formula = getattr(item, "formula_latex", "") or ""
            if formula:
                _para(doc, f"公式：{formula}", mono=True, color=FORMULA_RED)

            evidence = getattr(item, "evidence", None) or []
            if evidence:
                labels = "、".join(_evidence_label(ev) for ev in evidence[:3])
                _para(doc, f"【出处】{labels}", size=9, color=LIGHT_GREY)
                quote = (getattr(evidence[0], "quote", "") or "").strip()
                if quote:
                    _para(doc, f"「{quote[:120]}」", size=9, color=LIGHT_GREY)

    key_points = list(getattr(result, "key_points", None) or [])
    if key_points:
        _heading(doc, "重点清单", 1)
        for point in key_points:
            _para(doc, f"· {point}", size=10)

    mindmap = (getattr(result, "mindmap_text", "") or "").strip()
    if mindmap:
        _heading(doc, "知识结构", 1)
        for line in mindmap.splitlines():
            _para(doc, line, size=9.5, mono=True)

    if quality is not None:
        _heading(doc, "整理质量自查（85% / 10% / 5%）", 1)
        _para(doc, f"总分 {getattr(quality, 'total', '')} / 100　"
                   f"核心 {getattr(quality, 'core', '')}　"
                   f"结构 {getattr(quality, 'structure', '')}　"
                   f"关联 {getattr(quality, 'extension', '')}")
        for reason in getattr(quality, "reasons", None) or []:
            _para(doc, f"· {reason}", size=9, color=GREY)

    dropped = getattr(result, "dropped_items", 0) or 0
    if dropped:
        _para(doc, f"注：有 {dropped} 条内容因无法在原文中核验出处而被丢弃。",
              size=9, color=GREY)

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
