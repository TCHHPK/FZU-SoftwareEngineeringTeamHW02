"""线上真实全流程验证：注册 → 上传真实课件 → 整理 → 结果 → 导出。

这不是本地测试，而是直接打生产地址，验证「老师打开后能不能用」。
会真实消耗模型额度（单章约几分钱）。

用法：
    python scripts/online_verify.py            # 默认验证线上服务器
    python scripts/online_verify.py --base http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_BASE = "http://47.114.55.115:8000"
ROOT = Path(__file__).resolve().parents[1]


def build_sample_pdf() -> Path:
    """从 9_副本.pdf 取几页真实内容，拼一份小课件（避免上传 27MB 大文件）。"""
    import pymupdf

    source = ROOT.parent / "9_副本.pdf"
    out = Path.home() / "online_verify_sample.pdf"

    if source.exists():
        src = pymupdf.open(str(source))
        dst = pymupdf.open()
        # 挑正文页（第 2 页起），跳过封面
        for pno in range(1, min(7, src.page_count)):
            dst.insert_pdf(src, from_page=pno, to_page=pno)
        dst.save(str(out))
        dst.close()
        src.close()
        return out

    # 没有真实课件时退化为生成一份，保证脚本仍可运行
    doc = pymupdf.open()
    for title, body in [
        ("第13章 构件级设计", "构件是系统中可部署的单元，对象是运行时实例。"),
        ("13.1 什么是构件", "构件封装实现并通过接口对外提供服务，具有可替换性。"),
        ("13.2 基本设计原则", "开闭原则要求模块对扩展开放、对修改封闭。"),
    ]:
        page = doc.new_page()
        page.insert_text((60, 80), title, fontsize=17, fontname="china-s")
        page.insert_textbox(pymupdf.Rect(60, 110, 520, 760), body,
                            fontsize=12, fontname="china-s")
    doc.save(str(out))
    doc.close()
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--timeout", type=int, default=420, help="等待整理完成的最长秒数")
    args = parser.parse_args()
    base = args.base.rstrip("/")

    s = requests.Session()
    ok = True

    def step(msg: str) -> None:
        print(f"\n[{msg}]")

    def check(cond: bool, msg: str) -> None:
        nonlocal ok
        print(f"  {'OK  ' if cond else 'FAIL'} {msg}")
        if not cond:
            ok = False

    step("1/7 健康检查")
    try:
        h = s.get(f"{base}/api/health", timeout=10).json()
        check(h.get("status") == "ok", f"/api/health -> {h}")
    except Exception as exc:  # noqa: BLE001
        print(f"  无法连接 {base}：{exc}")
        return 1

    meta = s.get(f"{base}/api/meta", timeout=10).json()["data"]
    check(meta["features"]["quality_eval"] is True, f"质量自评已开启 {meta['features']}")
    check(len(meta["allowed_extensions"]) >= 5,
          f"支持 {len(meta['allowed_extensions'])} 种格式")

    step("2/7 前端页面")
    r = s.get(f"{base}/", timeout=10)
    check(r.status_code == 200 and '<div id="app">' in r.text, "首页返回 Vue 应用")
    r2 = s.get(f"{base}/sessions/1/result", timeout=10)
    check(r2.status_code == 200 and '<div id="app">' in r2.text, "前端路由回退正常")

    step("3/7 注册账号")
    username = f"verify_{uuid.uuid4().hex[:8]}"
    r = s.post(f"{base}/api/auth/register",
               json={"username": username, "password": "verify123", "nickname": "线上验证"},
               timeout=20)
    check(r.status_code == 200, f"注册 {username} -> HTTP {r.status_code}")
    if r.status_code != 200:
        print("   ", r.text[:300])
        return 1
    token = r.json()["data"]["token"]
    s.headers["Authorization"] = f"Bearer {token}"

    step("4/7 上传真实课件")
    pdf = build_sample_pdf()
    size_kb = pdf.stat().st_size / 1024
    with pdf.open("rb") as fp:
        r = s.post(f"{base}/api/uploads", files={"file": (pdf.name, fp, "application/pdf")},
                   data={"course_name": "软件工程（线上验证）"}, timeout=180)
    if r.status_code != 200:
        check(False, f"上传失败 HTTP {r.status_code}: {r.text[:300]}")
        return 1
    doc = r.json()["data"]["document"]
    check(doc["parse_status"] == "success",
          f"解析成功：{doc['page_count']} 页 / {doc['chunk_count']} 分块（{size_kb:.0f} KB）")
    check(doc["chunk_count"] > 0, "产生了文本分块")

    step("5/7 发起整理任务（真实调用模型）")
    r = s.post(f"{base}/api/sessions",
               json={"doc_ids": [doc["doc_id"]], "course_name": "软件工程（线上验证）"},
               timeout=30)
    check(r.status_code == 202, f"创建任务 HTTP {r.status_code}")
    session_id = r.json()["data"]["session_id"]
    print(f"      session_id = {session_id}，开始轮询（最多 {args.timeout}s）…")

    started = time.time()
    status = {}
    while time.time() - started < args.timeout:
        time.sleep(3)
        status = s.get(f"{base}/api/sessions/{session_id}", timeout=15).json()["data"]
        elapsed = int(time.time() - started)
        print(f"      [{elapsed:>3}s] {status['status']:<8} {status['progress']:>3}%  "
              f"{status.get('stage_message', '')}")
        if status["status"] in {"success", "partial", "failed"}:
            break

    check(status.get("status") in {"success", "partial"},
          f"任务终态 {status.get('status')}（耗时 {int(time.time() - started)}s）")
    if status.get("status") == "failed":
        print("      失败原因：", status.get("error_message"))
        return 1

    step("6/7 检查结果质量")
    r = s.get(f"{base}/api/sessions/{session_id}/result", timeout=30)
    check(r.status_code == 200, f"结果接口 HTTP {r.status_code}")
    data = r.json()["data"]
    items = data.get("items") or []
    check(len(items) > 0, f"生成 {len(items)} 个知识点")
    with_ev = [i for i in items if i.get("evidence")]
    check(len(with_ev) == len(items), f"{len(with_ev)}/{len(items)} 条带原文出处")
    pages = sorted({e["page_num"] for i in items for e in i["evidence"] if e.get("page_num")})
    check(len(pages) >= 1, f"出处页码覆盖：{pages}")
    check(bool(data.get("key_points")), f"重点清单 {len(data.get('key_points') or [])} 条")
    check(bool(data.get("mindmap_text")), "文本思维导图已生成")
    q = data.get("quality")
    check(q is not None, f"质量自评：{q['total'] if q else '无'}")
    print(f"      丢弃条目数（防编造机制）：{data.get('dropped_items')}")
    for w in (data.get("warnings") or [])[:3]:
        print(f"      告警：{w}")
    if items:
        first = items[0]
        ev = (first.get("evidence") or [{}])[0]
        print(f"      示例：{first['name']}")
        print(f"            出处 第{ev.get('page_num')}页 / {ev.get('source_file')}")
        print(f"            引文 {str(ev.get('quote'))[:60]}…")

    step("7/7 导出")
    md = s.get(f"{base}/api/sessions/{session_id}/export", params={"fmt": "md"}, timeout=30)
    check(md.status_code == 200 and "【出处】" in md.text,
          f"Markdown 导出 {len(md.text)} 字符")
    tex = s.get(f"{base}/api/sessions/{session_id}/export", params={"fmt": "tex"}, timeout=30)
    check(tex.status_code == 200 and r"\end{document}" in tex.text,
          f"LaTeX 导出 {len(tex.text)} 字符")

    print("\n" + "=" * 66)
    if ok:
        print("线上全流程通过：老师打开后可以正常注册、上传、生成带出处的笔记并导出")
        print(f"验证账号：{username} / verify123   （任务 #{session_id} 已存入历史）")
    else:
        print("线上验证发现问题，见上方 FAIL 项")
    print("=" * 66)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
