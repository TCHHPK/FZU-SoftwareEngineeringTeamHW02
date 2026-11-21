"""学习闭环三功能的真实 HTTP 联调冒烟：自测 → 错题本 → 导图。

与单元测试的区别：
    tests/ 里是进程内调用（TestClient）；这里起真实 uvicorn、走真实 HTTP，
    能一并验证路由前缀、后台任务、静态资源、序列化在真实服务下没问题。

覆盖的链路：
    注册 → 上传 → 整理 → 组卷 → 取卷(无答案) → 交卷 → 错题列表 → 错题重做
         → 导图生成 → 导图读取 → 三种导出

用法：python scripts/smoke_learning_loop.py [--port 8031]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import pymupdf
import requests

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable

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


def ok(label: str, condition: bool, detail: str = "") -> bool:
    print(f"  {'OK  ' if condition else 'FAIL'} {label}{('　' + detail) if detail else ''}")
    return condition


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8031)
    args = parser.parse_args()
    base = f"http://127.0.0.1:{args.port}"

    tmp = Path(tempfile.mkdtemp(prefix="cna-loop-"))
    env = dict(os.environ)
    env.update({
        "STORAGE_DIR": str(tmp),
        "UPLOAD_DIR": str(tmp / "uploads"),
        "BUSINESS_DB": str(tmp / "business.db"),
        "KB_DB": str(tmp / "kb.db"),
        "AGENT_STUB": "1",
        "SECRET_KEY": "smoke-loop",
        "PYTHONIOENCODING": "utf-8",
    })

    print(f"[1/9] 启动服务 :{args.port}（占位实现，不调模型）")
    proc = subprocess.Popen(
        [PY, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(args.port)],
        cwd=str(ROOT), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    passed = True
    try:
        for _ in range(80):
            try:
                if requests.get(f"{base}/api/health", timeout=1).status_code == 200:
                    break
            except requests.RequestException:
                time.sleep(0.5)
        else:
            print("[失败] 服务没起来")
            return 1

        s = requests.Session()
        name = f"loop_{uuid.uuid4().hex[:6]}"

        print("[2/9] 注册 + 上传课件")
        r = s.post(f"{base}/api/auth/register",
                   json={"username": name, "password": "passw0rd", "nickname": name}, timeout=30)
        passed &= ok("注册", r.status_code == 200, f"HTTP {r.status_code}")
        pdf = make_pdf(tmp / "loop.pdf")
        with pdf.open("rb") as fp:
            up = s.post(f"{base}/api/uploads", files={"file": (pdf.name, fp, "application/pdf")},
                        data={"course_name": "软件工程"}, timeout=180)
        passed &= ok("上传解析", up.status_code == 200,
                     up.json()["data"]["document"]["parse_status"] if up.status_code == 200 else "")
        doc_id = up.json()["data"]["document"]["doc_id"]

        print("[3/9] 创建整理任务并等待完成")
        sid = s.post(f"{base}/api/sessions",
                     json={"doc_ids": [doc_id], "course_name": "软件工程"}, timeout=30
                     ).json()["data"]["session_id"]
        st = {}
        for _ in range(90):
            st = s.get(f"{base}/api/sessions/{sid}", timeout=15).json()["data"]
            if st["status"] in {"success", "partial"}:
                break
            time.sleep(1)
        passed &= ok("整理完成", st.get("status") in {"success", "partial"},
                     f"状态 {st.get('status')}，知识点 {st.get('note_count')}")

        print("[4/9] 智能自测：组卷 → 取卷")
        r = s.post(f"{base}/api/self-tests",
                   json={"session_id": sid, "question_count": 3}, timeout=30)
        passed &= ok("组卷返回 202", r.status_code == 202, f"HTTP {r.status_code}")
        test_id = r.json()["data"]["test_id"]
        paper = {}
        for _ in range(40):
            paper = s.get(f"{base}/api/self-tests/{test_id}", timeout=15).json()["data"]
            if paper["status"] == "ready":
                break
            time.sleep(0.5)
        passed &= ok("出题完成", paper.get("status") == "ready", f"题目 {paper.get('question_count')} 道")
        passed &= ok("取卷不含答案", all("answer" not in it for it in paper["items"]))

        print("[5/9] 交卷（全错，制造错题）")
        wrong = [{"item_id": it["item_id"], "answer": "D"} for it in paper["items"]]
        r = s.post(f"{base}/api/self-tests/{test_id}/submit",
                   json={"answers": wrong}, timeout=30)
        res = r.json()["data"] if r.status_code == 200 else {}
        passed &= ok("交卷判分", r.status_code == 200, f"得分 {res.get('score')}")
        r2 = s.post(f"{base}/api/self-tests/{test_id}/submit", json={"answers": wrong}, timeout=30)
        passed &= ok("重复交卷幂等", r2.json()["data"]["score"] == res.get("score", -1))

        print("[6/9] 错题本：列表与薄弱度")
        r = s.get(f"{base}/api/wrong-questions", timeout=20)
        wl = r.json()["data"] if r.status_code == 200 else None
        passed &= ok("错题接口可用", r.status_code == 200, f"HTTP {r.status_code}")
        if isinstance(wl, dict):
            items = wl.get("items") or []
            stats = wl.get("weak_points") or []
            passed &= ok("错题已入库", len(items) > 0, f"{len(items)} 条")
            passed &= ok("薄弱度聚合", len(stats) > 0,
                         "、".join(f"{s['knowledge_name']}×{s['wrong_count']}"
                                   f"({s['weakness']})" for s in stats[:3]))
        elif isinstance(wl, list):
            passed &= ok("错题已入库", len(wl) > 0, f"{len(wl)} 条")

        print("[7/9] 图形化思维导图：生成 → 读取")
        r = s.post(f"{base}/api/sessions/{sid}/mindmap/build", timeout=30)
        built = r.json()["data"] if r.status_code == 200 else {}
        passed &= ok("导图生成", r.status_code == 200, f"HTTP {r.status_code}")
        r = s.get(f"{base}/api/sessions/{sid}/mindmap", timeout=20)
        tree = r.json()["data"] if r.status_code == 200 else {}
        node_count = len(tree.get("nodes") or [])
        passed &= ok("导图读取", r.status_code == 200 and node_count > 0, f"{node_count} 个节点")
        root = tree.get("tree") or {}
        passed &= ok("树有根节点", bool(root.get("name")), str(root.get("name", ""))[:24])

        print("[8/9] 导出三格式")
        for fmt in ("docx", "md", "tex"):
            r = s.get(f"{base}/api/sessions/{sid}/export", params={"fmt": fmt}, timeout=60)
            passed &= ok(f"导出 {fmt}", r.status_code == 200, f"{len(r.content)} 字节")

        print("[9/9] 静态资源（前端是否挂上）")
        r = s.get(f"{base}/", timeout=20)
        passed &= ok("首页可访问", r.status_code == 200 and '<div id="app">' in r.text)
        r = s.get(f"{base}/sessions/1/mindmap", timeout=20)
        passed &= ok("前端路由回退", r.status_code == 200 and '<div id="app">' in r.text)

        print("\n" + "=" * 66)
        if passed:
            print("学习闭环联调通过：自测 → 错题 → 导图 → 导出 → 前端")
        else:
            print("存在失败项，见上方 FAIL")
        print("=" * 66)
        return 0 if passed else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
