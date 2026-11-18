"""中文友好的全文检索：把文本和查询都转成 2-gram，交给 SQLite FTS5，再用本地覆盖率重排。

为什么不用向量库：
    单门课程的课件规模（约 200~800 个 chunk）下，BM25 + 2-gram 足够，
    而且省掉一个需要运维、需要在答辩里解释的组件。向量召回保留为可选开关
    （settings.enable_vector），不阻塞主线。

为什么需要「重排」：
    FTS5 的 OR 查询只保证「命中任一二元组」，所以「量子力学的不确定性原理」会因
    命中「力学」而错误召回导数章节。因此在 FTS 召回之后必须用二元组覆盖率重排，
    并设最低阈值，让无关问题返回空 —— 这是「材料未涉及就如实回答」的技术前提。
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

# 只保留中文、字母、数字；其余（标点/公式符号/空白）视作分隔符
_KEEP = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]+")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_LATIN_WORD = re.compile(r"[A-Za-z0-9]+")

# 判定「相关」的最低二元组覆盖率；低于该值视为材料未涉及
MIN_COVERAGE = 0.25
# FTS 粗召回倍数：先取 top_k * CANDIDATE_FACTOR 条，再重排取前 top_k
CANDIDATE_FACTOR = 8
# 覆盖率低于该值：仍返回结果，但标记为低置信，问答侧应提示「材料依据不足」
LOW_CONFIDENCE = 0.40

# 中文疑问词/语气词：它们会稀释二元组覆盖率，必须在检索前剔除。
# 例："可导和连续是什么关系" 剔除后只剩「可导」「连续」，覆盖率从 0.30 升到 0.75。
_QUESTION_FILLER = re.compile(
    r"(请|帮我|麻烦|我想|想要|问一下|解释一下|说明一下|讲解|分析|告诉我|是什么|什么是|"
    r"为什么|怎么|如何|怎样面对|哪些|哪个|多少|是否|有没有|能否|可以|关系|区别|联系|"
    r"核心要求|要求|强调|软件实体|"
    r"和|与|跟|的|了|吗|呢|吧|啊|呀|什么|一下|一个|这个|那个)"
)


def extract_query_terms(text: str) -> list[str]:
    """提取检索用的实词单元：先切掉疑问词，再切掉单字虚词，保序去重。

    不要在这里做分词——只做「去噪音」，剩下的交给 2-gram。
    """
    stripped = _QUESTION_FILLER.sub(" ", normalize_text(text))
    terms: list[str] = []
    for chunk in stripped.split():
        if len(chunk) <= 1:
            continue
        # 开头/结尾的单字虚词也去掉，如「的导数」「导数啊」
        chunk = re.sub(r"^[的了在和与跟对把被为是]+", "", chunk)
        chunk = re.sub(r"[的了在和与跟对把被为是吗呢吧啊呀]+$", "", chunk)
        if len(chunk) > 1:
            terms.append(chunk)
    seen: set[str] = set()
    return [t for t in terms if not (t in seen or seen.add(t))]



def normalize_text(text: str) -> str:
    """归一化：全角转半角、去多余空白、统一小写。校验 quote 时也用它。"""
    if not text:
        return ""
    out = []
    for ch in text:
        code = ord(ch)
        if code == 0x3000:  # 全角空格
            ch = " "
        elif 0xFF01 <= code <= 0xFF5E:  # 全角 ASCII
            ch = chr(code - 0xFEE0)
        out.append(ch)
    return re.sub(r"\s+", " ", "".join(out)).strip().lower()


def _squash(text: str) -> str:
    """去掉一切非中英文数字字符，只留连续串（用于引文核验的宽松比较）。"""
    return "".join(_KEEP.findall(normalize_text(text)))


def to_bigram(text: str) -> str:
    """把文本转成 2-gram 串，写入/查询 FTS5 的 text_bigram 列。

    例："函数的极限" -> "函数 数的 的极 极限"
    英文与数字保持整词，避免 "limit" 被切碎。

    注意：入库（chunk 正文）时要传原文，不要传用户问题——问题请先走 extract_query_terms。
    """
    s = normalize_text(text)
    if not s:
        return ""
    grams: list[str] = []
    for run in _CJK_RUN.findall(s):
        if len(run) == 1:
            grams.append(run)
        else:
            grams.extend(run[i:i + 2] for i in range(len(run) - 1))
    grams.extend(_LATIN_WORD.findall(s))
    seen: set[str] = set()
    return " ".join(g for g in grams if not (g in seen or seen.add(g)))


def query_bigrams(query: str) -> set[str]:
    """把用户问题变成检索用二元组集合（先去疑问词）。"""
    grams: set[str] = set()
    for term in extract_query_terms(query):
        grams.update(to_bigram(term).split())
    return grams


def build_fts_query(query: str, *, mode: str = "or") -> str:
    """把用户问题变成 FTS5 查询串。

    or  : 任一二元组命中（粗召回，默认，随后由覆盖率重排）
    and : 全部命中（精确优先）
    每个 term 用双引号包成短语，避免 FTS5 把 2-gram 当语法解析。
    """
    grams = sorted(query_bigrams(query))
    if not grams:
        return ""
    if mode == "and":
        return " AND ".join(f'"{g}"' for g in grams)
    return " OR ".join(f'"{g}"' for g in grams)


# --------------------------------------------------------------------------
# 重排打分
# --------------------------------------------------------------------------
def _gram_hits(query_grams: set[str], model_grams: set[str]) -> float:
    """查询相对该片段的覆盖率：0~1，1 表示查询的每个二元组都出现在片段里。"""
    if not query_grams:
        return 0.0
    return len(query_grams & model_grams) / len(query_grams)


def rerank(
    rows: list[dict],
    query: str,
    *,
    top_k: int = 8,
    min_coverage: float = MIN_COVERAGE,
) -> list[dict]:
    """按二元组覆盖率 + 片段被解释程度重排，并过滤掉覆盖率过低的候选。

    打分：0.7 * 覆盖率 + 0.3 * 片段方向覆盖率，
    避免「超长片段恰好包含少量查询词」压过「短而精准」的片段。
    覆盖率低于 LOW_CONFIDENCE 的结果会带 low_confidence=True，供问答侧提示依据不足。
    """
    q_grams = query_bigrams(query)
    if not q_grams:
        return []
    scored: list[dict] = []
    for row in rows:
        m_grams = set(to_bigram(row.get("text", "")).split())
        cov_q = _gram_hits(q_grams, m_grams)          # 查询被覆盖多少
        cov_c = _gram_hits(m_grams, q_grams) if m_grams else 0.0  # 片段被解释多少
        if cov_q < min_coverage:
            continue
        row = dict(row)
        row["coverage"] = round(cov_q, 3)
        row["relevance"] = round(0.7 * cov_q + 0.3 * cov_c, 3)
        row["low_confidence"] = cov_q < LOW_CONFIDENCE
        scored.append(row)
    scored.sort(key=lambda r: (r["relevance"], r["coverage"]), reverse=True)
    return scored[:top_k]


def index_chunks(conn: sqlite3.Connection, rows: list[dict]) -> None:
    """把 chunk 写入 FTS5 索引。rows: [{chunk_key, doc_id, text}, ...]"""
    if not rows:
        return
    conn.executemany(
        "INSERT INTO ft_chunks (chunk_key, doc_id, text_bigram, text_raw) VALUES (?, ?, ?, ?)",
        [
            (r["chunk_key"], str(r["doc_id"]), to_bigram(r["text"]), normalize_text(r["text"]))
            for r in rows
        ],
    )


@dataclass
class SearchResult:
    """检索结果：把「有材料依据」与「依据不足」在类型上分开。

    调用方据此决定回答策略，不需要自己去猜覆盖率阈值：
      ① confident 为空            → 材料未涉及，如实说明
      ② confident 为空但 low 非空 → 材料依据不足，建议换问法
      ③ confident 非空            → 可以据此作答（必须引用 evidence）
    """

    confident: list[dict] = field(default_factory=list)
    low_confidence: list[dict] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.confident and not self.low_confidence

    @property
    def hits(self) -> list[dict]:
        return self.confident + self.low_confidence

    @property
    def insufficient(self) -> bool:
        return not self.confident


def search_chunks(
    conn: sqlite3.Connection,
    query: str,
    *,
    doc_ids: list[int] | None = None,
    course_name: str | None = None,
    top_k: int = 8,
    mode: str = "or",
    min_coverage: float = MIN_COVERAGE,
    per_bucket: int | None = None,
) -> SearchResult:
    """检索证据片段。

    两段式：先按课程/文档做元数据过滤与 FTS 粗召回，再本地重排过滤。
    返回按「可信 / 低置信」分桶的结果，对应设计文档 1.6 节的检索方案。
    """
    fts_q = build_fts_query(query, mode=mode)
    if not fts_q:
        return SearchResult()

    limit = max(top_k * CANDIDATE_FACTOR, 20)
    sql = """
        SELECT c.chunk_key, c.doc_id, c.text, c.chapter_title, c.section_title,
               c.page_num, c.slide_index, d.source_file,
               bm25(ft_chunks, 1.0, 0.3) AS bm25_score
        FROM ft_chunks
        JOIN chunks c ON c.chunk_key = ft_chunks.chunk_key
        JOIN documents d ON d.doc_id = c.doc_id
        WHERE ft_chunks MATCH ?
    """
    params: list = [fts_q]
    if doc_ids:
        sql += f" AND c.doc_id IN ({','.join('?' * len(doc_ids))})"
        params.extend(doc_ids)
    if course_name:
        sql += " AND d.course_name = ?"
        params.append(course_name)
    sql += " ORDER BY bm25_score LIMIT ?"
    params.append(limit)

    try:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    except sqlite3.OperationalError as exc:  # FTS 语法异常时降级为关键词 LIKE
        if "fts5" not in str(exc).lower() and "syntax" not in str(exc).lower():
            raise
        rows = _fallback_like(conn, query, doc_ids=doc_ids, limit=limit)

    scored = rerank(rows, query, top_k=top_k, min_coverage=min_coverage)
    confident = [r for r in scored if not r["low_confidence"]]
    low = [r for r in scored if r["low_confidence"]]
    if per_bucket:
        confident, low = confident[:per_bucket], low[:per_bucket]
    return SearchResult(confident=confident, low_confidence=low)


def search_chunk_list(conn: sqlite3.Connection, query: str, **kwargs) -> list[dict]:
    """只要一个平铺列表时的便捷入口（后台脚本、旧调用方用）。"""
    return search_chunks(conn, query, **kwargs).hits


def _fallback_like(
    conn: sqlite3.Connection,
    query: str,
    *,
    doc_ids: list[int] | None,
    limit: int,
) -> list[dict]:
    """FTS 不可用时的兜底：按关键词 LIKE 粗召回，重排逻辑不变。"""
    words = [w for w in _KEEP.findall(normalize_text(query)) if len(w) >= 2][:6]
    if not words:
        return []
    where = " OR ".join(["c.text LIKE ?"] * len(words))
    params: list = [f"%{w}%" for w in words]
    sql = f"""
        SELECT c.chunk_key, c.doc_id, c.text, c.chapter_title, c.section_title,
               c.page_num, c.slide_index, d.source_file, 0.0 AS bm25_score
        FROM chunks c JOIN documents d ON d.doc_id = c.doc_id
        WHERE {where}
    """
    if doc_ids:
        sql += f" AND c.doc_id IN ({','.join('?' * len(doc_ids))})"
        params.extend(doc_ids)
    sql += " LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def quote_in_text(quote: str, text: str, *, min_len: int = 5) -> bool:
    """证据校验用：模型给的引文能否在原文中找到。

    三级宽松度，逐级降级（原则：宁可拦截编造，也不放过被改写的引文）：
      ① 归一化后直接子串匹配
      ② 去掉全部标点/公式符号后匹配（容忍模型改写标点）
      ③ 过短引文（< min_len 字）不具备证据效力，直接返回 False，
         防止「导数」这类两字词蒙混过关
    """
    q = normalize_text(quote)
    t = normalize_text(text)
    if len(q) < min_len or not t:
        return False
    if q in t:
        return True
    return _squash(q) in _squash(t)
