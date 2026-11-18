"""课件解析：任意学习资料 → 带定位信息的文本块。

本模块只做「文件 → 结构化文本」，不碰数据库（入库见 services/ingest.py），
这样解析逻辑可以脱离数据库单独测试。

支持格式通过 _EXTRACTORS 注册表扩展：加一种格式 = 加一个函数，
下游的切块、索引、检索、证据校验完全不用改。

三条硬要求（对应 SRS 3.2.2 与 FR-02）：
  1. 每一块都必须带上出处定位：PDF 带页码、PPTX 带幻灯片序号、Word 带章节层级、
     纯文本带行号；无法给出行内定位时至少要有章节或文件名；
  2. 无法读取的内容必须如实上报（扫描件、加密、空文件、编码异常），不能假装解析成功；
  3. 单页/单文件的失败不能让整单任务崩掉，记进 warnings，状态由上层判为 partial。
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pymupdf

# --------------------------------------------------------------------------
# 支持格式
# --------------------------------------------------------------------------
# 常规格式：有对应提取器
SUPPORTED_EXTENSIONS = {
    ".pdf", ".pptx", ".docx",
    ".txt", ".md", ".markdown", ".text",
    ".html", ".htm", ".csv", ".epub",
    # 以下需要 OCR 能力，未配置时给出明确提示而不是静默失败
    ".png", ".jpg", ".jpeg", ".webp", ".bmp",
}
# 旧格式：有更好替代，明确提示用户转换
LEGACY_EXTENSIONS = {
    ".ppt": "PowerPoint 旧格式，请在 PowerPoint 中另存为 .pptx",
    ".doc": "Word 旧格式，请在 Word 中另存为 .docx",
    ".xls": "Excel 旧格式，请另存为 .xlsx",
    ".wps": "WPS 格式，请另存为 .docx 或 .pdf",
    ".caj": "CAJ 格式，请从知网导出为 PDF",
}
# 尚未支持但常被上传的格式：给出可操作的提示
UNSUPPORTED_HINTS = {
    ".xlsx": "Excel 表格暂未支持，可另存为 .csv 后上传",
    ".zip": "压缩包请先解压，逐个文件上传",
    ".rtf": "RTF 请另存为 .docx 或 .pdf",
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

# 平均每页文本少于该字符数 → 判为扫描件（无文本层）
SCANNED_CHARS_PER_PAGE = 40
# 替换符/私用区字符占比超过该值 → 判为字体缺字或编码异常
GARBLED_REPLACEMENT_RATIO = 0.15

# 章节/小节标题识别
# 注意：章号与标题之间可能是空格、全角空格、顿号或直接相连，
# 「第1章 函数与极限」与「第1章函数与极限」必须都能识别（实测两种写法都很常见）。
_CHAPTER_PATTERNS = [
    re.compile(r"^第\s*[0-9一二三四五六七八九十百]+\s*[章讲部篇]"),
    re.compile(r"^(chapter|unit|part)\s*[0-9ivx]+", re.I),
]
_SECTION_PATTERNS = [
    re.compile(r"^[0-9]{1,2}\.[0-9]{1,2}(?:\.[0-9]{1,3})?\s*\S"),
    re.compile(r"^第\s*[0-9一二三四五六七八九十百]+\s*节"),
]
# Markdown / HTML 的标题标记
_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
# 以这些标点结尾的一律不是标题
_SENTENCE_END = "。；;.!！?？,，、:："

MIN_CHUNK_CHARS = 40
MAX_CHUNK_CHARS = 900
# 标题最长字符数：超过这个长度的行不可能是标题（是正文）
_MAX_TITLE_CHARS = 40
MERGE_BELOW_CHARS = 150


# --------------------------------------------------------------------------
# 数据结构
# --------------------------------------------------------------------------
@dataclass
class ParsedPage:
    """一个定位单元。

    不同格式对应不同东西，字段名统一但含义随 file_type 变化：
        pdf   → 页（page_num）
        pptx  → 幻灯片（slide_index）
        docx / md / html / epub → 章节或标题块（section_title 记层级）
        txt / csv → 一个分块（行号记在 section_title 里）
    """

    index: int
    text: str = ""
    chapter_title: str = ""
    section_title: str = ""
    char_start: int = 0
    char_end: int = 0
    failed: bool = False
    message: str = ""


@dataclass
class ParsedDocument:
    source_file: str
    file_type: str
    pages: list[ParsedPage] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)     # 格式相关的附加信息（标题、作者等）

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def full_text(self) -> str:
        return "\n".join(p.text for p in self.pages)

    @property
    def text_chars(self) -> int:
        return sum(len(p.text) for p in self.pages)

    @property
    def has_text_layer(self) -> bool:
        """是否有可提取的文字。仅对 PDF 用「每页平均字数」判定；其他格式只要有文字即算。"""
        if not self.pages:
            return False
        if self.file_type != "pdf":
            return self.text_chars > 0
        return self.text_chars / max(len(self.pages), 1) >= SCANNED_CHARS_PER_PAGE


@dataclass
class Chunk:
    """待入库的文本块。chunk_key 格式见编程组分工确认表第三节。"""

    chunk_key: str
    doc_id: int
    seq: int
    chapter_title: str
    section_title: str
    page_num: int | None
    slide_index: int | None
    char_start: int
    char_end: int
    text: str


class ParseError(Exception):
    """文件级解析失败（格式不支持、加密、损坏）。调用方应把任务标为 failed 并展示 message。"""


# --------------------------------------------------------------------------
# 文件类型识别：优先看文件头，不信任扩展名（学生常把 ppt 改名成 pptx）
# --------------------------------------------------------------------------
_ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")

# 这些扩展名按纯文本处理（无文件头特征，只能靠扩展名判断）
_PLAIN_TEXT_EXTENSIONS = {".txt", ".text", ".log", ".rst", ".srt", ".vtt", ".json", ".yaml", ".yml"}


def sniff_format(path: Path, suffix: str) -> str:
    """返回规范化格式名：pdf / pptx / docx / epub / txt / md / html / csv / image / xlsx。

    找不到匹配时返回空字符串 —— **不要兜底成 txt**，否则 .xyz 这类未知文件会被
    当纯文本硬读出一堆乱码，还绕过了「不支持该格式」的提示。
    """
    try:
        with path.open("rb") as fp:
            head = fp.read(8)
    except OSError:
        head = b""

    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        # OLE2 复合文档：.doc/.ppt/.xls 旧格式
        return "ole2"
    if head.startswith(_ZIP_SIGNATURES):
        return _sniff_zip(path, suffix)
    if head.startswith(b"\x89PNG") or head.startswith(b"\xff\xd8") or head[:2] == b"BM":
        return "image"
    if head.startswith(b"RIFF"):
        return "image"          # webp 等
    if head.startswith(b"GIF8"):
        return "image"

    if suffix in {".md", ".markdown"}:
        return "md"
    if suffix in {".html", ".htm"}:
        return "html"
    if suffix == ".csv":
        return "csv"
    if suffix in _PLAIN_TEXT_EXTENSIONS:
        return "txt"
    return ""


def _sniff_zip(path: Path, suffix: str) -> str:
    """ZIP 容器内看目录结构区分 pptx / docx / epub / xlsx。"""
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            if "mimetype" in names:
                try:
                    if zf.read("mimetype").startswith(b"application/epub"):
                        return "epub"
                except (KeyError, OSError):
                    pass
            if any(n.startswith("ppt/") for n in names):
                return "pptx"
            if any(n.startswith("word/") for n in names):
                return "docx"
            if any(n.startswith("xl/") for n in names):
                return "xlsx"
    except (zipfile.BadZipFile, OSError):
        pass
    return suffix.lstrip(".") or "txt"


# --------------------------------------------------------------------------
# 标题识别
# --------------------------------------------------------------------------
def match_heading_pattern(text: str, *, min_len: int = 4, max_len: int = 40) -> str:
    """按编号规律识别标题，返回 'chapter' / 'section' / ''。"""
    t = text.strip()
    if not (min_len <= len(t) <= max_len) or t[-1] in _SENTENCE_END:
        return ""
    for pattern in _CHAPTER_PATTERNS:
        if pattern.match(t):
            return "chapter"
    for pattern in _SECTION_PATTERNS:
        if pattern.match(t):
            return "section"
    return ""


def classify_heading(title: str, *, first_on_page: bool = False,
                     previous_kind: str = "") -> str:
    """判断一个标题是章还是小节：**只认编号规律**。

    刻意不根据字号、位置或「是不是页内第一个」来提拔成章 —— 实测真实课件里
    这些信号会把页码（"2"）、状态机状态名（"Idle"、"Resetting"）、图例符号
    （"III"、"Ø"）判成章，实测有份课件被拆出 42 个假章，笔记结构完全不可用。

    没有章编号的文件，章名由各解析器用「文档级主章」统一兜底。
    """
    return match_heading_pattern(title)


def detect_headings(page: "pymupdf.Page") -> tuple[list[tuple[float, str]], float]:
    """用字号识别 PDF 候选标题。返回 ([(y坐标, 文本)], 正文字号估计值)。"""
    try:
        data = page.get_text("dict")
    except Exception:  # noqa: BLE001 - 极少数 PDF 取 dict 会失败，退化为纯文本
        return [], 0.0

    lines: list[tuple[float, str, float]] = []
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
            if not text:
                continue
            size = max((float(s.get("size", 0)) for s in line.get("spans", [])), default=0.0)
            bold = any("bold" in str(s.get("font", "")).lower() for s in line.get("spans", []))
            lines.append((float(line.get("bbox", (0, 0, 0, 0))[1]), text,
                          size if not bold else size + 0.8))

    if not lines:
        return [], 0.0

    weights: dict[float, int] = {}
    for _, text, size in lines:
        key = round(size, 1)
        weights[key] = weights.get(key, 0) + len(text)
    body_size = max(weights, key=lambda k: weights[k]) if weights else 0.0

    candidates = [
        (y, text) for y, text, size in lines
        if (size >= body_size + 1.2 and len(text) <= 48 and text[-1] not in _SENTENCE_END)
    ]
    return candidates, body_size


# --------------------------------------------------------------------------
# 通用文本清理
# --------------------------------------------------------------------------
def normalize_paragraphs(text: str) -> str:
    """清理解析噪声：合并被硬折行拆开的句子、去掉空行。

    把每一行分成两类：
        complete —— 以句末标点结尾，是完整句子，不并入下一行
        fragment —— 没有结尾标点（硬折行或未写完的句子），并入下一行
    这样「上一行内容」会被下一行的标题「2.1 导数的概念」接上成一段，
    但换行本身仍被保留（换行是段落边界）。
    """
    if not text:
        return ""
    lines = [ln.strip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    lines = [ln for ln in lines if ln]

    paragraphs: list[str] = []
    for line in lines:
        if not paragraphs:
            paragraphs.append(line)
            continue
        prev = paragraphs[-1]
        is_heading = bool(match_heading_pattern(line))
        if _is_complete(prev) or is_heading or (_is_short_fragment(prev) and _is_short_fragment(line)):
            paragraphs.append(line)
        else:
            paragraphs[-1] = prev + line
    return "\n".join(paragraphs).strip()


def _is_complete(line: str) -> bool:
    return bool(line) and line[-1] in _SENTENCE_END


def _is_short_fragment(line: str) -> bool:
    return len(line) <= 4


def _looks_garbled(text: str) -> bool:
    if not text:
        return False
    suspicious = sum(1 for ch in text if ch == "\ufffd" or 0xE000 <= ord(ch) <= 0xF8FF)
    return suspicious / len(text) > GARBLED_REPLACEMENT_RATIO


def _clean_heading_candidates(titles: list[str]) -> list[str]:
    """清洗标题候选：去页码、去纯数字、去超长行、去明显不是标题的行。"""
    out: list[str] = []
    for title in titles:
        t = _strip_trailing_page_number(title.strip())
        if not t or t.isdigit():
            continue
        if len(t) > _MAX_TITLE_CHARS:
            continue
        has_cjk = any("\u4e00" <= c <= "\u9fff" for c in t)
        if not has_cjk and not re.search(r"[A-Za-z]{3,}", t):
            continue
        out.append(t)
    return out


def _strip_trailing_page_number(text: str, *, max_digits: int = 3) -> str:
    """剥掉粘在标题末尾的页码，如「第14章用户界面设计5」→「第14章用户界面设计」。"""
    m = re.search(r"(\d{1,%d})\s*$" % max_digits, text)
    if not m:
        return text
    head = text[:m.start()].rstrip(" 　·-—、.")
    if len(head) < 4 or head.endswith(("第", "章", "节", "讲")):
        return text
    return head


def resolve_chapter(page_headings: dict[int, list[str]], path: Path,
                    *, fallback_title: str = "") -> str:
    """确定整份文档的「章」名（用于没有章编号的资料兜底）。

    优先级：
      ① 出现过的「第X章 / Chapter N」型标题（最可靠）
      ② 前面若干单元里含中文的短行（讲义、按主题组织的课件常见）
      ③ 文档自带标题（如 Word 的 Heading 1、EPUB 的章节名）
      ④ 文件名里的中文部分
      ⑤ 「未命名资料」

    绝不用纯数字：文件名是 1.pdf 时把章名设成「1」，学生在页面上看到会莫名其妙。
    """
    for i in sorted(page_headings):
        for title in page_headings[i]:
            if classify_heading(title) == "chapter":
                return title

    for i in sorted(page_headings)[:3]:
        for title in page_headings[i]:
            if 4 <= len(title) <= 24 and any("\u4e00" <= c <= "\u9fff" for c in title):
                return title

    if fallback_title and len(fallback_title) <= 40:
        return fallback_title

    stem = re.sub(r"[_\-\s]*副本$", "", path.stem).strip()
    chinese = re.findall(r"[\u4e00-\u9fff]{2,}", stem)
    if chinese:
        return max(chinese, key=len)
    return "未命名资料"


def _apply_headings(pages: list[ParsedPage], page_headings: dict[int, list[str]],
                    doc_chapter: str) -> None:
    """统一的第二遍：把标题候选落到各页，并维护跨页的章上下文。"""
    state = {"chapter": doc_chapter, "section": ""}
    for parsed in pages:
        titles = [t for t in page_headings.get(parsed.index, []) if t]
        for title in titles:
            kind = classify_heading(title)
            if kind == "chapter":
                state["chapter"] = title
                state["section"] = ""
            else:
                state["section"] = title
        parsed.chapter_title = state["chapter"]
        if titles:
            parsed.section_title = state["section"]
        elif not parsed.section_title:
            parsed.section_title = state["section"]


# --------------------------------------------------------------------------
# 提取器：PDF
# --------------------------------------------------------------------------
def parse_pdf(path: Path) -> ParsedDocument:
    doc = ParsedDocument(source_file=path.name, file_type="pdf")
    try:
        pdf = pymupdf.open(path)
    except Exception as exc:  # noqa: BLE001
        raise ParseError(f"PDF 无法打开：{exc}") from exc

    try:
        if pdf.needs_pass:
            raise ParseError("PDF 已加密，需要口令；请提供未加密版本或先解除限制")

        offset = 0
        garbled_pages = 0
        page_headings: dict[int, list[str]] = {}

        for i, page in enumerate(pdf, start=1):
            parsed = ParsedPage(index=i)
            try:
                raw = page.get_text("text") or ""
            except Exception as exc:  # noqa: BLE001 - 单页失败不放弃整篇
                parsed.failed = True
                parsed.message = f"第 {i} 页读取失败：{exc}"
                doc.warnings.append(parsed.message)
                raw = ""

            text = normalize_paragraphs(raw)
            parsed.char_start = offset
            parsed.char_end = offset + len(text)
            offset = parsed.char_end + 1

            if text and _looks_garbled(text):
                garbled_pages += 1
                parsed.message = f"第 {i} 页疑似字体缺字或编码异常"
            parsed.text = text

            candidates, _body_size = detect_headings(page)
            titles = [t for _, t in candidates]
            if not titles:
                titles = [ln.strip() for ln in text.split("\n")[:4]
                          if match_heading_pattern(ln.strip())]
            page_headings[i] = _clean_heading_candidates(titles)
            doc.pages.append(parsed)

        _apply_headings(doc.pages, page_headings, resolve_chapter(page_headings, path))

        if garbled_pages:
            doc.warnings.append(
                f"{garbled_pages} 页存在字体缺字/编码异常，提取文本可能不准，建议人工核对")
        return doc
    finally:
        pdf.close()


# --------------------------------------------------------------------------
# 提取器：PPTX
# --------------------------------------------------------------------------
def parse_pptx(path: Path) -> ParsedDocument:
    from pptx import Presentation  # 延迟导入：只有处理 PPTX 时才需要

    doc = ParsedDocument(source_file=path.name, file_type="pptx")
    try:
        prs = Presentation(str(path))
    except Exception as exc:  # noqa: BLE001
        raise ParseError(f"PPTX 无法打开：{exc}（若是 .ppt 旧格式，请先另存为 .pptx）") from exc

    offset = 0
    page_headings: dict[int, list[str]] = {}
    for i, slide in enumerate(prs.slides, start=1):
        parsed = ParsedPage(index=i)
        title = ""
        body_lines: list[str] = []

        for shape in slide.shapes:
            if not getattr(shape, "has_text_frame", False):
                continue
            text = (shape.text_frame.text or "").strip()
            if not text:
                continue
            try:
                is_title = shape == slide.shapes.title or (
                    shape.is_placeholder and shape.placeholder_format.idx == 0)
            except Exception:  # noqa: BLE001 - 部分模板占位符异常
                is_title = False
            if is_title or (not title and len(text) <= 40 and "\n" not in text):
                title = text
            else:
                body_lines.append(text)

        text = normalize_paragraphs("\n".join(body_lines)) or normalize_paragraphs(title)
        parsed.char_start = offset
        parsed.char_end = offset + len(text)
        offset = parsed.char_end + 1
        parsed.text = text
        page_headings[i] = _clean_heading_candidates([title] if title else [])
        if not text:
            parsed.message = f"第 {i} 张幻灯片无可提取文本（可能整页为图片）"
            doc.warnings.append(parsed.message)
        doc.pages.append(parsed)

    _apply_headings(doc.pages, page_headings, resolve_chapter(page_headings, path))

    if not doc.has_text_layer:
        doc.warnings.append("整份 PPT 文本极少，可能为图文混排或图片版，建议人工核对")
    return doc


# --------------------------------------------------------------------------
# 提取器：DOCX
# --------------------------------------------------------------------------
def parse_docx(path: Path) -> ParsedDocument:
    from docx import Document as DocxDocument
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = ParsedDocument(source_file=path.name, file_type="docx")
    try:
        wd = DocxDocument(str(path))
    except Exception as exc:  # noqa: BLE001
        raise ParseError(f"Word 文档无法打开：{exc}（若是 .doc 旧格式，请另存为 .docx）") from exc

    core = getattr(wd, "core_properties", None)
    if core is not None and getattr(core, "title", ""):
        doc.meta["title"] = str(core.title).strip()

    # 按文档顺序遍历：段落与表格混排时不能分开处理，否则内容顺序会乱
    blocks: list[tuple[str, str]] = []       # (kind, text)；kind = heading/body/table
    try:
        body = wd.element.body
        for child in body.iterchildren():
            tag = child.tag.split("}")[-1]
            if tag == "p":
                para = Paragraph(child, wd)
                text = (para.text or "").strip()
                if not text:
                    continue
                style = (para.style.name if para.style is not None else "") or ""
                is_heading = style.lower().startswith(("heading", "标题", "title")) or \
                    match_heading_pattern(text) != ""
                blocks.append(("heading" if is_heading else "body", text))
            elif tag == "tbl":
                table = Table(child, wd)
                rows = []
                for row in table.rows:
                    cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                    if any(cells):
                        rows.append(" | ".join(cells))
                if rows:
                    blocks.append(("table", "\n".join(rows)))
    except Exception as exc:  # noqa: BLE001 - 结构异常时退化为只读段落
        doc.warnings.append(f"文档结构遍历异常，已退化为逐段读取：{exc}")
        blocks = [("body", p.text.strip()) for p in wd.paragraphs if p.text.strip()]

    if not blocks:
        raise ParseError("Word 文档里没有可提取的文字内容")

    # 每个「标题 + 其下正文」组成一个定位单元
    offset = 0
    page_headings: dict[int, list[str]] = {}
    index = 0
    buffer: list[str] = []
    buffer_title = ""

    def flush() -> None:
        nonlocal index, buffer, buffer_title, offset
        if not buffer and not buffer_title:
            return
        index += 1
        text = normalize_paragraphs("\n".join(buffer))
        parsed = ParsedPage(index=index, text=text)
        parsed.char_start = offset
        parsed.char_end = offset + len(text)
        offset = parsed.char_end + 1
        if buffer_title:
            page_headings[index] = _clean_heading_candidates([buffer_title])
        doc.pages.append(parsed)
        buffer = []

    for kind, text in blocks:
        if kind == "heading":
            flush()
            buffer_title = text
            buffer.append(text)
        else:
            buffer.append(text)
    flush()

    _apply_headings(doc.pages, page_headings,
                    resolve_chapter(page_headings, path, fallback_title=doc.meta.get("title", "")))
    doc.meta["blocks"] = len(blocks)
    return doc


# --------------------------------------------------------------------------
# 提取器：纯文本 / Markdown / CSV / HTML / EPUB
# --------------------------------------------------------------------------
_TEXT_ENCODINGS = ("utf-8", "utf-8-sig", "gb18030", "big5", "utf-16", "latin-1")


def _read_text(path: Path) -> tuple[str, str | None]:
    """按常见中文编码依次尝试读取，返回 (文本, 告警)。"""
    raw = path.read_bytes()
    for enc in _TEXT_ENCODINGS:
        try:
            text = raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        warn = None
        if enc in {"gb18030", "big5"}:
            warn = f"文件不是 UTF-8 编码，已按 {enc} 读取；如有乱码请另存为 UTF-8"
        return text, warn
    # 最后兜底：忽略无法解码的字节
    return raw.decode("utf-8", errors="replace"), "文件编码无法识别，部分字符已替换"


def parse_text(path: Path) -> ParsedDocument:
    doc = ParsedDocument(source_file=path.name, file_type="txt")
    text, warn = _read_text(path)
    if warn:
        doc.warnings.append(warn)
    if not text.strip():
        raise ParseError("文本文件是空的")

    # 用空行分段；单段过长时交给后面的切块逻辑再切
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        paragraphs = [text.strip()]

    offset = 0
    page_headings: dict[int, list[str]] = {}
    for i, para in enumerate(paragraphs, start=1):
        parsed = ParsedPage(index=i, text=para)
        parsed.char_start = offset
        parsed.char_end = offset + len(para)
        offset = parsed.char_end + 1
        page_headings[i] = _clean_heading_candidates([para.split("\n")[0].strip()])
        doc.pages.append(parsed)

    _apply_headings(doc.pages, page_headings, resolve_chapter(page_headings, path))
    return doc


def parse_markdown(path: Path) -> ParsedDocument:
    doc = ParsedDocument(source_file=path.name, file_type="md")
    text, warn = _read_text(path)
    if warn:
        doc.warnings.append(warn)
    if not text.strip():
        raise ParseError("Markdown 文件是空的")

    # 去掉代码块内容里的 # 干扰：把围栏内容当作普通正文
    lines = text.replace("\r\n", "\n").split("\n")
    offset = 0
    index = 0
    page_headings: dict[int, list[str]] = {}
    buffer: list[str] = []
    title = ""

    def flush() -> None:
        nonlocal index, buffer, title, offset
        if not buffer and not title:
            return
        index += 1
        body = normalize_paragraphs("\n".join(buffer))
        parsed = ParsedPage(index=index, text=body)
        parsed.char_start = offset
        parsed.char_end = offset + len(body)
        offset = parsed.char_end + 1
        if title:
            page_headings[index] = _clean_heading_candidates([title])
        doc.pages.append(parsed)
        buffer = []

    for line in lines:
        m = _MD_HEADING.match(line.strip())
        if m:
            flush()
            title = m.group(2).strip()
            buffer.append(title)          # 标题本身也进正文，保证引用可回查
        else:
            buffer.append(line)
    flush()

    if not doc.pages:
        raise ParseError("Markdown 文件没有可提取的内容")
    _apply_headings(doc.pages, page_headings, resolve_chapter(page_headings, path))
    return doc


def parse_csv(path: Path) -> ParsedDocument:
    doc = ParsedDocument(source_file=path.name, file_type="csv")
    text, warn = _read_text(path)
    if warn:
        doc.warnings.append(warn)

    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel

    rows = list(csv.reader(io.StringIO(text), dialect))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        raise ParseError("CSV 文件没有数据行")

    header = [c.strip() for c in rows[0]]
    # 每行转成「列名: 值」的文本，便于检索与问答
    offset = 0
    page_headings: dict[int, list[str]] = {}
    for i, row in enumerate(rows[1:] or rows, start=1):
        pairs = []
        for j, cell in enumerate(row):
            cell = cell.strip()
            if not cell:
                continue
            name = header[j] if j < len(header) and header[j] else f"第{j + 1}列"
            pairs.append(f"{name}: {cell}")
        body = "；".join(pairs) or " | ".join(row)
        parsed = ParsedPage(index=i, text=body)
        parsed.char_start = offset
        parsed.char_end = offset + len(body)
        offset = parsed.char_end + 1
        parsed.section_title = f"第 {i + 1} 行"
        page_headings[i] = [f"第 {i + 1} 行"]
        doc.pages.append(parsed)

    doc.meta["columns"] = header
    _apply_headings(doc.pages, page_headings, resolve_chapter(page_headings, path))
    for p in doc.pages:      # CSV 的行号比自动识别的章节更有意义，强制保留
        p.section_title = p.section_title or f"第 {p.index + 1} 行"
    return doc


def parse_html(path: Path, *, file_type: str = "html") -> ParsedDocument:
    from html.parser import HTMLParser

    class _Extractor(HTMLParser):
        """只取可见文本与 h1-h6 层级，丢弃 script/style。"""

        SKIP = {"script", "style", "noscript", "head"}

        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.units: list[tuple[str, str]] = []   # (kind, text)
            self._skip_depth = 0
            self._heading_level = 0
            self._buffer: list[str] = []

        def handle_starttag(self, tag, attrs):  # noqa: D102
            if tag in self.SKIP:
                self._skip_depth += 1
            elif re.fullmatch(r"h[1-6]", tag):
                self._flush()
                self._heading_level = int(tag[1])
            elif tag in {"p", "br", "li", "div", "tr", "table"}:
                self._flush()

        def handle_endtag(self, tag):  # noqa: D102
            if tag in self.SKIP and self._skip_depth:
                self._skip_depth -= 1
            elif re.fullmatch(r"h[1-6]", tag):
                self._flush()
                self._heading_level = 0
            elif tag in {"p", "li", "div", "tr"}:
                self._flush()

        def handle_data(self, data):  # noqa: D102
            if self._skip_depth:
                return
            text = data.strip()
            if text:
                self._buffer.append(text)

        def _flush(self) -> None:
            if not self._buffer:
                return
            text = " ".join(self._buffer).strip()
            self._buffer = []
            if text:
                kind = "heading" if self._heading_level else "body"
                self.units.append((kind, text))

        def close(self) -> None:  # noqa: D102
            self._flush()
            super().close()

    text, warn = _read_text(path)
    if warn:
        doc.warnings.append(warn)

    parser = _Extractor()
    try:
        parser.feed(text)
        parser.close()
    except Exception as exc:  # noqa: BLE001
        raise ParseError(f"HTML 解析失败：{exc}") from exc

    if not parser.units:
        raise ParseError("HTML 文件里没有可提取的正文")

    doc = ParsedDocument(source_file=path.name, file_type=file_type)
    offset = 0
    index = 0
    page_headings: dict[int, list[str]] = {}
    buffer: list[str] = []
    title = ""

    def flush() -> None:
        nonlocal index, buffer, title, offset
        if not buffer and not title:
            return
        index += 1
        body = normalize_paragraphs("\n".join(buffer))
        parsed = ParsedPage(index=index, text=body)
        parsed.char_start = offset
        parsed.char_end = offset + len(body)
        offset = parsed.char_end + 1
        if title:
            page_headings[index] = _clean_heading_candidates([title])
        doc.pages.append(parsed)
        buffer = []

    for kind, value in parser.units:
        if kind == "heading":
            flush()
            title = value
            buffer.append(value)
        else:
            buffer.append(value)
    flush()

    _apply_headings(doc.pages, page_headings, resolve_chapter(page_headings, path))
    return doc


def parse_epub(path: Path) -> ParsedDocument:
    """EPUB 本质是 zip + xhtml，用标准库解压后复用 HTML 提取逻辑。"""
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise ParseError(f"EPUB 文件损坏：{exc}") from exc

    with zf:
        names = zf.namelist()
        # 按 spine 顺序取内容文档；取不到就退化为按文件名排序的所有 xhtml/html
        content_names: list[str] = []
        try:
            container = zf.read("META-INF/container.xml").decode("utf-8", "replace")
            m = re.search(r'full-path="([^"]+\.opf)"', container)
            if m:
                opf = zf.read(m.group(1)).decode("utf-8", "replace")
                base = m.group(1).rsplit("/", 1)[0] if "/" in m.group(1) else ""
                items = dict(re.findall(r'<item[^>]*id="([^"]+)"[^>]*href="([^"]+)"', opf))
                order = re.findall(r'<itemref[^>]*idref="([^"]+)"', opf)
                for idref in order:
                    href = items.get(idref)
                    if href:
                        content_names.append(f"{base}/{href}" if base else href)
        except (KeyError, OSError):
            pass

        if not content_names:
            content_names = sorted(n for n in names
                                   if n.lower().endswith((".xhtml", ".html", ".htm")))

        if not content_names:
            raise ParseError("EPUB 里没有找到正文内容")

        doc = ParsedDocument(source_file=path.name, file_type="epub")
        offset = 0
        index = 0
        page_headings: dict[int, list[str]] = {}
        for name in content_names:
            try:
                html = zf.read(name).decode("utf-8", "replace")
            except (KeyError, OSError):
                continue
            tmp = path.parent / f".__epub_tmp_{index}.html"
            try:
                tmp.write_text(html, encoding="utf-8")
                sub = parse_html(tmp, file_type="epub")
            finally:
                tmp.unlink(missing_ok=True)

            for page in sub.pages:
                index += 1
                text = normalize_paragraphs(page.text)
                if not text:
                    continue
                parsed = ParsedPage(index=index, text=text,
                                    section_title=page.section_title or name.rsplit("/", 1)[-1])
                parsed.char_start = offset
                parsed.char_end = offset + len(text)
                offset = parsed.char_end + 1
                page_headings[index] = _clean_heading_candidates([parsed.section_title])
                doc.pages.append(parsed)

        if not doc.pages:
            raise ParseError("EPUB 里没有可提取的文字")
        _apply_headings(doc.pages, page_headings, resolve_chapter(page_headings, path))
        doc.meta["chapters_in_epub"] = len(content_names)
        return doc


# --------------------------------------------------------------------------
# 提取器：图片（需要 OCR）
# --------------------------------------------------------------------------
def parse_image(path: Path) -> ParsedDocument:
    """图片：需要 OCR 才能读字。

    未配置 OCR 时抛出可操作的错误，而不是返回空文档假装成功。
    """
    from app.services.ocr import ocr_available, image_to_text

    if not ocr_available():
        raise ParseError(
            "图片需要 OCR 才能识别文字，当前未配置 OCR 服务。"
            "可在 .env 中配置 OCR_ACCESS_KEY / OCR_ACCESS_SECRET（阿里云文字识别，"
            "每月有免费额度）后重试；或先把图片内容整理成 Word/PDF 再上传")

    text = image_to_text(path)
    if not text.strip():
        raise ParseError("图片里没有识别出文字，可能是不含文字的照片或插图")

    doc = ParsedDocument(source_file=path.name, file_type="image")
    parsed = ParsedPage(index=1, text=normalize_paragraphs(text))
    parsed.char_end = len(parsed.text)
    doc.pages.append(parsed)
    _apply_headings(doc.pages, {1: []}, resolve_chapter({1: []}, path))
    doc.meta["ocr"] = True
    return doc


# --------------------------------------------------------------------------
# 提取器注册表
# --------------------------------------------------------------------------
_EXTRACTORS: dict[str, Callable[[Path], ParsedDocument]] = {
    "pdf": parse_pdf,
    "pptx": parse_pptx,
    "docx": parse_docx,
    "txt": parse_text,
    "md": parse_markdown,
    "csv": parse_csv,
    "html": parse_html,
    "epub": parse_epub,
    "image": parse_image,
}


def register_extractor(name: str, func: Callable[[Path], ParsedDocument]) -> None:
    """扩展点：注册新的格式提取器。加格式不需要改本模块之外任何代码。"""
    _EXTRACTORS[name] = func


def supported_formats() -> list[str]:
    return sorted(SUPPORTED_EXTENSIONS)


# --------------------------------------------------------------------------
# 统一入口
# --------------------------------------------------------------------------
def parse_file(path: str | Path, *, course_name: str = "", ocr: bool = False) -> ParsedDocument:
    """解析任意支持格式的学习资料。解析失败抛 ParseError（含可展示的原因）。"""
    p = Path(path)
    if not p.exists():
        raise ParseError(f"文件不存在：{p}")
    if p.stat().st_size == 0:
        raise ParseError("文件为空")

    suffix = p.suffix.lower()
    if suffix in LEGACY_EXTENSIONS:
        raise ParseError(f"{suffix} 是{suffix.lstrip('.').upper()} 旧格式：{LEGACY_EXTENSIONS[suffix]}")
    if suffix in UNSUPPORTED_HINTS:
        raise ParseError(UNSUPPORTED_HINTS[suffix])

    fmt = sniff_format(p, suffix)
    if fmt == "ole2":
        raise ParseError("这是 Office 旧格式（.doc/.ppt/.xls），请用新版 Office 另存为 "
                         ".docx / .pptx 后再上传")
    if fmt == "xlsx":
        raise ParseError("Excel 表格暂未支持，可在 Excel 中另存为 .csv 后上传")

    extractor = _EXTRACTORS.get(fmt)
    if extractor is None:
        raise ParseError(
            f"暂不支持 {suffix or '该'} 格式。当前支持："
            f"{'、'.join(sorted(SUPPORTED_EXTENSIONS))}")

    doc = extractor(p)
    if not doc.pages:
        raise ParseError("文件里没有可解析的内容")

    # 扫描件判定：只对 PDF 有意义（其他格式不存在「图片页」概念）
    if fmt == "pdf" and not doc.has_text_layer:
        per_page = doc.text_chars // max(doc.page_count, 1)
        if ocr:
            doc.warnings.append("已启用 OCR，但该 PDF 的文本层仍为空，请检查 OCR 配置")
        else:
            doc.warnings.append(
                f"该 PDF 平均每页仅 {per_page} 个字符，疑似扫描件（整页为图片）。"
                "当前未启用 OCR，只能提取到极少内容；"
                "可在 .env 中配置 OCR_ACCESS_KEY / OCR_ACCESS_SECRET 后重新上传以识别图片文字")
    return doc


# --------------------------------------------------------------------------
# 切块
# --------------------------------------------------------------------------
def split_text(text: str, *, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """按段落/句子边界切分，尽量不切断句子。"""
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    pieces: list[str] = []
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            continue
        if len(para) <= max_chars:
            pieces.append(para)
            continue
        buf = ""
        for seg in re.split(r"(?<=[。；！？!?；])", para):
            if not seg:
                continue
            if len(buf) + len(seg) <= max_chars:
                buf += seg
            else:
                if buf:
                    pieces.append(buf)
                while len(seg) > max_chars:
                    pieces.append(seg[:max_chars])
                    seg = seg[max_chars:]
                buf = seg
        if buf:
            pieces.append(buf)

    merged: list[str] = []
    for piece in pieces:
        if merged and len(piece) < MERGE_BELOW_CHARS and len(merged[-1]) + len(piece) <= max_chars:
            merged[-1] = merged[-1] + piece
        else:
            merged.append(piece)
    return [m for m in merged if len(m) >= MIN_CHUNK_CHARS] or [text[:max_chars]]


def build_chunks(doc: ParsedDocument, doc_id: int, *, max_chars: int = MAX_CHUNK_CHARS) -> list[Chunk]:
    """把解析结果切成待入库的 chunk 列表。

    chunk_key 格式：d<doc_id>-p<页码或单元号>-c<序号>
    页码与幻灯片序号分别写入 page_num / slide_index，宁可留空也不张冠李戴。
    """
    chunks: list[Chunk] = []
    seq = 0
    for page in doc.pages:
        for idx, piece in enumerate(split_text(page.text, max_chars=max_chars), start=1):
            seq += 1
            chunks.append(Chunk(
                chunk_key=f"d{doc_id}-p{page.index}-c{idx}",
                doc_id=doc_id,
                seq=seq,
                chapter_title=page.chapter_title,
                section_title=page.section_title,
                page_num=page.index if doc.file_type == "pdf" else None,
                slide_index=page.index if doc.file_type == "pptx" else None,
                char_start=page.char_start,
                char_end=page.char_end,
                text=piece,
            ))
    return chunks
