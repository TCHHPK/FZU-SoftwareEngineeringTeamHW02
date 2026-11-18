"""验证：两份材料对同一知识点解释冲突时，系统怎么处理。

章玲（答辩组）的问题：
    两个 PDF 对同一个知识点的解释不一样怎么办？意思不一样，是不是一定有一个错了？

两种冲突形态分别验证：
    A. 同名冲突：两份材料都有「开闭原则」，但定义互相矛盾（一份说"对修改开放"）。
    B. 异名冲突：表述成不同条目名，但内容指向同一个概念且互相矛盾。

观察：
    1. 最终笔记里有几条；
    2. 同名时保留哪一条（规则是"保留更长的定义"）；
    3. 证据是否把两份材料的出处都挂上；
    4. 有没有任何冲突提示（warnings）。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pymupdf
import requests

BASE = "http://127.0.0.1:8000"
COURSE = "冲突材料实验"
ACCOUNT = ("verify_37777bd6", "verify123")


def make_pdf(text: str, name: str) -> Path:
    path = Path.home() / name
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(50, 50, 540, 790), text, fontsize=11, fontname="china-s")
    doc.save(str(path))
    doc.close()
    return path


def upload(s: requests.Session, pdf: Path) -> int:
    with pdf.open("rb") as fp:
        r = s.post(f"{BASE}/api/uploads",
                   files={"file": (pdf.name, fp, "application/pdf")},
                   data={"course_name": COURSE}, timeout=180)
    r.raise_for_status()
    return r.json()["data"]["document"]["doc_id"]


def run(s: requests.Session, doc_ids: list[int]) -> dict:
    r = s.post(f"{BASE}/api/sessions",
               json={"doc_ids": doc_ids, "course_name": COURSE}, timeout=60)
    r.raise_for_status()
    sid = r.json()["data"]["session_id"]
    start = time.time()
    while time.time() - start < 240:
        time.sleep(2)
        st = s.get(f"{BASE}/api/sessions/{sid}", timeout=30).json()["data"]
        if st["status"] in {"success", "partial", "failed"}:
            break
    res = s.get(f"{BASE}/api/sessions/{sid}/result", timeout=60).json()["data"]
    res["_session_id"] = sid
    return res


def dump(res: dict, label: str) -> None:
    items = res.get("items") or []
    print(f"\n  --- {label}：{len(items)} 条，session #{res.get('_session_id')} ---")
    for it in items:
        definition = (it.get("definition") or "").replace("\n", " ")
        files = sorted({e.get("source_file") for e in it.get("evidence") or [] if e.get("source_file")})
        print(f"    · {it['name']}")
        print(f"      定义: {definition[:78]}")
        print(f"      出处: {files}（{len(it.get('evidence') or [])} 条证据）")
    warnings = res.get("warnings") or []
    print(f"    告警: {warnings if warnings else '无'}")


def main() -> int:
    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/login",
               json={"username": ACCOUNT[0], "password": ACCOUNT[1]}, timeout=40)
    if r.status_code != 200:
        print("登录失败:", r.status_code, r.text[:160])
        return 1
    s.headers["Authorization"] = "Bearer " + r.json()["data"]["token"]

    # A. 同名冲突：都叫「开闭原则」，含义相反
    a1 = make_pdf("13.2 基本设计原则\n开闭原则是指：软件实体应当对修改开放，对扩展关闭。"
                  "也就是说新增功能时应当修改已有代码。", "conflict-a1.pdf")
    a2 = make_pdf("13.2 基本设计原则（修订）\n开闭原则是指：软件实体应当对扩展开放，对修改关闭。"
                  "也就是说新增功能时不修改已有代码，而是通过扩展实现。", "conflict-a2.pdf")
    d1, d2 = upload(s, a1), upload(s, a2)
    dump(run(s, [d1, d2]), "A. 同名冲突（开闭原则，两份含义相反）")

    # B. 异名冲突：同一个概念被抽成不同条目名
    b1 = make_pdf("13.3 模块独立性\n耦合度衡量模块之间相互依赖的程度，耦合越高越好。",
                  "conflict-b1.pdf")
    b2 = make_pdf("13.3 模块独立性（讲义补充）\n耦合度衡量模块之间相互依赖的程度，耦合越低越好，"
                  "低耦合是设计目标。", "conflict-b2.pdf")
    d3, d4 = upload(s, b1), upload(s, b2)
    dump(run(s, [d3, d4]), "B. 异名冲突（耦合度含义相反）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
