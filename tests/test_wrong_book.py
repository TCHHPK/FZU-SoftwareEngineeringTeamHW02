"""错题本（U13）接口测试：列表 + 薄弱度聚合 / 详情 / 重做判分与掌握。

独立于自测模块：用 service 层直接造错题数据（契约 5.1：错题接口不依赖出题，
可先用自造数据独立完成），验证三个端点与判分/掌握/去重逻辑。

运行：python -m pytest tests/test_wrong_book.py -q
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 用 setdefault：conftest 已优先设置隔离存储，这里不覆盖，保持全测试共享同一临时库
_TMP = tempfile.mkdtemp(prefix="cna-wrong-test-")
os.environ.setdefault("STORAGE_DIR", _TMP)
os.environ.setdefault("UPLOAD_DIR", str(Path(_TMP) / "uploads"))
os.environ.setdefault("AGENT_STUB", "1")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from fastapi.testclient import TestClient  # noqa: E402

from app.db.conn import business_db, init_databases  # noqa: E402
from app.main import app  # noqa: E402
from app.services import wrong_book  # noqa: E402

init_databases()  # 确保迁移表（wrong_questions 等）已建


# --------------------------------------------------------------------------
# 判分纯函数（契约 4.2，口径唯一）
# --------------------------------------------------------------------------
def test_judge_single_choice_normalization():
    f = wrong_book.judge_answer
    assert f("B", "B") is True
    assert f("B", "b") is True          # 大小写归一化
    assert f("B", "Ａ") is False        # 全角Ａ → A ≠ b
    assert f("B", "A") is False
    assert f("B", "") is False          # 空答案记错
    assert f("B", None) is False        # 空答案记错，不抛异常


def test_judge_judge_mapping():
    f = wrong_book.judge_answer
    # 真值之间互通
    assert f("对", "对") is True
    assert f("对", "true") is True
    assert f("对", "TRUE") is True
    assert f("对", "1") is True
    assert f("对", "是") is True
    # 假值之间互通
    assert f("错", "错") is True
    assert f("错", "false") is True
    assert f("错", "0") is True
    assert f("错", "否") is True
    # 真假不互通
    assert f("对", "错") is False
    assert f("对", "false") is False
    assert f("错", "true") is False


def test_judge_explicit_question_type_overrides_heuristic():
    f = wrong_book.judge_answer
    # 显式 single：即使答案长得像判断值，也走字符串相等，不做判断映射
    assert f("对", "true", question_type="single") is False
    # 显式 judge：做映射
    assert f("是", "Y", question_type="judge") is True


# --------------------------------------------------------------------------
# 辅助
# --------------------------------------------------------------------------
def _register(client: TestClient, username: str) -> int:
    r = client.post("/api/auth/register",
                    json={"username": username, "password": "passw0rd", "nickname": username})
    assert r.status_code == 200, r.text
    r2 = client.post("/api/auth/login", json={"username": username, "password": "passw0rd"})
    assert r2.status_code == 200, r2.text
    return int(r2.json()["data"]["user"]["user_id"])


def _seed(uid: int, **kw) -> int:
    with business_db() as conn:
        return wrong_book.add_wrong_question(conn, user_id=uid, **kw)


# --------------------------------------------------------------------------
# 接口
# --------------------------------------------------------------------------
def test_unauthenticated_is_401():
    with TestClient(app) as c:
        assert c.get("/api/wrong-questions").status_code == 401
        assert c.get("/api/wrong-questions/1").status_code == 401
        assert c.post("/api/wrong-questions/1/retry", json={"answer": "x"}).status_code == 401


def test_empty_list_shape():
    with TestClient(app) as c:
        _register(c, "wb_empty")
        r = c.get("/api/wrong-questions").json()
        assert r["code"] == 0
        assert r["data"]["total"] == 0
        assert r["data"]["items"] == []
        assert r["data"]["weak_points"] == []


def test_list_and_weak_point_aggregation_with_dedup():
    with TestClient(app) as c:
        uid = _register(c, "wb_agg")
        # 同一知识点下两题；其中 101 重复答错两次（去重加次数，不新增行）
        _seed(uid, knowledge_name="开闭原则", source_id=101,
              question_stem="Q1", correct_answer="B", analysis="a1",
              evidence_chunk_key="d1-p3-c1", evidence_page=12)
        _seed(uid, knowledge_name="开闭原则", source_id=102,
              question_stem="Q2", correct_answer="对", analysis="a2", evidence_page=5)
        _seed(uid, knowledge_name="开闭原则", source_id=101,
              question_stem="Q1", correct_answer="B")  # 重复答错

        data = c.get("/api/wrong-questions").json()["data"]
        # 行数去重：仍是 2 行
        assert data["total"] == 2, data
        assert len(data["items"]) == 2
        # 错题次数聚合：101 错 2 次 + 102 错 1 次 = 3
        wp = data["weak_points"][0]
        assert wp["knowledge_name"] == "开闭原则"
        assert wp["wrong_count"] == 3, wp
        assert wp["unmastered_count"] == 2
        assert wp["mastered_count"] == 0
        assert wp["weakness"] == "高"  # wrong_count>=3


def test_detail_and_cross_user_isolation():
    with TestClient(app) as c:
        alice = _register(c, "wb_alice")
        wid = _seed(alice, knowledge_name="依赖倒置", source_id=201,
                    question_stem="Q", correct_answer="C", analysis="解析",
                    evidence_chunk_key="d2-p1-c1", evidence_page=8)
        # 本人可看详情
        d = c.get(f"/api/wrong-questions/{wid}").json()["data"]
        assert d["wrong_id"] == wid
        assert d["correct_answer"] == "C"
        assert d["analysis"] == "解析"
        assert d["evidence_page"] == 8

        # 换 bob：越权一律 404（不区分不存在与无权）
        _register(c, "wb_bob")
        assert c.get(f"/api/wrong-questions/{wid}").status_code == 404
        assert c.post(f"/api/wrong-questions/{wid}/retry",
                      json={"answer": "C"}).status_code == 404
        # 不存在的 id 也是 404
        assert c.get("/api/wrong-questions/999999").status_code == 404


def test_retry_mastery_flow():
    with TestClient(app) as c:
        uid = _register(c, "wb_mastery")
        wid = _seed(uid, knowledge_name="单一职责", source_id=301,
                    question_stem="Q", correct_answer="D", evidence_page=3)

        # 第一次答错：连对清零，错题次数 +1
        r = c.post(f"/api/wrong-questions/{wid}/retry", json={"answer": "A"}).json()["data"]
        assert r["is_correct"] is False
        assert r["correct_streak"] == 0
        assert r["mastered"] is False
        assert r["correct_answer"] == "D"
        assert r["mastery_threshold"] == 2

        # 答对一次（大小写归一化）：连对 1，尚未掌握
        r = c.post(f"/api/wrong-questions/{wid}/retry", json={"answer": "d"}).json()["data"]
        assert r["is_correct"] is True
        assert r["correct_streak"] == 1
        assert r["mastered"] is False

        # 再答对一次：达到阈值 → 已掌握
        r = c.post(f"/api/wrong-questions/{wid}/retry", json={"answer": "D"}).json()["data"]
        assert r["is_correct"] is True
        assert r["correct_streak"] == 2
        assert r["mastered"] is True

        # 列表反映掌握状态
        data = c.get("/api/wrong-questions").json()["data"]
        item = next(i for i in data["items"] if i["wrong_id"] == wid)
        assert item["mastered"] is True
        wp = data["weak_points"][0]
        assert wp["mastered_count"] == 1
        assert wp["unmastered_count"] == 0
        assert wp["weakness"] == "已掌握"

        # 掌握后又答错：打回未掌握，连对清零
        r = c.post(f"/api/wrong-questions/{wid}/retry", json={"answer": "X"}).json()["data"]
        assert r["is_correct"] is False
        assert r["correct_streak"] == 0
        assert r["mastered"] is False


def test_retry_empty_answer_is_wrong():
    with TestClient(app) as c:
        uid = _register(c, "wb_emptyans")
        wid = _seed(uid, knowledge_name="接口隔离", source_id=401, correct_answer="A")
        r = c.post(f"/api/wrong-questions/{wid}/retry", json={"answer": ""}).json()["data"]
        assert r["is_correct"] is False


def test_filter_by_knowledge_and_mastered():
    with TestClient(app) as c:
        uid = _register(c, "wb_filter")
        w1 = _seed(uid, knowledge_name="里氏替换", source_id=501, correct_answer="A")
        w2 = _seed(uid, knowledge_name="合成复用", source_id=502, correct_answer="B")
        # 把 w1 练成已掌握
        c.post(f"/api/wrong-questions/{w1}/retry", json={"answer": "A"})
        c.post(f"/api/wrong-questions/{w1}/retry", json={"answer": "A"})

        # 按知识点筛选
        data = c.get("/api/wrong-questions", params={"knowledge_name": "里氏"}).json()["data"]
        assert data["total"] == 1
        assert data["items"][0]["wrong_id"] == w1
        assert all(wp["knowledge_name"] == "里氏替换" for wp in data["weak_points"])

        # 仅看已掌握
        data = c.get("/api/wrong-questions", params={"mastered": 1}).json()["data"]
        assert data["total"] == 1
        assert data["items"][0]["wrong_id"] == w1
        # 仅看未掌握
        data = c.get("/api/wrong-questions", params={"mastered": 0}).json()["data"]
        assert data["total"] == 1
        assert data["items"][0]["wrong_id"] == w2


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
