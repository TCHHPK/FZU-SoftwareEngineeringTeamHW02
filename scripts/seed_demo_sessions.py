"""预生成演示数据：把几份真实课件的文字重排成小 PDF，跑完整整理流程。

为什么要预生成：
    1. 答辩现场不依赖上传（大文件走隧道会 100 秒超时）；
    2. 网络抖动时可直接展示历史结果，是最稳的兜底；
    3. 每个任务都有真实模型产出、真实出处、真实自评分数。

用法：
    python scripts/seed_demo_sessions.py                 # 默认打 3 份
    python scripts/seed_demo_sessions.py --base http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT.parent
DEMO_DIR = DESKTOP / "演示课件"
ACCOUNT = ("verify_37777bd6", "verify123")

# (源课件, 起始页, 结束页, 课程名)
BATCHES = [
    ("9_副本.pdf", 1, 7, "软件工程 第13章 构件级设计"),
    ("8.pdf", 40, 46, "软件工程 第13章 体系结构设计"),
]


def build_sample(source: Path, start: int, end: int, out: Path) -> Path | None:
    """取真实课件的文字区间，重排成轻量 PDF（保留真实内容，去掉大图）。"""
    import pymupdf

    src = pymupdf.open(str(source))
    dst = pymupdf.open()
    written = 0
    for pno in range(start, min(end + 1, src.page_count)):
        text = src[pno].get_text("text").strip()
        if len(text) < 30:
            continue
        page = dst.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 545, 790), text,
                            fontsize=9.5, fontname="china-s")
        written += 1
    src.close()
    if not written:
        dst.close()
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    dst.save(str(out))
    dst.close()
    return out


def run_one(base: str, session: requests.Session, pdf: Path, course: str) -> bool:
    with pdf.open("rb") as fp:
        r = session.post(f"{base}/api/uploads",
                         files={"file": (pdf.name, fp, "application/pdf")},
                         data={"course_name": course}, timeout=300)
    if r.status_code != 200:
        print(f"    上传失败 HTTP {r.status_code}: {r.text[:120]}")
        return False
    doc = r.json()["data"]["document"]
    print(f"    解析 {doc['parse_status']}：{doc['page_count']} 页 / {doc['chunk_count']} 分块")

    r = session.post(f"{base}/api/sessions",
                     json={"doc_ids": [doc["doc_id"]], "course_name": course}, timeout=60)
    if r.status_code != 202:
        print(f"    建任务失败 HTTP {r.status_code}: {r.text[:120]}")
        return False
    sid = r.json()["data"]["session_id"]

    start = time.time()
    while time.time() - start < 300:
        time.sleep(3)
        st = session.get(f"{base}/api/sessions/{sid}", timeout=30).json()["data"]
        print(f"    [{int(time.time() - start):>3}s] {st['status']:<8} {st['progress']:>3}%  "
              f"{st.get('stage_message', '')}")
        if st["status"] in {"success", "partial", "failed"}:
            break
    if st["status"] == "failed":
        print(f"    失败：{st.get('error_message')}")
        return False

    res = session.get(f"{base}/api/sessions/{sid}/result", timeout=90).json()["data"]
    items = res.get("items") or []
    q = res.get("quality") or {}
    print(f"    结果：{len(items)} 个知识点，全部带出处={all(i.get('evidence') for i in items)}，"
          f"自评={q.get('total')}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    base = args.base.rstrip("/")

    s = requests.Session()
    r = s.post(f"{base}/api/auth/login",
               json={"username": ACCOUNT[0], "password": ACCOUNT[1]}, timeout=40)
    if r.status_code != 200:
        print(f"[失败] 登录 {ACCOUNT[0]} 失败：HTTP {r.status_code} {r.text[:120]}")
        return 1
    s.headers["Authorization"] = f"Bearer {r.json()['data']['token']}"
    print(f"[ok] 已登录 {ACCOUNT[0]}")

    ok = 0
    for name, start, end, course in BATCHES:
        source = DESKTOP / name
        if not source.exists():
            print(f"[跳过] 找不到 {source}")
            continue
        print(f"\n[..] 生成演示任务：{course}（源 {name} 第 {start}-{end} 页）")
        out = DEMO_DIR / f"演示-{course}.pdf"
        pdf = build_sample(source, start, end, out)
        if not pdf:
            print("     取不到文本，跳过")
            continue
        print(f"     样本：{pdf.name}（{pdf.stat().st_size / 1024:.0f} KB）")
        if run_one(base, s, pdf, course):
            ok += 1

    print(f"\n完成：成功 {ok} 个演示任务")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
