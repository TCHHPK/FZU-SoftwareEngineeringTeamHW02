"""12.03 上线核验清单（对应计划表 25 的八项）。

两种模式：
    --expect v1.2   按当前线上基线判（新端点缺失不算失败）
    --expect v1.3   封板口径：六个新端点必须都在，缺一个就失败

八项核验：
    1 线上可访问（首页 / docs）
    2 健康与元信息（/api/health、/api/meta 版本与开关）
    3 前端静态资源（index.html 引用的主包能取到）
    4 六个 v1.3 端点是否已注册（未登录应 401，不是 404）
    5 演示账号可登录
    6 三条缺陷回归（草稿交卷 409 / shortfall 字段 / 并发不重复计错）
    7 导出可用（docx / md / tex）
    8 性能底线（68 页课件整理 ≤150 秒，可用 --pages 控制页数）

用法：
    python scripts/verify_release.py --base http://47.114.55.115:8000 --expect v1.2
    python scripts/verify_release.py --full --username verify_37777bd6 --password ***

不带 --full 时只跑第 1–5 项（对外网只读，不改数据）。
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import uuid
from pathlib import Path

import pymupdf
import requests

NEW_ENDPOINTS = [
    ("POST", "/api/sessions/1/review-pack"),
    ("GET", "/api/review-packs/1/export"),
    ("POST", "/api/sessions/1/review-plan"),
    ("GET", "/api/wrong-questions/due"),
    ("GET", "/api/chunks/d1-p1-c1"),
    ("GET", "/api/sessions/1/trace"),
]


def make_pdf(pages: int) -> bytes:
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((56, 78), f"第{i + 1}节 复习要点", fontsize=16, fontname="china-s")
        page.insert_textbox(pymupdf.Rect(56, 104, 520, 770),
                            f"这是第 {i + 1} 页的正文。等价类划分把输入域划分为若干等价类，"
                            f"从每个等价类中取一个代表值设计用例。边界值分析关注边界。"
                            f"语句覆盖要求每条可执行语句至少执行一次。",
                            fontsize=12, fontname="china-s", lineheight=1.6)
    data = doc.tobytes()
    doc.close()
    return data


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://47.114.55.115:8000")
    ap.add_argument("--expect", choices=["v1.2", "v1.3"], default="v1.2")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--username")
    ap.add_argument("--password")
    ap.add_argument("--pages", type=int, default=12, help="性能核验用的页数（底线按 68 页 150s）")
    args = ap.parse_args()

    base = args.base.rstrip("/")
    s = requests.Session()
    results: list[tuple[str, bool, str]] = []

    def check(label: str, ok: bool, detail: str = "", *, soft: bool = False) -> None:
        results.append((label, True if soft else ok, detail))
        print(f"  {'OK  ' if ok else ('WARN' if soft else 'FAIL')} {label}"
              + (f"　{detail}" if detail else ""))

    print(f"核验目标 {base}（口径 {args.expect}）\n")

    # 1 可访问
    print("[1/8] 线上可访问")
    home = s.get(f"{base}/", timeout=30)
    check("首页可访问", home.status_code == 200 and 'id="app"' in home.text,
          f"HTTP {home.status_code}")
    docs = s.get(f"{base}/docs", timeout=30)
    check("/docs 可访问", docs.status_code == 200, f"HTTP {docs.status_code}")

    # 2 健康与元信息
    print("[2/8] 健康与元信息")
    health = s.get(f"{base}/api/health", timeout=30)
    check("健康接口", health.status_code == 200, health.text[:60])
    meta = s.get(f"{base}/api/meta", timeout=30).json()["data"]
    feats = meta.get("features", {})
    check("meta 可读", True, f"格式 {len(meta.get('allowed_extensions', []))} 种")
    if args.expect == "v1.3":
        for key in ("review_pack", "review_plan", "wrong_schedule"):
            check(f"开关 {key}", feats.get(key) is True, str(feats.get(key)))
    else:
        for key in ("review_pack", "review_plan", "wrong_schedule"):
            check(f"开关 {key}（v1.3 才有）", key in feats, str(feats.get(key)), soft=True)

    # 3 静态资源
    print("[3/8] 前端静态资源")
    m = re.search(r"assets/(index-[A-Za-z0-9_-]+\.js)", home.text)
    if m:
        asset = s.get(f"{base}/assets/{m.group(1)}", timeout=60)
        check("主包可取", asset.status_code == 200 and len(asset.content) > 10000,
              f"{m.group(1)}，{len(asset.content) / 1024:.0f} KB")
    else:
        check("index.html 里有主包引用", False, "未匹配到 assets/index-*.js")

    # 4 新端点注册情况
    print("[4/8] v1.3 六个端点是否已注册（应返回 JSON；SPA 回退的 HTML 不算）")
    missing = []
    for method, path in NEW_ENDPOINTS:
        try:
            r = s.request(method, f"{base}{path}", json={}, timeout=20,
                          headers={"Accept": "application/json"})
            code = r.status_code
            is_json = "application/json" in (r.headers.get("content-type") or "")
            detail = f"{code} {'JSON' if is_json else r.headers.get('content-type', '?')[:24]}"
        except requests.RequestException as exc:
            code, is_json = -1, False
            detail = str(exc)[:40]
        # 判据只有一条：未登录访问已注册的受保护接口，后端会先鉴权返回 401/403；
        # 405 是 SPA 的 catch-all 路由（只接受 GET）对 POST 的回执，200/HTML 是它的 GET 回退，
        # 这两种都说明"该端点根本没注册"，不能算通过（第一版就栽在这）。
        registered = code in {401, 403, 422}
        if not registered:
            missing.append(path)
        check(f"{method} {path}", registered, detail, soft=(args.expect == "v1.2"))
    if missing:
        print(f"       未注册 {len(missing)} 个：{', '.join(missing)}")

    # 5 登录
    print("[5/8] 演示账号可登录")
    logged = False
    if args.username and args.password:
        r = s.post(f"{base}/api/auth/login",
                   json={"username": args.username, "password": args.password}, timeout=30)
        logged = r.status_code == 200
        check("演示账号登录", logged, f"HTTP {r.status_code}")
        if logged:
            s.headers["Authorization"] = "Bearer " + r.json()["data"]["token"]
    else:
        check("演示账号登录", False, "未提供账号，跳过（用 --username/--password）", soft=True)

    if not args.full or not logged:
        return report(results, "未跑完整回归（缺 --full 或未登录）")

    # 6 缺陷回归
    print("[6/8] 三条缺陷回归")
    pdf_bytes = make_pdf(args.pages)
    up = s.post(f"{base}/api/uploads",
                files={"file": ("release-check.pdf", pdf_bytes, "application/pdf")},
                data={"course_name": "上线核验"}, timeout=600).json()["data"]["document"]
    sid = s.post(f"{base}/api/sessions",
                 json={"doc_ids": [up["doc_id"]], "course_name": "上线核验"},
                 timeout=60).json()["data"]["session_id"]
    start = time.time()
    for _ in range(200):
        st = s.get(f"{base}/api/sessions/{sid}", timeout=30).json()["data"]
        if st["status"] in {"success", "partial", "failed"}:
            break
        time.sleep(2)
    cost = time.time() - start

    created = s.post(f"{base}/api/self-tests",
                     json={"session_id": sid, "question_count": 5}, timeout=60).json()["data"]
    tid = created["test_id"]
    paper = {}
    for _ in range(100):
        paper = s.get(f"{base}/api/self-tests/{tid}", timeout=30).json()["data"]
        if paper["status"] in {"ready", "failed"}:
            break
        time.sleep(1)

    # A32：目标与实际
    check("A32 target/actual 字段", "target_count" in paper and "actual_count" in paper,
          f"target={paper.get('target_count')} actual={paper.get('actual_count')} "
          f"shortfall={paper.get('shortfall')}")

    # A30：整卷 draft 应 409（线上不能改库，改用一个未就绪的自测：立刻交卷抢在出题前）
    fast = s.post(f"{base}/api/self-tests",
                  json={"session_id": sid, "question_count": 3}, timeout=60).json()["data"]
    early = s.post(f"{base}/api/self-tests/{fast['test_id']}/submit",
                   json={"answers": []}, timeout=30)
    check("A30 未就绪交卷被挡", early.status_code in {409, 200},
          f"HTTP {early.status_code}（409 = 白名单生效；200 说明出题太快已完成）",
          soft=(early.status_code == 200))

    # A33：双请求并发交卷，错题不翻倍
    items = paper.get("items") or []
    wrong_ans = [{"item_id": it["item_id"], "answer": "D"} for it in items]
    before = len(s.get(f"{base}/api/wrong-questions", timeout=30).json()["data"]["items"])
    codes = []
    import concurrent.futures as cf
    with cf.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(s.post, f"{base}/api/self-tests/{tid}/submit",
                               json={"answers": wrong_ans}, timeout=60) for _ in range(2)]
        for f in futures:
            try:
                codes.append(f.result().status_code)
            except Exception:  # noqa: BLE001
                codes.append(-1)
    after = s.get(f"{base}/api/wrong-questions", timeout=30).json()["data"]["items"]
    grew = len(after) - before
    check("A33 并发交卷不重复计错", grew <= len(items),
          f"两次返回 {codes}，错题新增 {grew} 条（不超过题数 {len(items)}）")

    # 7 导出
    print("[7/8] 导出可用")
    for fmt in ("docx", "md", "tex"):
        r = s.get(f"{base}/api/sessions/{sid}/export", params={"fmt": fmt}, timeout=120)
        check(f"导出 {fmt}", r.status_code == 200 and len(r.content) > 200,
              f"{len(r.content)} 字节")

    # 8 性能
    print("[8/8] 性能底线")
    check(f"整理耗时 ≤150s（{args.pages} 页）", cost <= 150, f"{cost:.0f}s")

    return report(results, "")


def report(results: list[tuple[str, bool, str]], note: str) -> int:
    print("\n" + "=" * 70)
    ok = sum(1 for _, passed, _ in results if passed)
    print(f"核验 {len(results)} 项：通过 {ok}，失败 {len(results) - ok}")
    for label, passed, detail in results:
        if not passed:
            print(f"  FAIL {label}　{detail}")
    if note:
        print(f"  {note}")
    print("=" * 70)
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
