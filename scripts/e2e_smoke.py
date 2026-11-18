"""端到端联调自检：模拟前端真实调用顺序走一遍完整业务流程。

与 tests/test_api.py 的区别：这里跑的是「一条按真实使用顺序串起来的链路」，
输出人类可读的每一步结果，用于每天集成后确认主流程没断，也用作答辩演示脚本的底稿。

运行：python scripts/e2e_smoke.py      （不需要模型服务与密钥）
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_TMP = tempfile.mkdtemp(prefix="cna-e2e-")
os.environ["STORAGE_DIR"] = _TMP
os.environ["UPLOAD_DIR"] = str(Path(_TMP) / "uploads")
os.environ["AGENT_STUB"] = "1"

import pymupdf  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db.conn import init_databases  # noqa: E402
from app.main import app  # noqa: E402

# 演示用的模拟课件（内容为高等数学第一章的常识性表述，仅用于走通链路）
DEMO_PAGES = [
    ("第1章 函数与极限", "本章讨论函数的概念、数列的极限与函数的极限。"),
    ("1.1 函数的概念",
     "函数是定义在非空数集上的对应关系，定义域与值域是它的两个基本要素。\n"
     "函数的表示方法有解析法、列表法与图象法。"),
    ("1.2 数列的极限",
     "数列极限的严格定义使用 ε-N 语言描述：对任意正数 ε，都存在正整数 N，"
     "当 n 大于 N 时数列项与极限值之差的绝对值小于 ε。"),
    ("1.3 函数的极限",
     "函数极限存在要求左极限与右极限都存在且相等。"),
]


def banner(step: str, text: str) -> None:
    print(f"\n[{step}] {text}")


def main() -> int:
    failures: list[str] = []

    def check(condition: bool, message: str) -> None:
        print(f"      {'OK ' if condition else '!! '}{message}")
        if not condition:
            failures.append(message)

    init_databases(reset=True)

    pdf_path = Path(_TMP) / "demo-ch1.pdf"
    doc = pymupdf.open()
    for title, body in DEMO_PAGES:
        page = doc.new_page()
        page.insert_text((60, 80), title, fontsize=17, fontname="china-s")
        page.insert_textbox(pymupdf.Rect(60, 110, 520, 760), body, fontsize=12, fontname="china-s")
    doc.save(str(pdf_path))
    doc.close()

    with TestClient(app) as client:
        banner("1/7", "健康检查与元信息")
        check(client.get("/api/health").json() == {"status": "ok"}, "GET /api/health")
        meta = client.get("/api/meta").json()["data"]
        check(meta["logged_in"] is False, "未登录时 meta.logged_in=False")
        check(meta["features"]["formula_ocr"] is False, "未实现的功能开关为关")

        banner("2/7", "注册与登录")
        r = client.post("/api/auth/register",
                        json={"username": "demo_student", "password": "demo123456",
                              "nickname": "演示学生"})
        check(r.status_code == 200, f"注册 {r.status_code}")
        check(client.get("/api/auth/me").json()["data"]["username"] == "demo_student",
              "登录态生效")

        banner("3/7", "上传课件并解析")
        with pdf_path.open("rb") as fp:
            r = client.post("/api/uploads", files={"file": (pdf_path.name, fp, "application/pdf")},
                            data={"course_name": "高等数学（上）"})
        check(r.status_code == 200, f"上传 {r.status_code}")
        upload = r.json()["data"]
        d = upload["document"]
        doc_id = d["doc_id"]
        check(d["parse_status"] == "success", f"解析状态 {d['parse_status']}")
        check(d["page_count"] == len(DEMO_PAGES), f"解析出 {d['page_count']} 页")
        check(d["chunk_count"] >= len(DEMO_PAGES), f"生成 {d['chunk_count']} 个文本块")
        check(bool(upload["chapters"]), f"识别章节：{upload['chapters'][:3]}")

        banner("4/7", "发起整理任务并等待完成")
        r = client.post("/api/sessions", json={"doc_ids": [doc_id], "course_name": "高等数学（上）"})
        check(r.status_code == 202, f"创建任务 {r.status_code}")
        session_id = r.json()["data"]["session_id"]
        status = client.get(f"/api/sessions/{session_id}").json()["data"]
        check(status["status"] in {"success", "partial"}, f"任务终态 {status['status']}")
        check(status["progress"] == 100, "进度 100")

        banner("5/7", "查看整理结果（笔记 / 重点 / 导图 / 自评 / 出处）")
        result = client.get(f"/api/sessions/{session_id}/result").json()["data"]
        check(len(result["items"]) >= len(DEMO_PAGES), f"{len(result['items'])} 个知识点条目")
        check(bool(result["key_points"]), "重点清单已生成")
        check(bool(result["mindmap_text"]), "文本思维导图已生成")
        check(result["quality"] is not None, f"质量自评总分 {result['quality']['total']}")
        with_evidence = sum(1 for it in result["items"] if it["evidence"])
        check(with_evidence == len(result["items"]),
              f"{with_evidence}/{len(result['items'])} 个条目带原文出处")
        first = result["items"][0]
        ev = first["evidence"][0]
        print(f"      示例出处：{ev['source_file']} 第 {ev['page_num']} 页 / {ev['chunk_key']}")
        print(f"      引文：{ev['quote'][:40]}...")

        banner("6/7", "导出与检索验证")
        md = client.get(f"/api/sessions/{session_id}/export", params={"fmt": "md"})
        check(md.status_code == 200 and "【出处】" in md.text, f"Markdown 导出 {len(md.text)} 字符")
        tex = client.get(f"/api/sessions/{session_id}/export", params={"fmt": "tex"})
        check(tex.status_code == 200 and r"\end{document}" in tex.text,
              f"LaTeX 导出 {len(tex.text)} 字符")
        found = client.get(f"/api/sessions/{session_id}/chunks/search",
                           params={"q": "数列极限是怎么定义的"}).json()["data"]
        check(bool(found["confident"]), "相关问题能召回到证据")
        if found["confident"]:
            top = found["confident"][0]
            print(f"      命中 p{top['page_num']} coverage={top['coverage']} "
                  f"「{top['text'][:30]}...」")
        none = client.get(f"/api/sessions/{session_id}/chunks/search",
                          params={"q": "红烧肉怎么做才好吃"}).json()["data"]
        check(none["hits"] == [], "无关问题零召回（据此回答「材料未涉及」）")

        banner("7/7", "越权与异常路径")
        client.post("/api/auth/register", json={"username": "demo_other", "password": "demo123456"})
        check(client.get(f"/api/uploads/{doc_id}").status_code == 404, "他人无法读取该材料")
        check(client.get(f"/api/sessions/{session_id}").status_code == 404, "他人无法读取该任务")
        check(client.get("/api/admin/stats").status_code == 403, "学生无法访问管理接口")
        bad = Path(_TMP) / "broken.pdf"
        bad.write_bytes(b"%PDF-1.7 not really a pdf")
        with bad.open("rb") as fp:
            r = client.post("/api/uploads", files={"file": ("broken.pdf", fp, "application/pdf")})
        check(r.status_code == 422 and bool(r.json()["message"]),
              f"损坏文件被拒并给出原因：{r.json()['message'][:36]}")

    print("\n" + "=" * 64)
    if failures:
        print(f"端到端自检发现 {len(failures)} 处问题：")
        for f in failures:
            print("  -", f)
        return 1
    print("端到端自检通过：注册 → 上传 → 解析 → 整理 → 结果 → 导出 → 检索 → 越权拦截，全部正常")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
