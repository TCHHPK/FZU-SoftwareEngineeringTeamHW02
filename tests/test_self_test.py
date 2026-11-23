"""智能自测（U14）的端到端测试。

覆盖四条关键行为：
    1. 组卷 → 取卷：答案不下发前端；
    2. 交卷判分：全对 100 分、全错 0 分；
    3. 错题回填：错的题进 wrong_questions，重复答错只加次数不产生新行；
    4. 幂等与越权：重复交卷不重复加分；别人的卷子返回 404。

运行：python -m pytest tests/test_self_test.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymupdf  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db.conn import business_db  # noqa: E402
from app.main import app  # noqa: E402

# 一份极简课件：四页，每页一个可抽成知识点的定义
PAGES = [
    ("第3章 软件测试", "本章讨论软件测试的基本概念与方法。"),
    ("3.1 等价类划分", "等价类划分把输入域划分为若干等价类，从每个等价类中取一个代表值设计用例。"),
    ("3.2 边界值分析", "边界值分析关注输入范围的边界，因为边界附近最容易出现缺陷。"),
    ("3.3 语句覆盖", "语句覆盖要求程序中的每条可执行语句至少执行一次。"),
]


def _make_pdf(path: Path) -> Path:
    doc = pymupdf.open()
    for title, body in PAGES:
        page = doc.new_page()
        page.insert_text((60, 80), title, fontsize=16, fontname="china-s")
        page.insert_textbox(pymupdf.Rect(60, 110, 520, 760), body, fontsize=12, fontname="china-s")
    doc.save(str(path))
    doc.close()
    return path


def _register(client: TestClient, username: str) -> None:
    r = client.post("/api/auth/register",
                    json={"username": username, "password": "passw0rd", "nickname": username})
    assert r.status_code == 200, r.text


def _prepare_session(client: TestClient, pdf: Path, course: str = "软件工程") -> int:
    """上传 → 建任务 → 等整理完成，返回 session_id。"""
    with pdf.open("rb") as fp:
        up = client.post("/api/uploads", files={"file": (pdf.name, fp, "application/pdf")},
                         data={"course_name": course})
    assert up.status_code == 200, up.text
    doc_id = up.json()["data"]["document"]["doc_id"]

    created = client.post("/api/sessions", json={"doc_ids": [doc_id], "course_name": course})
    assert created.status_code == 202, created.text
    session_id = created.json()["data"]["session_id"]

    status = client.get(f"/api/sessions/{session_id}").json()["data"]
    assert status["status"] in {"success", "partial"}, f"整理未完成：{status}"
    return session_id


def _answers_from_db(test_id: int) -> list[dict]:
    """测试用：直接从库里读正确答案，模拟「知道答案的学生」。"""
    with business_db() as conn:
        rows = conn.execute(
            "SELECT item_id, answer FROM self_test_items WHERE test_id = ? ORDER BY seq",
            (test_id,),
        ).fetchall()
    return [{"item_id": int(r["item_id"]), "answer": r["answer"]} for r in rows]


def _wrong_answers(test_id: int) -> list[dict]:
    """构造全错答案：单选里挑一个不等于正确答案的字母。"""
    correct = _answers_from_db(test_id)
    return [{"item_id": a["item_id"], "answer": "A" if a["answer"] != "A" else "B"}
            for a in correct]


def test_self_test_full_flow(tmp_path) -> None:
    # 临时 PDF 写到 pytest 的临时目录，避免污染仓库（曾把 _tmp_quiz.pdf 提交进去）
    pdf = _make_pdf(tmp_path / "quiz.pdf")
    with TestClient(app) as client:
        _register(client, "quiz_alice")
        session_id = _prepare_session(client, pdf)

        # ---- 组卷：202 + draft ----
        r = client.post("/api/self-tests", json={"session_id": session_id, "question_count": 3})
        assert r.status_code == 202, r.text
        test_id = r.json()["data"]["test_id"]
        assert r.json()["data"]["status"] == "draft"

        # ---- 取卷：已出题、且不含答案 ----
        paper = client.get(f"/api/self-tests/{test_id}").json()["data"]
        assert paper["status"] == "ready", f"出题未完成：{paper}"
        assert paper["question_count"] == 3
        items = paper["items"]
        assert len(items) == 3
        for item in items:
            assert item["stem"] and len(item["options"]) >= 2
            assert "answer" not in item, "未判分时不得下发答案"
            assert "analysis" not in item, "未判分时不得下发解析"

        # ---- 交卷（全对）：100 分、无错题 ----
        r = client.post(f"/api/self-tests/{test_id}/submit",
                        json={"answers": _answers_from_db(test_id)})
        assert r.status_code == 200, r.text
        result = r.json()["data"]
        assert result["status"] == "graded"
        assert result["score"] == 100.0 and result["correct_count"] == 3
        assert result["wrong_count"] == 0
        # 判分后才返回答案与解析
        assert all("answer" in it and "analysis" in it for it in result["items"])

        with business_db() as conn:
            n_wrong = conn.execute(
                "SELECT COUNT(*) AS c FROM wrong_questions WHERE user_id = "
                "(SELECT user_id FROM self_tests WHERE test_id = ?)", (test_id,)
            ).fetchone()["c"]
        assert n_wrong == 0, "全对不应产生错题"

        # ---- 重复交卷：幂等，分数不变 ----
        r2 = client.post(f"/api/self-tests/{test_id}/submit", json={"answers": _wrong_answers(test_id)})
        assert r2.status_code == 200
        assert r2.json()["data"]["score"] == 100.0, "重复提交不得覆盖已判分数"


def test_self_test_wrong_answers_go_to_wrong_book(tmp_path) -> None:
    pdf = _make_pdf(tmp_path / "quiz_wrong.pdf")
    with TestClient(app) as client:
        _register(client, "quiz_bob")
        session_id = _prepare_session(client, pdf)

        test_id = client.post("/api/self-tests",
                              json={"session_id": session_id, "question_count": 3}
                              ).json()["data"]["test_id"]
        assert client.get(f"/api/self-tests/{test_id}").json()["data"]["status"] == "ready"

        r = client.post(f"/api/self-tests/{test_id}/submit",
                        json={"answers": _wrong_answers(test_id)})
        result = r.json()["data"]
        assert result["score"] == 0.0 and result["correct_count"] == 0
        assert result["wrong_count"] == 3, "三道错题都应回填"

        with business_db() as conn:
            rows = conn.execute(
                """SELECT w.knowledge_name, w.wrong_count, w.correct_streak, w.mastered
                     FROM wrong_questions w
                     JOIN self_tests t ON t.user_id = w.user_id
                    WHERE t.test_id = ?""", (test_id,)
            ).fetchall()
        assert len(rows) == 3
        assert all(row["wrong_count"] == 1 and row["correct_streak"] == 0
                   and row["mastered"] == 0 for row in rows)
        assert all(row["knowledge_name"] for row in rows), "错题应带知识点名，供薄弱度聚合"


def test_self_test_rejects_bad_and_cross_user(tmp_path) -> None:
    pdf = _make_pdf(tmp_path / "quiz_guard.pdf")
    with TestClient(app) as client:
        _register(client, "quiz_carol")
        session_id = _prepare_session(client, pdf)
        test_id = client.post("/api/self-tests",
                              json={"session_id": session_id, "question_count": 2}
                              ).json()["data"]["test_id"]

        # 不存在的任务 → 404
        r = client.post("/api/self-tests", json={"session_id": 999999, "question_count": 3})
        assert r.status_code == 404

        # 题量越界 → 422
        r = client.post("/api/self-tests", json={"session_id": session_id, "question_count": 99})
        assert r.status_code == 422

        # 未登录 → 401
        anon = TestClient(app)
        assert anon.get(f"/api/self-tests/{test_id}").status_code == 401

        # 别人的卷子 → 404（不暴露存在性）
        client.post("/api/auth/logout")
        _register(client, "quiz_dave")
        assert client.get(f"/api/self-tests/{test_id}").status_code == 404
        assert client.post(f"/api/self-tests/{test_id}/submit",
                           json={"answers": []}).status_code == 404


def test_self_test_list_and_empty_answers(tmp_path) -> None:
    pdf = _make_pdf(tmp_path / "quiz_list.pdf")
    with TestClient(app) as client:
        _register(client, "quiz_erin")
        session_id = _prepare_session(client, pdf)
        test_id = client.post("/api/self-tests",
                              json={"session_id": session_id, "question_count": 2}
                              ).json()["data"]["test_id"]
        assert client.get(f"/api/self-tests/{test_id}").json()["data"]["status"] == "ready"

        # 空答案交卷：不报错，全部记错
        r = client.post(f"/api/self-tests/{test_id}/submit", json={"answers": []})
        assert r.status_code == 200
        assert r.json()["data"]["score"] == 0.0

        # 列表里能看到这张卷
        rows = client.get("/api/self-tests").json()["data"]
        assert any(row["test_id"] == test_id for row in rows)
        row = next(r for r in rows if r["test_id"] == test_id)
        assert row["status"] == "graded" and row["correct_count"] == 0


def test_submit_rejects_draft_and_failed(tmp_path) -> None:
    """缺陷 A30：只有 ready 能判分；draft / failed 一律 409，不许返回 200 判 0 分。"""
    pdf = _make_pdf(tmp_path / "quiz_a30.pdf")
    with TestClient(app) as client:
        _register(client, "quiz_frank")
        session_id = _prepare_session(client, pdf)
        test_id = client.post("/api/self-tests",
                              json={"session_id": session_id, "question_count": 2}
                              ).json()["data"]["test_id"]
        assert client.get(f"/api/self-tests/{test_id}").json()["data"]["status"] == "ready"

        # 手工把状态改成 draft（模拟「还在出题」的卷子）
        with business_db() as conn:
            conn.execute("UPDATE self_tests SET status = 'draft' WHERE test_id = ?", (test_id,))
        r = client.post(f"/api/self-tests/{test_id}/submit", json={"answers": []})
        assert r.status_code == 409, r.text
        assert "出题" in r.json()["message"]
        # 草稿卷没有被判分
        with business_db() as conn:
            row = conn.execute("SELECT status, score FROM self_tests WHERE test_id = ?",
                               (test_id,)).fetchone()
        assert row["status"] == "draft" and float(row["score"] or 0) == 0.0

        # 出题失败的卷子同样 409，且提示重新组卷
        with business_db() as conn:
            conn.execute("UPDATE self_tests SET status = 'failed' WHERE test_id = ?", (test_id,))
        r = client.post(f"/api/self-tests/{test_id}/submit", json={"answers": []})
        assert r.status_code == 409
        assert "重新组卷" in r.json()["message"]


def test_target_and_actual_exposed(tmp_path) -> None:
    """缺陷 A32：要 5 题只给 3 题时，target 与 actual 都要给出，不许静默改写题量。"""
    pdf = _make_pdf(tmp_path / "quiz_a32.pdf")
    with TestClient(app) as client:
        _register(client, "quiz_grace")
        session_id = _prepare_session(client, pdf)

        # 课件只有 3 个知识点，却要 5 题
        test_id = client.post("/api/self-tests",
                              json={"session_id": session_id, "question_count": 5}
                              ).json()["data"]["test_id"]
        paper = client.get(f"/api/self-tests/{test_id}").json()["data"]
        assert paper["status"] == "ready"
        assert paper["target_count"] == 5, "target 应保留用户要的题量"
        assert paper["actual_count"] == len(paper["items"])
        assert paper["actual_count"] < 5, "本例知识点不足，实际题数应少于 5"
        assert paper["shortfall"] is True, "少给时必须标记 shortfall，不能静默"

        # question_count 不应被改写成实际条数（A32 的原始表现）
        with business_db() as conn:
            row = conn.execute("SELECT question_count FROM self_tests WHERE test_id = ?",
                               (test_id,)).fetchone()
        assert int(row["question_count"]) == 5, "question_count 必须保留 target"


def test_concurrent_submit_does_not_double_count(tmp_path) -> None:
    """缺陷 A33：两个线程同时交卷，分数与错题次数都不能翻倍。

    直接调 service（不走 HTTP），用两条独立连接模拟两个并发请求；
    BEGIN IMMEDIATE + 带条件的 UPDATE 保证只有一个请求真正判分。
    """
    import threading

    from app.services import quiz as quiz_service

    pdf = _make_pdf(tmp_path / "quiz_a33.pdf")
    with TestClient(app) as client:
        _register(client, "quiz_heidi")
        session_id = _prepare_session(client, pdf)
        test_id = client.post("/api/self-tests",
                              json={"session_id": session_id, "question_count": 2}
                              ).json()["data"]["test_id"]
        assert client.get(f"/api/self-tests/{test_id}").json()["data"]["status"] == "ready"
        answers = _wrong_answers(test_id)
        # user_id 不能用常量：各测试共用一个业务库，用户 id 是递增的
        with business_db() as conn:
            owner_id = int(conn.execute(
                "SELECT user_id FROM self_tests WHERE test_id = ?", (test_id,)
            ).fetchone()["user_id"])

    results: list[dict] = []
    errors: list[Exception] = []
    barrier = threading.Barrier(2)

    def worker() -> None:
        try:
            barrier.wait(timeout=5)
            with business_db() as conn:
                results.append(quiz_service.submit_test(
                    conn, test_id=test_id, user_id=owner_id, answers=answers))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"并发交卷抛异常：{errors}"
    assert len(results) == 2, "两个请求都应拿到结果或明确 409"

    # 错题次数只加一次：每道题的 wrong_count 必须是 1
    with business_db() as conn:
        rows = conn.execute(
            "SELECT wrong_count FROM wrong_questions WHERE source_type = 'self_test' "
            "AND source_id IN (SELECT item_id FROM self_test_items WHERE test_id = ?)",
            (test_id,)).fetchall()
        graded = conn.execute("SELECT status, score FROM self_tests WHERE test_id = ?",
                              (test_id,)).fetchone()
    assert graded["status"] == "graded"
    assert all(int(r["wrong_count"]) == 1 for r in rows), f"错题次数被重复累加：{[dict(r) for r in rows]}"
    # 两次返回的分数必须一致（都来自同一次判分）
    assert len({r["score"] for r in results}) == 1


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"[PASS] {name}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                import traceback
                print(f"[FAIL] {name}: {type(exc).__name__}: {exc}")
                traceback.print_exc()
    print("-" * 60)
    print("全部通过" if failures == 0 else f"{failures} 个用例失败")
    raise SystemExit(1 if failures else 0)
