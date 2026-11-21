"""智能自测接口的真实 HTTP 冒烟：起一个临时服务，按学生视角走完整闭环。

与 tests/test_self_test.py 的区别：
    测试用 TestClient（进程内调用），这里用真实 HTTP + 真实 uvicorn，
    能顺带验证路由前缀、后台任务、JSON 序列化在真实服务下没问题。

用法：python scripts/smoke_self_test.py [--port 8021]
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


def make_pdf(path: Path) -> Path:
    doc = pymupdf.open()
    for title, body in [
        ("第3章 软件测试", "本章讨论软件测试的基本概念与方法。"),
        ("3.1 等价类划分", "等价类划分把输入域划分为若干等价类，从每个等价类中取一个代表值设计用例。"),
        ("3.2 边界值分析", "边界值分析关注输入范围的边界，因为边界附近最容易出现缺陷。"),
        ("3.3 语句覆盖", "语句覆盖要求程序中的每条可执行语句至少执行一次。"),
    ]:
        page = doc.new_page()
        page.insert_text((60, 80), title, fontsize=16, fontname="china-s")
        page.insert_textbox(pymupdf.Rect(60, 110, 520, 760), body, fontsize=12, fontname="china-s")
    doc.save(str(path))
    doc.close()
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8021)
    args = parser.parse_args()
    base = f"http://127.0.0.1:{args.port}"

    tmp = Path(tempfile.mkdtemp(prefix="cna-smoke-"))
    env = dict(os.environ)
    env.update({
        "STORAGE_DIR": str(tmp),
        "UPLOAD_DIR": str(tmp / "uploads"),
        "BUSINESS_DB": str(tmp / "business.db"),
        "KB_DB": str(tmp / "kb.db"),
        "AGENT_STUB": "1",
        "SECRET_KEY": "smoke-secret",
        "PYTHONIOENCODING": "utf-8",
    })

    print(f"[1/7] 启动服务 :{args.port}（占位实现，不调模型）")
    proc = subprocess.Popen(
        [PY, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(args.port)],
        cwd=str(ROOT), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(60):
            try:
                if requests.get(f"{base}/api/health", timeout=1).status_code == 200:
                    break
            except requests.RequestException:
                time.sleep(0.5)
        else:
            print("[失败] 服务没起来")
            return 1
        print("      服务就绪")

        s = requests.Session()
        name = f"smoke_{uuid.uuid4().hex[:6]}"

        print("[2/7] 注册 + 上传课件")
        r = s.post(f"{base}/api/auth/register",
                   json={"username": name, "password": "passw0rd", "nickname": name}, timeout=30)
        assert r.status_code == 200, r.text
        pdf = make_pdf(tmp / "quiz.pdf")
        with pdf.open("rb") as fp:
            up = s.post(f"{base}/api/uploads", files={"file": (pdf.name, fp, "application/pdf")},
                        data={"course_name": "软件工程"}, timeout=120)
        assert up.status_code == 200, up.text
        doc_id = up.json()["data"]["document"]["doc_id"]
        print(f"      解析 {up.json()['data']['document']['parse_status']}，doc_id={doc_id}")

        print("[3/7] 创建整理任务并等待完成")
        r = s.post(f"{base}/api/sessions",
                   json={"doc_ids": [doc_id], "course_name": "软件工程"}, timeout=30)
        session_id = r.json()["data"]["session_id"]
        for _ in range(60):
            st = s.get(f"{base}/api/sessions/{session_id}", timeout=10).json()["data"]
            if st["status"] in {"success", "partial"}:
                break
            time.sleep(1)
        print(f"      任务 {session_id} 状态：{st['status']}，知识点 {st['note_count']} 个")
        assert st["status"] in {"success", "partial"}

        print("[4/7] 组卷")
        r = s.post(f"{base}/api/self-tests",
                   json={"session_id": session_id, "question_count": 3}, timeout=30)
        assert r.status_code == 202, r.text
        test_id = r.json()["data"]["test_id"]
        print(f"      test_id={test_id}，状态 {r.json()['data']['status']}")

        print("[5/7] 取卷（应无答案）")
        paper = None
        for _ in range(30):
            paper = s.get(f"{base}/api/self-tests/{test_id}", timeout=15).json()["data"]
            if paper["status"] == "ready":
                break
            time.sleep(0.5)
        assert paper["status"] == "ready", f"出题未完成：{paper['status']}"
        assert all("answer" not in it for it in paper["items"]), "取卷泄露了答案"
        print(f"      {paper['question_count']} 道题，均未下发答案")
        for it in paper["items"][:2]:
            print(f"      · [{it['knowledge_name']}] {it['stem'][:42]}")

        print("[6/7] 交卷（故意答错以触发错题回填）")
        wrong = [{"item_id": it["item_id"], "answer": "D"} for it in paper["items"]]
        r = s.post(f"{base}/api/self-tests/{test_id}/submit",
                   json={"answers": wrong}, timeout=30)
        assert r.status_code == 200, r.text
        res = r.json()["data"]
        print(f"      得分 {res['score']}/{res['total_score']}，对 {res['correct_count']} 题，"
              f"错题回填 {res['wrong_count']} 条")

        print("[7/7] 幂等：重复交卷")
        r2 = s.post(f"{base}/api/self-tests/{test_id}/submit", json={"answers": wrong}, timeout=30)
        assert r2.json()["data"]["score"] == res["score"], "重复提交改变了分数"
        print("      分数未变，幂等成立")

        print("\n" + "=" * 62)
        print("智能自测闭环通过：组卷 → 取卷(无答案) → 交卷 → 判分 → 错题回填 → 幂等")
        print(f"接口文档：{base}/docs")
        print("=" * 62)
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
