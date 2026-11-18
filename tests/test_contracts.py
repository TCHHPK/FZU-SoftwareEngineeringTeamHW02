"""契约冒烟测试：不依赖网络与 LLM，验证三个契约文件真的能用。

运行：python -m pytest tests/test_contracts.py -q
     或直接 python tests/test_contracts.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 用临时目录，避免污染开发库
_TMP = tempfile.mkdtemp(prefix="cna-test-")
import os  # noqa: E402

os.environ["STORAGE_DIR"] = _TMP

from app.core.security import hash_password, verify_password  # noqa: E402
from app.db.conn import business_db, init_databases, kb_db  # noqa: E402
from app.schemas.agent_io import (  # noqa: E402
    Evidence,
    KnowledgeItem,
    NoteResult,
    OutlineNode,
    QualityScore,
)
from app.services.llm import _parse_json  # noqa: E402
from app.services.query import (  # noqa: E402
    build_fts_query,
    extract_query_terms,
    index_chunks,
    query_bigrams,
    quote_in_text,
    search_chunks,
    to_bigram,
)


def test_init_databases_creates_both_files() -> None:
    paths = init_databases(reset=True)
    assert Path(paths["business"]).exists(), "business.db 未创建"
    assert Path(paths["kb"]).exists(), "kb.db 未创建"
    with business_db() as conn:
        names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for required in ("users", "documents", "chunks", "ft_chunks", "sessions",
                     "notes", "note_items", "note_versions", "chats"):
        assert required in names, f"business.db 缺少表 {required}"
    with kb_db() as conn:
        names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for required in ("knowledge_points", "knowledge_relations", "example_problems",
                     "latex_rules", "source_index"):
        assert required in names, f"kb.db 缺少表 {required}"


def test_password_hash_roundtrip() -> None:
    stored = hash_password("admin123")
    assert stored.startswith("pbkdf2_sha256$")
    assert "admin123" not in stored, "口令不能明文出现在哈希串里"
    assert verify_password("admin123", stored)
    assert not verify_password("admin124", stored)
    assert not verify_password("admin123", "PLACEHOLDER_CHANGE_ME")


def test_bigram_and_fts_search() -> None:
    assert to_bigram("函数的极限") == "函数 数的 的极 极限"
    assert "limit" in to_bigram("求 limit 值")
    assert build_fts_query("极限").count("OR") == 0

    # 疑问词剔除：口语化提问不应稀释检索覆盖率
    assert extract_query_terms("可导和连续是什么关系") == ["可导", "连续"], \
        extract_query_terms("可导和连续是什么关系")
    assert extract_query_terms("请帮我解释一下导数的几何意义") == ["导数", "几何意义"]
    assert extract_query_terms("开闭原则要求软件实体怎样面对扩展和修改") == ["开闭原则", "扩展", "修改"]
    assert extract_query_terms("罗尔定理") == ["罗尔定理"]
    assert query_bigrams("可导和连续是什么关系") == {"可导", "连续"}, \
        "疑问词「是什么」「关系」不应进入检索"

    init_databases(reset=True)
    with business_db() as conn:
        conn.execute("INSERT INTO users (username, password_hash, nickname) VALUES ('u1','x','u1')")
        uid = conn.execute("SELECT user_id FROM users WHERE username='u1'").fetchone()["user_id"]
        cur = conn.execute(
            """INSERT INTO documents (user_id, course_name, source_file, stored_path, file_type)
               VALUES (?, '高等数学（上）', 'ch2.pdf', 'storage/ch2.pdf', 'pdf')""", (uid,))
        doc_id = cur.lastrowid
        rows = [
            {"chunk_key": f"d{doc_id}-p1-c1", "doc_id": doc_id,
             "text": "函数在点 x0 处的导数描述函数在该点附近的变化率，几何意义是切线的斜率。"},
            {"chunk_key": f"d{doc_id}-p2-c1", "doc_id": doc_id,
             "text": "可导必连续，连续不一定可导。可导的充分必要条件是左右导数存在且相等。"},
            {"chunk_key": f"d{doc_id}-p3-c1", "doc_id": doc_id,
             "text": "重要极限：当 x 趋于 0 时，sin x 与 x 的比值趋于 1。"},
        ]
        for r in rows:
            conn.execute(
                """INSERT INTO chunks (chunk_key, doc_id, seq, page_num, char_start, char_end, text)
                   VALUES (?, ?, ?, ?, 0, 0, ?)""",
                (r["chunk_key"], doc_id, int(r["chunk_key"].split("-p")[1].split("-")[0]),
                 int(r["chunk_key"].split("-p")[1].split("-")[0]), r["text"]))
        index_chunks(conn, rows)

        found = search_chunks(conn, "导数的几何意义是什么", doc_ids=[doc_id], top_k=2)
        assert found.confident, "全文检索没有召回任何片段"
        top = found.confident[0]
        assert top["chunk_key"].endswith("p1-c1"), f"最相关片段排序不对：{top['chunk_key']}"
        assert top["page_num"] == 1 and top["source_file"] == "ch2.pdf"

        found2 = search_chunks(conn, "可导和连续的关系", doc_ids=[doc_id], top_k=2)
        assert found2.confident and found2.confident[0]["chunk_key"].endswith("p2-c1")

        # 关键回归用例：FTS 的 OR 粗召回会因为命中「力学」而错误召回导数章节，
        # 必须靠覆盖率重排把它们过滤掉，否则系统会「编造材料外的答案」。
        assert search_chunks(conn, "量子力学的不确定性原理", doc_ids=[doc_id]).empty, \
            "无关问题不应有召回"
        assert search_chunks(conn, "红烧肉怎么做才好吃", doc_ids=[doc_id]).empty, \
            "无关问题不应有召回"
        assert top["relevance"] > 0.5 and top["coverage"] > 0.5, "相关片段的覆盖率应偏高"



def test_quote_verification() -> None:
    text = ("函数在点 x0 处的导数描述函数在该点附近的变化率，几何意义：曲线在点 (x0, f(x0)) 处切线的斜率。")
    # 通过：原文连续片段
    assert quote_in_text("几何意义：曲线在点 (x0, f(x0)) 处切线的斜率", text)
    assert quote_in_text("函数在点 x0 处的导数描述函数在该点附近的变化率", text)
    # 通过：只改了标点
    assert quote_in_text("函数在点x0处的导数描述函数在该点附近的变化率", text), "标点差异应容忍"
    assert quote_in_text("几何意义, 曲线在点(x0,f(x0))处切线的斜率", text), "标点被改写应容忍"
    # 拦截：编造
    assert not quote_in_text("导数就是函数的积分", text), "编造的内容必须被判为不通过"
    assert not quote_in_text("", text)
    assert not quote_in_text("导数", text), "过短的引文不具备证据效力，必须拒绝"
    # 拦截：看似同义但非原文的拼接（原文是「几何意义：曲线在点…处切线的斜率」）
    # 这是有意的保守取舍：宁可让模型重抄一遍原文，也不放过任何非原文表述。
    assert not quote_in_text("几何意义是切线的斜率", text), "改写拼接的引文不予通过"


def test_json_fallback_parsing() -> None:
    assert _parse_json('{"items": []}') == {"items": []}
    assert _parse_json('```json\n{"items": []}\n```') == {"items": []}
    assert _parse_json('好的，结果如下：{"items": [{"name": "导数"}]} 以上。') == {"items": [{"name": "导数"}]}
    assert _parse_json('{"items": [1,2,],}') == {"items": [1, 2]}, "尾随逗号应被修复"
    assert _parse_json("模型今天不想输出 JSON") is None


def test_agent_io_contracts() -> None:
    ev = Evidence(chunk_key="d1-p1-c1", source_file="ch2.pdf", page_num=1, quote="导数")
    item = KnowledgeItem(name="导数", definition="变化率", key_points=["切线斜率"], evidence=[ev])
    score = QualityScore.from_dimensions(core=90, structure=80, extension=70)
    assert score.total == round(90 * 0.85 + 80 * 0.10 + 70 * 0.05, 1) == 88.0

    result = NoteResult(
        course_name="高等数学（上）",
        outline=[OutlineNode(title="第2章 导数与微分", level=1, items=[item])],
        key_points=["导数的定义与几何意义"],
        mindmap_text="导数与微分\n├─ 导数定义\n└─ 可导与连续",
        quality=score,
        dropped_items=2,
    )
    dumped = result.model_dump()
    assert dumped["outline"][0]["items"][0]["evidence"][0]["page_num"] == 1
    assert NoteResult.model_validate(dumped).quality.total == 88.0
    try:
        KnowledgeItem(name="x", importance=9)
        raise AssertionError("importance 越界应当报错")
    except Exception:
        pass


def test_env_values_ignore_inline_comments(monkeypatch) -> None:
    """回归用例：.env 里的行内注释不能污染配置值。

    线上真踩过：`.env` 写成 `ENABLE_EXAMPLE=1  # 例题整理`，
    注释被当成值的一部分，导致所有功能开关静默变成 false，
    界面上看不到质量自评，排查了很久。这里锁定该行为。
    """
    from app.core import config

    monkeypatch.setenv("T_BOOL_ON", "1        # 说明文字")
    monkeypatch.setenv("T_BOOL_OFF", "0        # 已关闭")
    monkeypatch.setenv("T_SIZE", "37             # 上限")
    monkeypatch.setenv("T_LIST", ".pdf,.docx     # 只放行三种")

    assert config._env_bool("T_BOOL_ON") is True
    assert config._env_bool("T_BOOL_OFF") is False
    assert config._env_int("T_SIZE", 50) == 37
    assert config._env_list("T_LIST", []) == [".pdf", ".docx"], "最后一项不应带注释文本"

    # 非法数值应回退默认值，而不是抛异常导致服务起不来
    monkeypatch.setenv("T_SIZE", "不是数字  # 注释")
    assert config._env_int("T_SIZE", 50) == 50
    monkeypatch.setenv("T_RATE", "abc")
    assert config._env_float("T_RATE", 0.2) == 0.2


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
