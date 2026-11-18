"""API 端到端测试。

用 FastAPI TestClient 跑真实请求，不需要启动服务器、不需要模型服务与密钥。
预置 4 份不同章节的课件，覆盖「指定范围整理 → 查看结果 → 导出 → 跨账号越权」全流程。

运行：python tests/test_api.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 必须在导入 app 之前设置：独立的存储目录 + 开启占位实现
_TMP = tempfile.mkdtemp(prefix="cna-api-test-")
os.environ["STORAGE_DIR"] = _TMP
os.environ["UPLOAD_DIR"] = str(Path(_TMP) / "uploads")
os.environ["AGENT_STUB"] = "1"
os.environ["SECRET_KEY"] = "test-secret-key"

import pymupdf  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db.conn import business_db, init_databases  # noqa: E402
from app.main import app  # noqa: E402

FIXTURES = Path(tempfile.mkdtemp(prefix="cna-api-fixtures-"))

# 一个班的 4 份课件，内容整体来自高等数学（上）第二章，用于验证「指定范围整理」
MATERIALS = {
    "第1章 函数与极限.pdf": [
        ("第1章 函数与极限", "本章讨论函数的概念、数列极限与函数极限。"),
        ("1.1 函数的概念", "函数是定义在非空数集上的对应关系，定义域与值域是它的两个基本要素。"),
        ("1.2 数列的极限", "数列极限的严格定义使用 ε-N 语言描述：对任意正数 ε 都存在正整数 N。"),
        ("1.3 函数的极限", "函数极限有左极限与右极限，二者存在且相等时极限存在。"),
    ],
    "第2章 导数与微分.pdf": [
        ("第2章 导数与微分", "本章讨论导数的概念、求导法则与微分。"),
        ("2.1 导数的概念",
         "函数 y=f(x) 在点 x0 处的导数记作 f'(x0)，描述函数在该点附近的变化率。\n"
         "几何意义：曲线在点 (x0, f(x0)) 处切线的斜率。"),
        ("2.2 求导法则", "积的导数 (uv)'=u'v+uv'；商的导数 (u/v)'=(u'v-uv')/v^2。\n复合函数求导遵循链式法则。"),
        ("2.3 高阶导数", "二阶导数是一阶导数的导数，可用来判断函数曲线的凹凸性。"),
    ],
    "第3章 微分中值定理.pdf": [
        ("第3章 微分中值定理", "本章讨论罗尔定理、拉格朗日中值定理与柯西中值定理。"),
        ("3.1 罗尔定理", "若函数在闭区间连续、开区间可导且两端点函数值相等，则区间内至少存在一点导数为零。"),
        ("3.2 拉格朗日中值定理", "拉格朗日中值定理是罗尔定理的推广，建立了函数增量与导数之间的联系。"),
    ],
    "第4章 不定积分.pdf": [
        ("第4章 不定积分", "本章讨论原函数与不定积分的概念及基本积分方法。"),
        ("4.1 原函数", "若 F'(x)=f(x)，则称 F(x) 是 f(x) 的一个原函数。"),
        ("4.2 基本积分公式", "不定积分是求导运算的逆运算，基本积分公式由基本求导公式反推得到。"),
    ],
}


def make_pdf(path: Path, pages: list[tuple[str, str]]) -> Path:
    doc = pymupdf.open()
    for title, body in pages:
        page = doc.new_page()
        page.insert_text((60, 80), title, fontsize=17, fontname="china-s")
        page.insert_textbox(pymupdf.Rect(60, 110, 520, 760), body, fontsize=12, fontname="china-s")
    doc.save(str(path))
    doc.close()
    return path


def build_fixtures() -> dict[str, Path]:
    return {name: make_pdf(FIXTURES / name, pages) for name, pages in MATERIALS.items()}


class ApiClient:
    """带登录态的轻量客户端封装，避免每个用例重复写登录代码。"""

    def __init__(self, client: TestClient):
        self.c = client

    def register(self, username: str, password: str = "passw0rd") -> dict:
        r = self.c.post("/api/auth/register",
                        json={"username": username, "password": password, "nickname": username})
        assert r.status_code == 200, r.text
        return r.json()["data"]

    def login(self, username: str, password: str = "passw0rd") -> dict:
        r = self.c.post("/api/auth/login", json={"username": username, "password": password})
        assert r.status_code == 200, r.text
        return r.json()["data"]

    def upload(self, path: Path, course_name: str) -> dict:
        with path.open("rb") as fp:
            r = self.c.post("/api/uploads",
                            files={"file": (path.name, fp, "application/pdf")},
                            data={"course_name": course_name})
        return {"status": r.status_code, **r.json()}

    def create_session(self, doc_ids: list[int], course_name: str, **extra) -> dict:
        r = self.c.post("/api/sessions", json={"doc_ids": doc_ids, "course_name": course_name,
                                               **extra})
        return {"status": r.status_code, **r.json()}

    def json(self, method: str, url: str, **kw) -> tuple[int, dict]:
        r = getattr(self.c, method)(url, **kw)
        try:
            return r.status_code, r.json()
        except Exception:  # noqa: BLE001 - 导出接口返回纯文本
            return r.status_code, {"raw": r.text}


def test_health_and_meta_public() -> None:
    with TestClient(app) as client:
        assert client.get("/api/health").json() == {"status": "ok"}
        meta = client.get("/api/meta").json()["data"]
        assert meta["logged_in"] is False
        assert meta["features"]["formula_ocr"] is False, "未实现的功能开关必须为关"
        assert meta["max_upload_mb"] > 0
        assert ".pdf" in meta["allowed_extensions"]


def test_auth_flow_and_errors() -> None:
    with TestClient(app) as client:
        api = ApiClient(client)
        assert client.get("/api/auth/me").status_code == 401, "未登录访问 /me 应 401"

        api.register("alice")
        me = client.get("/api/auth/me").json()["data"]
        assert me["username"] == "alice" and me["role"] == "student"

        # 重复注册
        code, body = api.json("post", "/api/auth/register",
                              json={"username": "alice", "password": "passw0rd"})
        assert code == 409 and "已被注册" in body["message"]

        # 密码过短 / 用户名过短
        assert api.json("post", "/api/auth/register",
                        json={"username": "bob", "password": "123"})[0] == 422
        assert api.json("post", "/api/auth/register",
                        json={"username": "ab", "password": "passw0rd"})[0] == 422

        # 密码错误不透露用户名是否存在
        code, body = api.json("post", "/api/auth/login",
                              json={"username": "alice", "password": "wrongpass"})
        assert code == 401 and body["message"] == "用户名或密码错误"
        code, body = api.json("post", "/api/auth/login",
                              json={"username": "nobody", "password": "wrongpass"})
        assert code == 401 and body["message"] == "用户名或密码错误"

        # 登出后回到未登录
        assert client.post("/api/auth/logout").status_code == 200
        assert client.get("/api/auth/me").status_code == 401

        # Bearer 方式也能用（评测脚本与自动化用）
        token = api.login("alice")["token"]
        r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200 and r.json()["data"]["username"] == "alice"


def test_me_rejects_forged_token() -> None:
    with TestClient(app) as client:
        r = client.get("/api/auth/me", headers={"Authorization": "Bearer forged.token.value"})
        assert r.status_code == 401


def test_upload_validation() -> None:
    fixtures = build_fixtures()
    with TestClient(app) as client:
        api = ApiClient(client)
        api.register("uploader")

        # 正常上传
        ok = api.upload(fixtures["第2章 导数与微分.pdf"], "高等数学（上）")
        assert ok["status"] == 200, ok
        doc = ok["data"]["document"]
        assert doc["parse_status"] == "success"
        assert doc["page_count"] == 4 and doc["chunk_count"] >= 4
        assert "导数" in "".join(ok["data"]["chapters"])
        doc_id = doc["doc_id"]

        # 真正不支持的类型
        weird = FIXTURES / "data.xyz"
        weird.write_bytes(b"whatever")
        with weird.open("rb") as fp:
            r = client.post("/api/uploads",
                            files={"file": ("data.xyz", fp, "application/octet-stream")})
        assert r.status_code == 400 and "不支持的文件类型" in r.json()["message"]

        # 旧格式 .ppt 明确提示另存
        with (FIXTURES / "old.ppt").open("wb") as fp:
            fp.write(b"x")
        with (FIXTURES / "old.ppt").open("rb") as fp:
            r = client.post("/api/uploads", files={"file": ("old.ppt", fp, "application/vnd.ms-powerpoint")})
        assert r.status_code == 400

        # 扩展支持后：纯文本也应能上传并解析入库
        notes = FIXTURES / "lecture-notes.txt"
        notes.write_text("第5章 软件测试\n\n软件测试的目的是发现缺陷，而不是证明没有缺陷。\n\n"
                         "单元测试关注最小可测单元，集成测试关注模块间接口。", encoding="utf-8")
        with notes.open("rb") as fp:
            r = client.post("/api/uploads", files={"file": (notes.name, fp, "text/plain")},
                            data={"course_name": "软件工程"})
        assert r.status_code == 200, r.text
        assert r.json()["data"]["document"]["file_type"] == "txt"
        assert r.json()["data"]["document"]["parse_status"] == "success"

        # 损坏文件：状态 422 且落库为 failed，能给出原因
        broken = FIXTURES / "broken.pdf"
        broken.write_bytes(b"%PDF-1.7 not really a pdf")
        with broken.open("rb") as fp:
            r = client.post("/api/uploads", files={"file": ("broken.pdf", fp, "application/pdf")})
        assert r.status_code == 422 and r.json()["message"]

        # 空文件
        empty = FIXTURES / "empty.pdf"
        empty.write_bytes(b"")
        with empty.open("rb") as fp:
            r = client.post("/api/uploads", files={"file": ("empty.pdf", fp, "application/pdf")})
        assert r.status_code == 400 and "空" in r.json()["message"]

        # 列表与详情
        docs = client.get("/api/uploads").json()["data"]
        assert any(d["doc_id"] == doc_id for d in docs)
        assert client.get(f"/api/uploads/{doc_id}").json()["data"]["doc_id"] == doc_id
        assert client.get("/api/uploads/999999").status_code == 404

        courses = client.get("/api/uploads/courses").json()["data"]
        assert any(c["course_name"] == "高等数学（上）" for c in courses)


def test_full_flow_note_result_and_export() -> None:
    fixtures = build_fixtures()
    with TestClient(app) as client:
        api = ApiClient(client)
        api.register("student1")
        up = api.upload(fixtures["第2章 导数与微分.pdf"], "高等数学（上）")
        doc_id = up["data"]["document"]["doc_id"]

        created = api.create_session([doc_id], "高等数学（上）")
        assert created["status"] == 202, created
        session_id = created["data"]["session_id"]

        # 状态应已推进到终态（stub 不需要模型服务）
        status_body = client.get(f"/api/sessions/{session_id}").json()["data"]
        assert status_body["status"] in {"success", "partial"}, status_body
        assert status_body["progress"] == 100

        # 结果：结构笔记 + 重点清单 + 文本导图 + 自评
        result = client.get(f"/api/sessions/{session_id}/result").json()["data"]
        assert result["status"] in {"success", "partial"}
        assert result["items"], "结果里必须有知识点条目"
        assert result["key_points"] and result["mindmap_text"]
        assert result["quality"]["total"] > 0

        # 每个条目都要带可核验的出处
        for item in result["items"]:
            assert item["evidence"], f"条目缺少出处：{item['name']}"
            ev = item["evidence"][0]
            assert ev["chunk_key"].startswith("d"), ev
            assert ev["page_num"] or ev["slide_index"], "出处必须带页码或幻灯片序号"

        # 导出两种格式
        md = client.get(f"/api/sessions/{session_id}/export", params={"fmt": "md"})
        assert md.status_code == 200 and "【出处】" in md.text
        assert "# 高等数学（上）" in md.text

        tex = client.get(f"/api/sessions/{session_id}/export", params={"fmt": "tex"})
        assert tex.status_code == 200
        assert r"\documentclass" in tex.text and r"\end{document}" in tex.text
        assert tex.text.count(r"\begin{document}") == 1

        # Word 导出（作业与报告用 Word 交，属于主要导出场景）
        docx = client.get(f"/api/sessions/{session_id}/export", params={"fmt": "docx"})
        assert docx.status_code == 200
        assert docx.content[:2] == b"PK", "docx 应是 zip 容器"
        assert "wordprocessingml" in docx.headers["content-type"]
        # 中文文件名必须走 RFC 5987，否则响应头编码会抛 UnicodeEncodeError
        assert "filename*=UTF-8''" in docx.headers["content-disposition"]

        # 非法格式被参数校验拦下
        assert client.get(f"/api/sessions/{session_id}/export",
                          params={"fmt": "pdf"}).status_code == 422

        # 历史列表
        sessions = client.get("/api/sessions").json()["data"]
        assert any(s["session_id"] == session_id for s in sessions)
        assert sessions[0]["note_count"] >= 1

        # 检索调试接口：能看出证据是怎么找出来的
        found = client.get(f"/api/sessions/{session_id}/chunks/search",
                           params={"q": "导数的几何意义", "top_k": 3}).json()["data"]
        assert found["confident"] and found["confident"][0]["page_num"] == 2
        assert found["confident"][0]["relevance"] > 0.5
        assert found["insufficient"] is False

        # 无关问题必须无召回（系统据此回答「材料未涉及」）
        none = client.get(f"/api/sessions/{session_id}/chunks/search",
                          params={"q": "红烧肉怎么做才好吃"}).json()["data"]
        assert none["hits"] == [] and none["insufficient"] is True


def test_session_creation_rejects_bad_input() -> None:
    fixtures = build_fixtures()
    with TestClient(app) as client:
        api = ApiClient(client)
        api.register("student2")
        up = api.upload(fixtures["第1章 函数与极限.pdf"], "高等数学（上）")
        doc_id = up["data"]["document"]["doc_id"]

        # 空 doc_ids 被参数校验拦下
        assert api.create_session([], "高等数学（上）")["status"] == 422
        # 不存在的文档
        assert api.create_session([999999], "高等数学（上）")["status"] == 404


def test_question_answering_paths(monkeypatch) -> None:
    """问答三态。

    注意：不传 doc_id 时，检索范围是「该用户可见的全部材料」，
    所以这里用一个全新账号并只上传一份课件，把范围隔离干净，
    否则库里其他章节会让无关问题意外命中。
    """
    fixtures = build_fixtures()
    with TestClient(app) as client:
        api = ApiClient(client)
        api.register("qa_isolated")
        up = api.upload(fixtures["第2章 导数与微分.pdf"], "高等数学（上）")
        doc_id = up["data"]["document"]["doc_id"]
        # 管理员上传的公共资料会出现在所有人的列表里，这里只校验「自己的私有材料」范围干净
        private = [d for d in client.get("/api/uploads").json()["data"] if not d["is_public"]]
        assert len(private) == 1, private

        # 范围外的问题：必须明确回答「未涉及」，不能编造
        r = client.post("/api/chat/ask", json={"doc_id": doc_id, "question": "红烧肉怎么做才好吃"})
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["insufficient"] is True
        assert "未涉及" in body["data"]["answer"]
        assert body["data"]["evidence"] == []

        # 术语部分重合但确实无关的问题：同样必须无召回，不能靠「力学」二字硬凑
        r = client.post("/api/chat/ask", json={"doc_id": doc_id,
                                              "question": "量子力学的不确定性原理是什么"})
        assert r.status_code == 200
        assert r.json()["data"]["insufficient"] is True
        assert r.json()["data"]["evidence"] == []

        # 范围内的问题：检索命中后只把可信证据交给模型，并保留引用。
        from app.agents import pipeline as agent_pipeline
        from app.db.conn import business_db

        class FakeLLM:
            def json_call(self, _system, user, **_kwargs):
                import json
                evidence = json.loads(user)["evidence"]
                return {"answer": "导数的几何意义是曲线在该点切线的斜率。",
                        "citations": [evidence[0]["chunk_key"]]}

        monkeypatch.setattr(agent_pipeline, "get_llm", lambda: FakeLLM())
        monkeypatch.setattr(agent_pipeline, "llm_available", lambda: True)

        with business_db() as conn:
            answer = agent_pipeline.answer_question(
                conn, question="导数的几何意义是什么", doc_ids=[doc_id])
            assert answer.insufficient is False
            assert "切线" in answer.answer
            assert answer.evidence and answer.evidence[0].chunk_key

        # 没有任何可用材料时的提示。公共资料是全局共享的，所以先按注册返回的 user_id
        # 查出该账号实际可见的材料数，再据此断言，避免用例依赖执行顺序。
        from app.db.conn import business_db as _bdb

        newbie = api.register("qa_newbie")
        newbie_id = newbie["user"]["user_id"]
        with _bdb() as conn:
            visible = conn.execute(
                "SELECT COUNT(*) AS c FROM documents WHERE user_id = :uid OR is_public = 1",
                {"uid": newbie_id}).fetchone()["c"]
        if visible == 0:
            r = client.post("/api/chat/ask", json={"question": "导数是什么"})
            assert r.status_code == 409 and "上传课件" in r.json()["message"]
        else:
            # 库里有公共资料时，新账号能就公共资料提问 —— 属于预期行为
            r = client.post("/api/chat/ask", json={"question": "红烧肉怎么做才好吃"})
            assert r.status_code == 200 and r.json()["data"]["insufficient"] is True

        # 注册 qa_newbie 会切换登录态；切回原账号检查它自己的问答历史。
        api.login("qa_isolated")
        history = client.get("/api/chat/history").json()["data"]
        assert any(h["role"] == "assistant" for h in history)


def test_permission_isolation_between_users() -> None:
    fixtures = build_fixtures()
    with TestClient(app) as client:
        alice = ApiClient(client)
        alice.register("alice2")
        up = alice.upload(fixtures["第2章 导数与微分.pdf"], "高等数学（上）")
        doc_id = up["data"]["document"]["doc_id"]
        session_id = alice.create_session([doc_id], "高等数学（上）")["data"]["session_id"]

        # 换一个账号（同一个 TestClient，登录态被覆盖）
        bob = ApiClient(client)
        bob.register("bob2")

        # AT-01：不能读别人的文档、任务、结果、导出
        assert client.get(f"/api/uploads/{doc_id}").status_code == 404
        assert client.get(f"/api/sessions/{session_id}").status_code == 404
        assert client.get(f"/api/sessions/{session_id}/result").status_code == 404
        assert client.get(f"/api/sessions/{session_id}/export").status_code == 404
        assert client.post("/api/sessions", json={"doc_ids": [doc_id]}).status_code == 404

        # 列表里可以有管理员维护的公共资料，但绝不能出现别人的私有材料
        docs = client.get("/api/uploads").json()["data"]
        assert all(d["is_public"] or d["doc_id"] != doc_id for d in docs), \
            "学生的材料列表中出现了他人的私有材料"
        assert all(d["doc_id"] != doc_id for d in docs), doc_id
        # 任务列表必须只含自己的
        assert client.get("/api/sessions").json()["data"] == []


def test_admin_permissions_and_stats() -> None:
    fixtures = build_fixtures()
    with TestClient(app) as client:
        # 建一个管理员（注册接口只产生学生账号，管理员由建库脚本或数据库直接创建）
        api = ApiClient(client)
        api.register("admin2")
        with business_db() as conn:
            conn.execute("UPDATE users SET role = 'admin' WHERE username = 'admin2'")

        assert client.post("/api/auth/login",
                           json={"username": "admin2", "password": "passw0rd"}).status_code == 200

        # 管理员上传公共资料
        with fixtures["第3章 微分中值定理.pdf"].open("rb") as fp:
            r = client.post("/api/admin/materials",
                            files={"file": ("第3章 微分中值定理.pdf", fp, "application/pdf")},
                            data={"course_name": "高等数学（上）"})
        assert r.status_code == 200, r.text
        assert r.json()["data"]["document"]["is_public"] is True

        stats = client.get("/api/admin/stats").json()["data"]
        assert stats["public_documents"] >= 1 and stats["chunks"] > 0
        assert stats["features"]["formula_ocr"] is False

        # 没有评测记录时返回空列表，不伪造数据
        evals = client.get("/api/admin/compare-records").json()
        assert evals["data"] == []

        # 学生访问管理接口应 403
        student = ApiClient(client)
        student.register("student3")
        assert client.get("/api/admin/stats").status_code == 403
        with fixtures["第4章 不定积分.pdf"].open("rb") as fp:
            r = client.post("/api/admin/materials",
                            files={"file": ("第4章 不定积分.pdf", fp, "application/pdf")})
        assert r.status_code == 403


def test_public_material_visible_to_students() -> None:
    """公共资料（领域知识库来源）必须对所有学生可读，但不能被学生修改。"""
    fixtures = build_fixtures()
    with TestClient(app) as client:
        api = ApiClient(client)
        api.register("admin3")
        with business_db() as conn:
            conn.execute("UPDATE users SET role = 'admin' WHERE username = 'admin3'")
        api.login("admin3")
        with fixtures["第1章 函数与极限.pdf"].open("rb") as fp:
            r = client.post("/api/admin/materials",
                            files={"file": ("第1章 函数与极限.pdf", fp, "application/pdf")},
                            data={"course_name": "高等数学（上）"})
        public_doc_id = r.json()["data"]["document"]["doc_id"]

        student = ApiClient(client)
        student.register("student4")
        docs = client.get("/api/uploads").json()["data"]
        assert any(d["doc_id"] == public_doc_id for d in docs), "公共资料应对学生可见"
        assert client.get(f"/api/uploads/{public_doc_id}").status_code == 200
        # 学生可以基于公共资料发起整理
        assert student.create_session([public_doc_id], "高等数学（上）")["status"] == 202


def main() -> int:
    import traceback

    init_databases(reset=True)
    failures = 0
    tests = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    for name, fn in tests:
        try:
            fn()
            print(f"[PASS] {name}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"[FAIL] {name}: {type(exc).__name__}: {exc}")
            if os.getenv("TEST_TRACE"):
                traceback.print_exc()
    print("-" * 60)
    print(f"{len(tests) - failures}/{len(tests)} 通过" if failures == 0
          else f"{failures} 个用例失败")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
