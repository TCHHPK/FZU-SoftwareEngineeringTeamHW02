"""造发布会演示数据：一个干净账号 + 预置课件 + 整理任务 + 自测错题 + 导图。

为什么要有这个：
    演示当天最怕"临场上传一个大文件、等 100 秒、还失败"。预置好数据以后，
    主讲点开就是现成的：历史任务里有结果页、错题本有内容、导图能点。
    12.03 上线核验清单里「演示账号数据」这一项，就是跑这个脚本。

用法（线上）：
    python scripts/seed_demo.py --base http://47.114.55.115:8000 \
        --username verify_37777bd6 --password <密码>

    # 只在本地验证脚本能跑通（占位实现，不花钱）：
    python scripts/seed_demo.py --base http://127.0.0.1:8055 --stub
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from pathlib import Path

import pymupdf
import requests

DEMO_PAGES = [
    ("第3章 软件测试", "软件测试的目的是发现软件中的缺陷，验证软件是否满足需求。"
                     "测试不能证明软件没有错误，只能证明存在错误。"),
    ("3.1 等价类划分", "等价类划分把输入域划分为若干等价类，从每个等价类中取一个代表值设计用例。"
                     "有效等价类与无效等价类都需要覆盖。"),
    ("3.2 边界值分析", "边界值分析关注输入范围的边界，因为边界附近最容易出现缺陷。"
                     "对范围 [1,100]，应取 0、1、2、99、100、101 作为测试数据。"),
    ("3.3 语句覆盖", "语句覆盖要求程序中的每条可执行语句至少执行一次，是最弱的覆盖准则。"),
    ("3.4 判定覆盖", "判定覆盖要求每个判定的真、假分支都至少执行一次，强于语句覆盖。"),
    ("3.5 条件覆盖", "条件覆盖要求每个判定中的每个条件的可能取值都至少出现一次。"),
    ("3.6 路径覆盖", "路径覆盖要求覆盖程序中所有可能的执行路径，是最强的覆盖准则。"),
    ("3.7 黑盒与白盒", "黑盒测试不关心内部结构，白盒测试基于代码结构设计用例。"),
    ("第4章 需求工程", "需求工程包括需求获取、分析、规约、验证与需求管理五个活动。"),
    ("4.1 需求分类", "需求分为功能需求、非功能需求与领域需求三类。"),
    ("4.2 用例图", "用例图描述参与者与系统用例之间的关系，属于需求建模的一部分。"),
    ("4.3 需求评审", "需求评审的目的是尽早发现需求缺陷，降低后期返工成本。"),
]


def make_pdf(path: Path, pages: int) -> Path:
    doc = pymupdf.open()
    for title, body in DEMO_PAGES[:pages]:
        page = doc.new_page()
        page.insert_text((56, 78), title, fontsize=17, fontname="china-s")
        page.insert_textbox(pymupdf.Rect(56, 104, 520, 770), body, fontsize=12,
                            fontname="china-s", lineheight=1.6)
    doc.save(str(path))
    doc.close()
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--username", default="verify_37777bd6")
    ap.add_argument("--password", default="demo1234")
    ap.add_argument("--nickname", default="演示账号")
    ap.add_argument("--course", default="软件工程")
    ap.add_argument("--pages", type=int, default=12, help="预置课件页数（默认 12，控成本）")
    ap.add_argument("--questions", type=int, default=5)
    ap.add_argument("--stub", action="store_true", help="说明：本次对端是占位实现，仅验证流程")
    args = ap.parse_args()

    base = args.base.rstrip("/")
    s = requests.Session()
    print(f"[1/6] 目标 {base}（{'占位实现' if args.stub else '真实模型'}）")

    # 登录或注册
    r = s.post(f"{base}/api/auth/login",
               json={"username": args.username, "password": args.password}, timeout=30)
    if r.status_code != 200:
        r = s.post(f"{base}/api/auth/register",
                   json={"username": args.username, "password": args.password,
                         "nickname": args.nickname}, timeout=30)
        if r.status_code != 200:
            print(f"  [失败] 登录与注册都失败：{r.status_code} {r.text[:200]}")
            return 1
        print(f"  注册新账号 {args.username}")
    else:
        print(f"  复用已有账号 {args.username}")
    s.headers["Authorization"] = "Bearer " + r.json()["data"]["token"]

    # 预置课件
    tmp_pdf = Path(f"demo-{uuid.uuid4().hex[:6]}.pdf")
    make_pdf(tmp_pdf, args.pages)
    print(f"[2/6] 上传预置课件（{args.pages} 页，{tmp_pdf.stat().st_size / 1024:.0f} KB）")
    with tmp_pdf.open("rb") as fp:
        up = s.post(f"{base}/api/uploads", files={"file": (tmp_pdf.name, fp, "application/pdf")},
                    data={"course_name": args.course}, timeout=300)
    tmp_pdf.unlink(missing_ok=True)
    if up.status_code != 200:
        print(f"  [失败] 上传：{up.status_code} {up.text[:200]}")
        return 1
    doc = up.json()["data"]["document"]
    print(f"  doc_id={doc['doc_id']}，解析 {doc['parse_status']}，{doc['page_count']} 页")

    # 整理任务
    print("[3/6] 创建整理任务并等待完成（真实模型约 30–120 秒）")
    start = time.time()
    sid = s.post(f"{base}/api/sessions",
                 json={"doc_ids": [doc["doc_id"]], "course_name": args.course},
                 timeout=60).json()["data"]["session_id"]
    st = {}
    for _ in range(200):
        st = s.get(f"{base}/api/sessions/{sid}", timeout=30).json()["data"]
        if st["status"] in {"success", "partial", "failed"}:
            break
        time.sleep(2)
    cost = time.time() - start
    print(f"  状态 {st.get('status')}，耗时 {cost:.0f}s，知识点 {st.get('note_count')}")
    if st.get("status") == "failed":
        print("  [失败] 整理失败，演示数据不完整")
        return 1

    # 导图
    print("[4/6] 生成思维导图")
    r = s.post(f"{base}/api/sessions/{sid}/mindmap/build", timeout=120)
    tree = s.get(f"{base}/api/sessions/{sid}/mindmap", timeout=60).json().get("data") or {}
    print(f"  导图节点 {len(tree.get('nodes') or [])} 个（{r.status_code}）")

    # 自测 + 故意答错（造错题）
    print("[5/6] 组一张自测卷并故意答错，制造错题本数据")
    created = s.post(f"{base}/api/self-tests",
                     json={"session_id": sid, "question_count": args.questions}, timeout=60)
    if created.status_code not in (200, 202):
        print(f"  跳过自测：{created.status_code} {created.text[:150]}")
    else:
        tid = created.json()["data"]["test_id"]
        paper = {}
        for _ in range(80):
            paper = s.get(f"{base}/api/self-tests/{tid}", timeout=30).json()["data"]
            if paper["status"] in {"ready", "failed"}:
                break
            time.sleep(1)
        items = paper.get("items") or []
        if items:
            # 全部选 A，若正好是对的也认了——目标是让错题本里有东西
            answers = [{"item_id": it["item_id"], "answer": "A"} for it in items]
            res = s.post(f"{base}/api/self-tests/{tid}/submit",
                         json={"answers": answers}, timeout=60)
            data = res.json().get("data") or {}
            print(f"  交卷：得分 {data.get('score')}，错 {data.get('wrong_count')} 题")
        else:
            print(f"  题目未生成（status={paper.get('status')}）")

    # 汇总
    print("[6/6] 汇总")
    wrong = s.get(f"{base}/api/wrong-questions", timeout=30).json().get("data") or {}
    print(f"  账号：{args.username} / {args.password}")
    print(f"  任务：session_id={sid}（{st.get('status')}）")
    print(f"  错题：{len(wrong.get('items') or [])} 条，"
          f"薄弱知识点 {len(wrong.get('weak_points') or [])} 个")
    print(f"  结果页：{base}/sessions/{sid}/result")
    print(f"  导图页：{base}/sessions/{sid}/mindmap")
    print(f"  性能：整理 {cost:.0f}s（底线 150s）")
    return 0 if cost <= 150 else 1


if __name__ == "__main__":
    sys.exit(main())
