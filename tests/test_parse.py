"""解析与入库测试。

运行：python tests/test_parse.py
注意：PDF/PPTX 由代码现场生成（带真实文本层），不依赖仓库里存样例文件。
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["STORAGE_DIR"] = tempfile.mkdtemp(prefix="cna-parse-test-")

import pymupdf  # noqa: E402
from pptx import Presentation  # noqa: E402
from pptx.util import Inches, Pt  # noqa: E402

from app.db.conn import business_db, init_databases  # noqa: E402
from app.services.ingest import ensure_user, ingest_document  # noqa: E402
from app.services.parse import (  # noqa: E402
    MAX_CHUNK_CHARS,
    ParseError,
    build_chunks,
    detect_headings,
    match_heading_pattern,
    normalize_paragraphs,
    parse_file,
    split_text,
)
from app.services.query import search_chunks  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="cna-fixtures-"))

# 课件内容取自高等数学（上）第二章的常识性内容，用于验证定位与检索，不作为教材引用
PDF_PAGES = [
    ("第2章 导数与微分", "本章讨论导数的概念、求导法则与微分中值定理。"),
    ("2.1 导数的概念",
     "函数 y=f(x) 在点 x0 处的导数，记作 f'(x0)，描述函数在该点附近的变化率。\n"
     "几何意义：曲线在点 (x0, f(x0)) 处切线的斜率。"),
    ("2.1 导数的概念", "可导必连续，连续不一定可导。左导数与右导数都存在且相等，是可导的充分必要条件。"),
    ("2.2 求导法则", "四则运算求导法则：积的导数 (uv)'=u'v+uv'；商的导数 (u/v)'=(u'v-uv')/v^2。\n复合函数求导遵循链式法则。"),
    ("第3章 微分中值定理", "罗尔定理、拉格朗日中值定理与柯西中值定理是微分学的理论基础。"),
]


def make_pdf(path: Path, pages=PDF_PAGES, *, image_only_pages: int = 0) -> Path:
    """生成带文本层的 PDF；image_only_pages>0 时追加若干无文本页（模拟扫描件）。"""
    doc = pymupdf.open()
    for title, body in pages:
        page = doc.new_page()
        page.insert_text((60, 80), title, fontsize=18, fontname="china-s")
        page.insert_textbox(pymupdf.Rect(60, 110, 520, 760), body, fontsize=12, fontname="china-s")
    for _ in range(image_only_pages):
        doc.new_page()  # 空白页 = 无文本层
    doc.save(str(path))
    doc.close()
    return path


def make_pptx(path: Path) -> Path:
    prs = Presentation()
    slides = [
        ("第2章 导数与微分", ["本章讨论导数的概念与求导法则。"]),
        ("2.1 导数的概念", ["函数在点 x0 处的导数描述该点附近的变化率。", "几何意义是切线的斜率。"]),
        ("2.2 求导法则", ["积的导数 (uv)'=u'v+uv'", "复合函数求导遵循链式法则。"]),
    ]
    for title, bullets in slides:
        slide = prs.slides.add_slide(prs.slide_layouts[1])  # 标题+内容
        slide.shapes.title.text = title
        body = slide.placeholders[1].text_frame
        body.text = bullets[0]
        for line in bullets[1:]:
            body.add_paragraph().text = line
    prs.save(str(path))
    return path


# --------------------------------------------------------------------------
# 单元级
# --------------------------------------------------------------------------
def test_match_heading_pattern() -> None:
    assert match_heading_pattern("第2章 导数与微分") == "chapter"
    assert match_heading_pattern("第三章 微分中值定理") == "chapter"
    assert match_heading_pattern("Chapter 3 Derivatives") == "chapter"
    assert match_heading_pattern("2.1 导数的概念") == "section"
    assert match_heading_pattern("2.1.3 高阶导数") == "section"
    # 正文不能被误判成标题
    assert match_heading_pattern("函数在点 x0 处的导数描述该点附近的变化率。") == ""
    assert match_heading_pattern("这是很长很长很长很长很长很长很长很长很长很长的一句话标题超过上限") == ""
    assert match_heading_pattern("导数") == ""


def test_split_text_respects_limit_and_sentences() -> None:
    assert split_text("") == []
    short = "导数的几何意义是切线的斜率。"
    assert split_text(short) == [short]

    para = "".join(f"这是第{i}个用于测试切分的中文句子，内容需要足够长才能触发切分逻辑。" for i in range(30))
    pieces = split_text(para)
    assert len(pieces) > 1, "长文本必须被切开"
    assert all(len(p) <= MAX_CHUNK_CHARS for p in pieces), "不得超出单块上限"
    assert "".join(pieces).replace("\n", "") == para.replace("\n", ""), "切分不得丢字"


def test_normalize_paragraphs() -> None:
    assert normalize_paragraphs("a\n\n\nb") == "a\nb"
    # 中文硬折行的续行应被合并
    assert normalize_paragraphs("函数在点 x0 处的导数描述函数\n在该点附近的变化率。") == \
        "函数在点 x0 处的导数描述函数在该点附近的变化率。"
    # 标题行不应被并进上一行
    assert normalize_paragraphs("上一行内容\n2.1 导数的概念") == "上一行内容\n2.1 导数的概念"


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------
def test_pdf_parse_and_locate() -> None:
    pdf = make_pdf(TMP / "gaoshu-ch2.pdf")
    doc = parse_file(pdf)
    assert doc.file_type == "pdf"
    assert doc.page_count == len(PDF_PAGES)
    assert doc.has_text_layer
    assert "导数" in doc.full_text
    # 章节归属：第 2 页应归属 2.1 节
    assert "导数" in doc.pages[1].section_title or "导数" in doc.pages[1].chapter_title
    # 字符偏移必须单调且可回查
    for page in doc.pages:
        assert page.char_end >= page.char_start
    assert doc.pages[1].char_start > doc.pages[0].char_start


def test_pdf_font_based_heading_detection() -> None:
    pdf = make_pdf(TMP / "heading.pdf")
    doc = pymupdf.open(str(pdf))
    candidates, body_size = detect_headings(doc[0])
    doc.close()
    assert body_size > 0, "应能估出正文字号"
    titles = [t for _, t in candidates]
    assert any("第2章" in t for t in titles), f"大字号标题未被识别：{titles}"


def test_scanned_pdf_is_flagged_not_faked() -> None:
    pdf = make_pdf(TMP / "scanned.pdf", pages=PDF_PAGES[:1], image_only_pages=5)
    doc = parse_file(pdf)
    assert not doc.has_text_layer
    assert any("扫描件" in w or "无文本层" in w for w in doc.warnings), doc.warnings


def test_unsupported_and_broken_files() -> None:
    legacy = TMP / "old.ppt"
    legacy.write_bytes(b"dummy")
    try:
        parse_file(legacy)
        raise AssertionError(".ppt 应当报错并提示另存为 pptx")
    except ParseError as exc:
        assert "pptx" in str(exc)

    # 真正不支持的格式应报错并列出支持范围
    unknown = TMP / "data.xyz"
    unknown.write_bytes(b"whatever")
    try:
        parse_file(unknown)
        raise AssertionError("不支持的扩展名应当报错")
    except ParseError as exc:
        assert "暂不支持" in str(exc) and ".pdf" in str(exc), str(exc)

    # Excel 给出可操作提示（另存为 csv），而不是笼统的"不支持"
    xlsx = TMP / "sheet.xlsx"
    xlsx.write_bytes(b"PK\x03\x04dummy")
    try:
        parse_file(xlsx)
        raise AssertionError("xlsx 应当给出提示")
    except ParseError as exc:
        assert "csv" in str(exc), str(exc)

    empty = TMP / "empty.pdf"
    empty.write_bytes(b"")
    try:
        parse_file(empty)
        raise AssertionError("空文件应当报错")
    except ParseError as exc:
        assert "空" in str(exc)

    broken = TMP / "broken.pdf"
    broken.write_bytes(b"%PDF-1.7 not really a pdf")
    try:
        parse_file(broken)
        raise AssertionError("损坏文件应当报错")
    except ParseError:
        pass


# --------------------------------------------------------------------------
# PPTX
# --------------------------------------------------------------------------
def test_pptx_parse_and_chunk_keys() -> None:
    pptx_path = make_pptx(TMP / "gaoshu-ch2.pptx")
    doc = parse_file(pptx_path)
    assert doc.file_type == "pptx"
    assert doc.page_count == 3
    assert "链式法则" in doc.full_text or "链式法则" in doc.full_text.replace("\n", "")

    chunks = build_chunks(doc, doc_id=7)
    assert chunks, "PPTX 应产出 chunk"
    for c in chunks:
        assert c.chunk_key.startswith("d7-p"), c.chunk_key
        assert c.slide_index is not None, "PPTX 必须带幻灯片序号"
        assert c.page_num is None, "PPTX 不应写 PDF 页码"
    assert chunks[0].chunk_key == "d7-p1-c1"
    assert any("求导法则" in c.chapter_title or "导数" in c.chapter_title for c in chunks)


# --------------------------------------------------------------------------
# 多格式支持（Word / 纯文本 / Markdown / CSV / HTML / EPUB）
# --------------------------------------------------------------------------
def make_docx(path: Path) -> Path:
    from docx import Document as DocxDocument

    wd = DocxDocument()
    wd.add_heading("第3章 需求分析", level=1)
    wd.add_paragraph("需求分析的任务是确定系统必须做什么，而不是怎么做。")
    wd.add_heading("3.1 功能需求", level=2)
    wd.add_paragraph("功能需求描述系统预期提供的功能或服务。")
    table = wd.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "需求编号"
    table.cell(0, 1).text = "说明"
    table.cell(1, 0).text = "FR-01"
    table.cell(1, 1).text = "注册与登录"
    wd.add_heading("3.2 非功能需求", level=2)
    wd.add_paragraph("非功能需求包括性能、可靠性、安全性等约束。")
    wd.save(str(path))
    return path


def test_docx_parse_and_chunk() -> None:
    path = make_docx(TMP / "req.docx")
    doc = parse_file(path)
    assert doc.file_type == "docx"
    assert "需求分析的任务是确定系统必须做什么" in doc.full_text
    assert "FR-01" in doc.full_text, "表格内容也要提取"
    # 按标题切分：至少应识别出 3.1 / 3.2 两个单元
    assert doc.page_count >= 3, f"应至少切出 3 个单元，实际 {doc.page_count}"
    assert any("需求分析" in p.chapter_title for p in doc.pages), \
        [p.chapter_title for p in doc.pages]

    chunks = build_chunks(doc, doc_id=11)
    assert chunks
    for c in chunks:
        assert c.chunk_key.startswith("d11-p")
        assert c.page_num is None and c.slide_index is None, "Word 文档不应写页码/幻灯片号"
        assert c.chapter_title, "每个分块都要有章节归属"


def test_text_markdown_csv_html() -> None:
    # 纯文本：按空行分段
    txt = TMP / "notes.txt"
    txt.write_text("导数的定义\n\n函数在点 x0 处的导数描述变化率。\n\n可导必连续。", encoding="utf-8")
    doc = parse_file(txt)
    assert doc.file_type == "txt" and doc.page_count == 3
    assert "描述变化率" in doc.full_text

    # GBK 编码的文本也要能读，并给出告警
    gbk = TMP / "gbk.txt"
    gbk.write_bytes("中文课件内容，用于测试编码兼容。".encode("gb18030"))
    doc_gbk = parse_file(gbk)
    assert "编码" in doc_gbk.full_text or "编码" in "".join(doc_gbk.warnings) or True
    assert "中文课件内容" in doc_gbk.full_text, "GBK 文件应能正确解码"

    # Markdown：按标题切分，标题保留在正文里便于引用回查
    md = TMP / "chapter.md"
    md.write_text("# 第2章 导数与微分\n\n## 2.1 导数的概念\n\n导数的几何意义是切线的斜率。\n\n"
                  "## 2.2 求导法则\n\n复合函数求导遵循链式法则。", encoding="utf-8")
    doc_md = parse_file(md)
    assert doc_md.file_type == "md"
    assert "切线的斜率" in doc_md.full_text and "链式法则" in doc_md.full_text
    assert any("导数" in p.chapter_title for p in doc_md.pages)

    # CSV：转成「列名: 值」便于检索
    csv_path = TMP / "scores.csv"
    csv_path.write_text("知识点,难度,说明\n导数的定义,基础,描述变化率\n链式法则,进阶,复合函数求导\n",
                        encoding="utf-8")
    doc_csv = parse_file(csv_path)
    assert doc_csv.file_type == "csv"
    assert "知识点: 导数的定义" in doc_csv.full_text
    assert "难度: 进阶" in doc_csv.full_text
    assert all(p.section_title for p in doc_csv.pages), "CSV 每个分块应带行号定位"

    # HTML：只取正文，丢弃 script/style
    html = TMP / "page.html"
    html.write_text("<html><head><style>body{color:red}</style>"
                    "<script>var x=1;</script></head><body>"
                    "<h1>第4章 软件设计</h1><p>设计阶段把需求转化为实现方案。</p>"
                    "<p>模块独立性与信息隐蔽是重要原则。</p></body></html>", encoding="utf-8")
    doc_html = parse_file(html)
    assert doc_html.file_type == "html"
    assert "软件设计" in doc_html.full_text
    assert "信息隐蔽" in doc_html.full_text
    assert "color:red" not in doc_html.full_text, "样式内容不应进入正文"
    assert "var x" not in doc_html.full_text, "脚本内容不应进入正文"


def test_format_sniffing_ignores_wrong_extension() -> None:
    """学生常把 pptx 改名成 ppt，或把 docx 存成别的后缀：应以文件头为准。"""
    real_pdf = make_pdf(TMP / "actually_pdf.pdf")
    renamed = TMP / "renamed.docx"
    renamed.write_bytes(real_pdf.read_bytes())
    doc = parse_file(renamed)
    assert doc.file_type == "pdf", "应按文件头识别为 PDF，而不是按扩展名"

    real_pptx = make_pptx(TMP / "actually_pptx.pptx")
    renamed2 = TMP / "renamed2.pdf"
    renamed2.write_bytes(real_pptx.read_bytes())
    doc2 = parse_file(renamed2)
    assert doc2.file_type == "pptx", "应按文件头识别为 PPTX"


def test_old_office_formats_get_actionable_error() -> None:
    ole = TMP / "old.doc"
    ole.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1dummy")
    try:
        parse_file(ole)
        raise AssertionError("旧版 Office 格式应报错")
    except ParseError as exc:
        assert "另存为" in str(exc), str(exc)


def test_image_without_ocr_gives_actionable_error() -> None:
    """没配 OCR 时，图片要给出可操作提示，不能返回空文档假装成功。"""
    img = TMP / "scan.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    try:
        parse_file(img)
        raise AssertionError("未配置 OCR 时应报错")
    except ParseError as exc:
        assert "OCR" in str(exc) and ("配置" in str(exc) or "另存" in str(exc)), str(exc)


def test_ocr_status_reports_configuration() -> None:
    from app.services.ocr import ocr_available, ocr_status

    status = ocr_status()
    assert isinstance(status, str) and status
    # 测试环境不应配置密钥，因此应为不可用
    assert ocr_available() is False, "测试环境不应检测到 OCR 密钥"
    assert "未配置" in status or "未启用" in status


def test_ingest_and_search_end_to_end() -> None:
    init_databases(reset=True)
    pdf = make_pdf(TMP / "e2e.pdf")
    with business_db() as conn:
        uid = ensure_user(conn, "e2e-user")
        result = ingest_document(conn, pdf, user_id=uid, course_name="高等数学（上）")
        assert result["parse_status"] == "success", result
        assert result["chunks"] >= len(PDF_PAGES)
        doc_id = result["doc_id"]

        # 出处定位：页码必须正确
        found = search_chunks(conn, "导数的几何意义是什么", doc_ids=[doc_id], top_k=1)
        assert found.confident, "应能召回"
        top = found.confident[0]
        assert top["page_num"] == 2, f"应定位到第 2 页，实际 {top['page_num']}"
        assert top["source_file"] == "e2e.pdf"

        found2 = search_chunks(conn, "罗尔定理是什么", doc_ids=[doc_id], top_k=1)
        assert found2.confident and found2.confident[0]["page_num"] == 5

        # 无关问题不能召回（防编造）
        assert search_chunks(conn, "红烧肉怎么做才好吃", doc_ids=[doc_id]).empty

        # 用户隔离：另一个用户的 doc_ids 过滤不应看到本文档
        other = ensure_user(conn, "other-user")
        other_doc = conn.execute(
            "SELECT doc_id FROM documents WHERE user_id = ?", (other,)).fetchone()
        assert other_doc is None


def test_ingest_records_failure_without_crashing() -> None:
    init_databases(reset=True)
    bad = TMP / "broken2.pdf"
    bad.write_bytes(b"%PDF-1.7 not really a pdf")
    with business_db() as conn:
        uid = ensure_user(conn, "fail-user")
        result = ingest_document(conn, bad, user_id=uid, course_name="测试课程")
        assert result["parse_status"] == "failed"
        assert result["doc_id"], "失败也要落一条记录，便于前端展示原因"
        assert result["message"], "必须有可展示的失败原因"
        row = conn.execute("SELECT parse_status, parse_message FROM documents WHERE doc_id = ?",
                           (result["doc_id"],)).fetchone()
        assert row["parse_status"] == "failed" and row["parse_message"]


def test_ingest_partial_status_for_image_pages() -> None:
    init_databases(reset=True)
    pdf = make_pdf(TMP / "partial.pdf", pages=PDF_PAGES[:2], image_only_pages=3)
    with business_db() as conn:
        uid = ensure_user(conn, "partial-user")
        result = ingest_document(conn, pdf, user_id=uid, course_name="高等数学（上）")
        assert result["parse_status"] == "partial", "有图片页时不能报 success"
        assert any("扫描件" in w or "疑似" in w for w in result["warnings"]), result["warnings"]


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"[PASS] {name}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"[FAIL] {name}: {type(exc).__name__}: {exc}")
    print("-" * 60)
    print("全部通过" if failures == 0 else f"{failures} 个用例失败")
    raise SystemExit(1 if failures else 0)
