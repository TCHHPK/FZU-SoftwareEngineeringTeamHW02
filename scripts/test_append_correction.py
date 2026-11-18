"""验证：追加材料后，前面材料里的错误会不会被纠正。

背景：章玲（答辩组）提问——新上传的材料加知识点或纠正前面材料的错误，
     最终产出的笔记会不会跟着变。这里用一个受控实验回答。

实验设计：
    材料一（故意写错）：构件是运行时实例；构件和对象是同一个概念。
    材料二（明确纠正）：构件不是运行时实例，是可部署单元；对象才是实例。

对比「只有材料一」与「追加材料二后」的知识点条目与定义。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pymupdf
import requests

BASE = "http://127.0.0.1:8000"
COURSE = "纠错实验课程"


def make_pdf(text: str, name: str) -> Path:
    path = Path.home() / name
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(50, 50, 540, 790), text, fontsize=11, fontname="china-s")
    doc.save(str(path))
    doc.close()
    return path


def upload(session: requests.Session, pdf: Path) -> int:
    with pdf.open("rb") as fp:
        r = session.post(f"{BASE}/api/uploads",
                         files={"file": (pdf.name, fp, "application/pdf")},
                         data={"course_name": COURSE}, timeout=180)
    r.raise_for_status()
    return r.json()["data"]["document"]["doc_id"]


def run(session: requests.Session, doc_ids: list[int]) -> int:
    r = session.post(f"{BASE}/api/sessions",
                     json={"doc_ids": doc_ids, "course_name": COURSE}, timeout=60)
    r.raise_for_status()
    sid = r.json()["data"]["session_id"]
    start = time.time()
    while time.time() - start < 240:
        time.sleep(2)
        st = session.get(f"{BASE}/api/sessions/{sid}", timeout=30).json()["data"]
        if st["status"] in {"success", "partial", "failed"}:
            break
    return sid


def show(session: requests.Session, sid: int, label: str) -> list[dict]:
    res = session.get(f"{BASE}/api/sessions/{sid}/result", timeout=60).json()["data"]
    items = res.get("items") or []
    print(f"\n  --- {label}：{len(items)} 条 ---")
    for it in items:
        definition = (it.get("definition") or "").replace("\n", " ")
        print(f"    · {it['name']}: {definition[:80]}")
    return items


def main() -> int:
    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/login",
               json={"username": "verify_37777bd6", "password": "verify123"}, timeout=40)
    if r.status_code != 200:
        print("登录失败:", r.status_code, r.text[:200])
        return 1
    s.headers["Authorization"] = "Bearer " + r.json()["data"]["token"]

    a = make_pdf("13.1 构件的基本概念\n构件是运行时实例。构件和对象是同一个概念，只是叫法不同。",
                 "err-a.pdf")
    d1 = upload(s, a)
    sid1 = run(s, [d1])
    first = show(s, sid1, "只有材料一")

    b = make_pdf("勘误说明\n纠正上一版材料的错误：构件不是运行时实例，构件是可部署的单元；"
                 "对象才是运行时实例。构件与对象不是同一个概念，构件通常大于类。",
                 "err-b.pdf")
    d2 = upload(s, b)
    old_ids = s.get(f"{BASE}/api/sessions/{sid1}", timeout=30).json()["data"]["doc_ids"]
    sid2 = run(s, [*old_ids, d2])
    second = show(s, sid2, "追加材料二之后")

    # 判定：是否存在「构件」条目，其定义里出现"可部署"（说明纠正被吸收）
    def find(items, name_kw):
        return [i for i in items if name_kw in i["name"]]

    print("\n  === 结论 ===")
    for label, items in (("材料一", first), ("合并后", second)):
        hits = find(items, "构件")
        for h in hits:
            d = (h.get("definition") or "")
            print(f"    {label} | {h['name']}: 含'可部署'={'可部署' in d} | "
                  f"含'运行时实例'={'运行时实例' in d}")

    new_only = [i["name"] for i in second if i["name"] not in {x["name"] for x in first}]
    print(f"    新增条目：{new_only if new_only else '无'}")
    print(f"    条目数：{len(first)} → {len(second)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
