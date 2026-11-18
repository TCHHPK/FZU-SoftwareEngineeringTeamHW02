"""端到端连通性自检：生成真实 PDF → 解析 → 建索引 → 检索 → 出处核对。

不上 LLM，不需要 API key。用于每天 21:00 集成后确认主链路没坏。
运行：python scripts/selftest_pipeline.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("STORAGE_DIR", tempfile.mkdtemp(prefix="cna-selftest-"))

import pymupdf  # noqa: E402

from app.db.conn import business_db, init_databases  # noqa: E402
from app.services.query import index_chunks, quote_in_text, search_chunks  # noqa: E402

PAGES: list[tuple[str, str]] = [
    ("第2章 导数与微分",
     "2.1 导数的概念\n函数 y=f(x) 在点 x0 处的导数，记作 f'(x0)，描述函数在该点附近的变化率。\n"
     "几何意义：曲线在点 (x0, f(x0)) 处切线的斜率。\n"
     "左导数与右导数都存在且相等，是 f(x) 在 x0 处可导的充分必要条件。"),
    ("2.1 导数的概念",
     "可导必连续，连续不一定可导。例如 y=|x| 在 x=0 处连续但不可导。"),
    ("2.2 求导法则",
     "四则运算求导法则：和的导数等于导数的和；积的导数 (uv)'=u'v+uv'；"
     "商的导数 (u/v)'=(u'v-uv')/v^2。\n复合函数求导遵循链式法则。"),
    ("2.3 高阶导数",
     "二阶导数 f''(x) 表示一阶导数的导数，可用来判断函数的凹凸性。"),
    ("第3章 微分中值定理",
     "罗尔定理、拉格朗日中值定理与柯西中值定理是微分学的理论基础。"),
]

QUERIES = [
    ("导数的几何意义是什么", 1),
    ("可导和连续是什么关系", 2),
    ("复合函数怎么求导", 3),
    ("罗尔定理", 5),
]


def make_pdf() -> bytes:
    """生成一份带文本层的测试课件（模拟老师给的 PDF）。"""
    doc = pymupdf.open()
    for title, body in PAGES:
        page = doc.new_page()
        page.insert_text((60, 80), title, fontsize=16, fontname="china-s")
        page.insert_textbox(pymupdf.Rect(60, 110, 520, 760), body, fontsize=12, fontname="china-s")
    data = doc.tobytes()
    doc.close()
    return data


def main() -> int:
    failures = 0
    pdf = make_pdf()
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    texts = [p.get_text().strip() for p in doc]
    doc.close()
    print(f"[1/4] 生成并解析 PDF：{len(pdf)} 字节，{len(texts)} 页")
    if len(texts) != len(PAGES):
        print("      !! 页数与预期不符"); failures += 1
    if "导数" not in texts[0]:
        print("      !! 第 1 页未提取到中文（字体/文本层问题）"); failures += 1

    init_databases(reset=True)
    with business_db() as conn:
        conn.execute("INSERT INTO users (username,password_hash,nickname) VALUES ('tester','x','测试')")
        uid = conn.execute("SELECT user_id FROM users").fetchone()["user_id"]
        cur = conn.execute(
            """INSERT INTO documents (user_id, course_name, source_file, stored_path,
                                      file_type, page_count, text_chars, parse_status)
               VALUES (?, '高等数学（上）', 'gaoshu-ch2.pdf', 'storage/x.pdf', 'pdf', ?, ?, 'success')""",
            (uid, len(texts), sum(len(t) for t in texts)))
        doc_id = cur.lastrowid

        rows = []
        for i, text in enumerate(texts):
            key = f"d{doc_id}-p{i + 1}-c1"
            rows.append({"chunk_key": key, "doc_id": doc_id, "text": text})
            conn.execute(
                """INSERT INTO chunks (chunk_key, doc_id, seq, chapter_title, page_num,
                                       char_start, char_end, text)
                   VALUES (?, ?, ?, ?, ?, 0, ?, ?)""",
                (key, doc_id, i + 1, PAGES[i][0], i + 1, len(text), text))
        index_chunks(conn, rows)
        print(f"[2/4] 入库并建索引：doc_id={doc_id}，{len(rows)} 个 chunk")

        print("[3/4] 检索召回：" + "-" * 40)
        for question, expect_page in QUERIES:
            found = search_chunks(conn, question, doc_ids=[doc_id], top_k=2)
            if not found.confident:
                print(f"      Q: {question} -> 无可信召回（应为 p{expect_page}）"); failures += 1
                continue
            top = found.confident[0]
            got = top["page_num"]
            flag = "OK " if got == expect_page else "!! "
            if got != expect_page:
                failures += 1
            print(f"      {flag}Q: {question:14s} -> p{got}（期望 p{expect_page}）"
                  f" {top['chunk_key']} relevance={top['relevance']:.2f}"
                  f" coverage={top['coverage']:.2f}")

        # 无关问题不应有任何召回（防止编造材料外内容）
        noise = search_chunks(conn, "红烧肉怎么做才好吃", doc_ids=[doc_id], top_k=3)
        if not noise.empty:
            print(f"      !! 无关问题产生了 {len(noise.hits)} 条召回，需检查阈值"); failures += 1
        else:
            print("      OK 无关问题无召回（可回答「材料未涉及」）")

        print("[4/4] 出处核对（证据校验用）：" + "-" * 30)
        real = search_chunks(conn, "切线", doc_ids=[doc_id], top_k=1).confident[0]["text"]
        cases = [
            ("几何意义：曲线在点 (x0, f(x0)) 处切线的斜率", True, "原文连续片段"),
            ("几何意义, 曲线在点(x0,f(x0))处切线的斜率", True, "仅标点被改写"),
            ("导数就是函数的积分", False, "编造内容"),
            ("几何意义是切线的斜率", False, "同义改写（要求模型抄原文）"),
            ("导数", False, "过短引文无证据效力"),
        ]
        for quote, expect, why in cases:
            ok = quote_in_text(quote, real)
            flag = "OK " if ok == expect else "!! "
            if ok != expect:
                failures += 1
            print(f"      {flag}{'通过' if ok else '拦截'}（{why}）：{quote[:26]}")

    print("-" * 60)
    print("主链路自检通过" if failures == 0 else f"主链路有 {failures} 处异常，需修")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
