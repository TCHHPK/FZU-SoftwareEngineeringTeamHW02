"""生产环境验收：在线上地址跑一遍学习闭环。

与本地 smoke 的区别：打的是真实服务器（有模型密钥、有真实数据库），
所以能验证「部署后老师打开能不能用」。

用法：python scripts/verify_prod.py [--base http://47.114.55.115:8000]
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from pathlib import Path

import pymupdf
import requests

PAGES = [
    ("第3章 软件测试", "本章讨论软件测试的基本概念与方法。"),
    ("3.1 等价类划分", "等价类划分把输入域划分为若干等价类，从每个等价类中取一个代表值设计用例。"),
    ("3.2 边界值分析", "边界值分析关注输入范围的边界，因为边界附近最容易出现缺陷。"),
    ("3.3 语句覆盖", "语句覆盖要求程序中的每条可执行语句至少执行一次。"),
]


def make_pdf(path: Path) -> Path:
    doc = pymupdf.open()
    for title, body in PAGES:
        page = doc.new_page()
        page.insert_text((60, 80), title, fontsize=16, fontname="china-s")
        page.insert_textbox(pymupdf.Rect(60, 110, 520, 760), body, fontsize=12, fontname="china-s")
    doc.save(str(path))
    doc.close()
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://47.114.55.115:8000")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    passed = True

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal passed
        passed &= ok
        print(f"  {'OK  ' if ok else 'FAIL'} {label}{('　' + detail) if detail else ''}")

    s = requests.Session()
    name = f"prod_{uuid.uuid4().hex[:8]}"

    print(f"[1/9] 生产环境 {base}")
    meta = s.get(f"{base}/api/meta", timeout=20).json()["data"]
    check("健康与元信息", True, f"格式 {len(meta['allowed_extensions'])} 种，自评 {meta['features']['quality_eval']}")

    print("[2/9] 前端资源")
    home = s.get(f"{base}/", timeout=20)
    check("首页可访问", home.status_code == 200 and '<div id="app">' in home.text)
    check("前端路由回退", s.get(f"{base}/wrong-book", timeout=20).status_code == 200)

    print("[3/9] 注册 + 上传")
    r = s.post(f"{base}/api/auth/register",
               json={"username": name, "password": "passw0rd", "nickname": name}, timeout=30)
    check("注册", r.status_code == 200, name)
    if r.status_code != 200:
        print("  ", r.text[:200])
        return 1
    s.headers["Authorization"] = "Bearer " + r.json()["data"]["token"]

    pdf = make_pdf(Path.home() / "prod-verify.pdf")
    with pdf.open("rb") as fp:
        up = s.post(f"{base}/api/uploads", files={"file": (pdf.name, fp, "application/pdf")},
                    data={"course_name": "生产验收课程"}, timeout=180)
    doc = up.json()["data"]["document"]
    check("上传解析", up.status_code == 200, f"{doc['parse_status']} / {doc['page_count']} 页")

    print("[4/9] 整理任务（真实调用模型，可能要等 1 分钟）")
    sid = s.post(f"{base}/api/sessions",
                 json={"doc_ids": [doc["doc_id"]], "course_name": "生产验收课程"},
                 timeout=40).json()["data"]["session_id"]
    st = {}
    start = time.time()
    for _ in range(160):
        st = s.get(f"{base}/api/sessions/{sid}", timeout=20).json()["data"]
        if st["status"] in {"success", "partial", "failed"}:
            break
        time.sleep(2)
    check("整理完成", st.get("status") in {"success", "partial"},
          f"{st.get('status')} / {int(time.time() - start)}s / 知识点 {st.get('note_count')}")

    print("[5/9] 智能自测：组卷 → 交卷")
    r = s.post(f"{base}/api/self-tests", json={"session_id": sid, "question_count": 3}, timeout=40)
    check("组卷 202", r.status_code == 202)
    test_id = r.json()["data"]["test_id"]
    paper = {}
    for _ in range(80):
        paper = s.get(f"{base}/api/self-tests/{test_id}", timeout=20).json()["data"]
        if paper["status"] in {"ready", "failed"}:
            break
        time.sleep(1)
    check("出题完成", paper.get("status") == "ready", f"{paper.get('question_count')} 道题")
    check("取卷不含答案", all("answer" not in it for it in paper.get("items", [])))
    if paper.get("items"):
        first = paper["items"][0]
        print(f"      示例题：{first['stem'][:44]}")
    answers = [{"item_id": it["item_id"], "answer": "D"} for it in paper.get("items", [])]
    r = s.post(f"{base}/api/self-tests/{test_id}/submit", json={"answers": answers}, timeout=40)
    res = r.json()["data"] if r.status_code == 200 else {}
    check("交卷判分", r.status_code == 200, f"得分 {res.get('score')} / 错题 {res.get('wrong_count')}")

    print("[6/9] 错题本")
    r = s.get(f"{base}/api/wrong-questions", timeout=20)
    wl = r.json()["data"] if r.status_code == 200 else {}
    check("错题入库", len(wl.get("items") or []) > 0, f"{len(wl.get('items') or [])} 条")
    check("薄弱度聚合", len(wl.get("weak_points") or []) > 0,
          "、".join(f"{w['knowledge_name']}×{w['wrong_count']}" for w in (wl.get("weak_points") or [])[:2]))
    if wl.get("items"):
        wid = wl["items"][0]["wrong_id"]
        detail = s.get(f"{base}/api/wrong-questions/{wid}", timeout=20).json()["data"]
        check("错题详情带选项", len(detail.get("options") or []) >= 2,
              f"{len(detail.get('options') or [])} 个选项")
        r = s.post(f"{base}/api/wrong-questions/{wid}/retry",
                   json={"answer": detail.get("correct_answer", "")}, timeout=20)
        check("重做判分", r.status_code == 200,
              f"连对 {r.json()['data'].get('correct_streak')} 次")

    print("[7/9] 图形化思维导图")
    r = s.post(f"{base}/api/sessions/{sid}/mindmap/build", timeout=40)
    check("导图生成", r.status_code == 200)
    tree = s.get(f"{base}/api/sessions/{sid}/mindmap", timeout=20).json()["data"]
    nodes = tree.get("nodes") or []
    check("导图读取", len(nodes) > 0, f"{len(nodes)} 个节点")
    leaves = [n for n in nodes if n.get("level") == 3]
    with_page = [n for n in leaves if n.get("evidence_page")]
    check("叶子节点带出处页码", len(with_page) > 0,
          f"{len(with_page)}/{len(leaves)} 个有页码")

    print("[8/9] 导出三格式")
    for fmt in ("docx", "md", "tex"):
        r = s.get(f"{base}/api/sessions/{sid}/export", params={"fmt": fmt}, timeout=60)
        check(f"导出 {fmt}", r.status_code == 200, f"{len(r.content)} 字节")

    print("[9/9] 问答（材料内）")
    r = s.post(f"{base}/api/chat/ask", json={"question": "等价类划分是什么"}, timeout=120)
    if r.status_code == 200:
        ans = r.json()["data"]
        check("问答可用", bool(ans.get("answer")), f"{len(ans.get('evidence') or [])} 条出处")
        print(f"      {ans['answer'][:70]}")
    else:
        check("问答可用", False, f"HTTP {r.status_code}")

    print("\n" + "=" * 66)
    print("生产环境学习闭环验收通过" if passed else "存在失败项，见上方 FAIL")
    print("=" * 66)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
