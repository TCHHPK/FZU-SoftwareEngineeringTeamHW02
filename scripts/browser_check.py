"""真实浏览器验收：导图交互 + 自测作答 + 错题重做。

为什么需要它：
    后端接口、前端构建、组件单测都过了，但「在浏览器里点得动」是另一件事。
    导图的缩放/拖动/点节点、错题的重做单选、自测的交卷渲染，
    都只有真浏览器能验证。

做法：
    1. 起一个临时 uvicorn（隔离存储、占位实现，不花钱）；
    2. 用 requests 通过 API 造好数据（用户/任务/自测/错题/导图），保证页面有内容；
    3. Playwright 驱动本机 Chrome 逐页操作并断言，失败处截图留证。

用法：python scripts/browser_check.py [--port 8051]
依赖：pip install playwright（用 channel="chrome"，不下载浏览器）
"""

from __future__ import annotations

import argparse
import os
import re
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
SHOTS = ROOT.parent / "验收截图-浏览器"

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


def seed(base: str, tmp: Path) -> dict:
    """造数据：返回用户名、session_id、test_id。"""
    s = requests.Session()
    name = f"browser_{uuid.uuid4().hex[:6]}"
    s.post(f"{base}/api/auth/register",
           json={"username": name, "password": "passw0rd", "nickname": name}, timeout=30).raise_for_status()

    pdf = make_pdf(tmp / "browser.pdf")
    with pdf.open("rb") as fp:
        up = s.post(f"{base}/api/uploads", files={"file": (pdf.name, fp, "application/pdf")},
                    data={"course_name": "软件工程"}, timeout=180).json()
    doc_id = up["data"]["document"]["doc_id"]

    sid = s.post(f"{base}/api/sessions", json={"doc_ids": [doc_id], "course_name": "软件工程"},
                 timeout=30).json()["data"]["session_id"]
    for _ in range(90):
        st = s.get(f"{base}/api/sessions/{sid}", timeout=15).json()["data"]
        if st["status"] in {"success", "partial"}:
            break
        time.sleep(1)

    # 自测：组卷 → 交卷（故意错，制造错题）
    test_id = s.post(f"{base}/api/self-tests", json={"session_id": sid, "question_count": 3},
                     timeout=30).json()["data"]["test_id"]
    paper = {}
    for _ in range(40):
        paper = s.get(f"{base}/api/self-tests/{test_id}", timeout=15).json()["data"]
        if paper["status"] in {"ready", "failed"}:
            break
        time.sleep(0.5)
    wrong = [{"item_id": it["item_id"], "answer": "D"} for it in paper.get("items", [])]
    s.post(f"{base}/api/self-tests/{test_id}/submit", json={"answers": wrong}, timeout=30)

    # 导图：先生成一次，保证页面有内容可点
    s.post(f"{base}/api/sessions/{sid}/mindmap/build", timeout=30)
    return {"username": name, "password": "passw0rd", "session_id": sid, "test_id": test_id}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8051)
    args = parser.parse_args()
    base = f"http://127.0.0.1:{args.port}"

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[失败] 没装 playwright：pip install playwright")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="cna-browser-"))
    env = dict(os.environ)
    env.update({
        "STORAGE_DIR": str(tmp), "UPLOAD_DIR": str(tmp / "uploads"),
        "BUSINESS_DB": str(tmp / "business.db"), "KB_DB": str(tmp / "kb.db"),
        "AGENT_STUB": "1", "SECRET_KEY": "browser-check", "PYTHONIOENCODING": "utf-8",
    })

    print(f"[1/6] 启动服务 :{args.port}")
    proc = subprocess.Popen(
        [PY, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(args.port)],
        cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    passed = True
    try:
        for _ in range(80):
            try:
                if requests.get(f"{base}/api/health", timeout=1).status_code == 200:
                    break
            except requests.RequestException:
                time.sleep(0.5)

        print("[2/6] 造数据（任务 / 自测 / 错题 / 导图）")
        data = seed(base, tmp)
        print(f"      用户 {data['username']}，session {data['session_id']}，test {data['test_id']}")

        SHOTS.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                                      device_scale_factor=2, locale="zh-CN")
            page = ctx.new_page()

            def check(label: str, ok: bool, detail: str = "") -> None:
                nonlocal passed
                passed &= ok
                print(f"  {'OK  ' if ok else 'FAIL'} {label}{('　' + detail) if detail else ''}")

            print("[3/6] 登录")
            page.goto(f"{base}/login", wait_until="networkidle")
            page.fill('input:not([type="password"])', data["username"])
            page.fill('input[type="password"]', data["password"])
            page.click('button:has-text("登录")')
            page.wait_for_timeout(2500)
            check("登录后离开登录页", "/login" not in page.url, page.url.split("/")[-1] or "首页")

            print("[4/6] 图形化思维导图：渲染 + 缩放 + 点节点")
            page.goto(f"{base}/sessions/{data['session_id']}/mindmap", wait_until="networkidle")
            page.wait_for_timeout(1500)
            svg = page.locator("svg").first
            check("导图 SVG 已渲染", svg.count() > 0)

            # 节点是 <g class="mindmap-node">；折叠按钮是它内部的 .collapse-icon。
            # 第一版用 "svg circle/rect" 取节点，结果点中了折叠圆点，整棵树被收起。
            nodes = page.locator(".mindmap-node")
            check("导图有节点元素", nodes.count() > 0, f"{nodes.count()} 个节点")

            # 先全部展开，保证叶子节点可见可点
            try:
                page.get_by_role("button", name="全部展开").click(timeout=3000)
                page.wait_for_timeout(400)
            except Exception:
                pass

            page.screenshot(path=str(SHOTS / "01-导图初始.png"), full_page=False)

            # 缩放：比较 SVG 内层 transform 的 scale
            inner = page.locator("svg g[transform*='scale']").first
            before = inner.get_attribute("transform") or ""
            page.get_by_role("button", name=re.compile("放大")).click()
            page.wait_for_timeout(500)
            after = inner.get_attribute("transform") or ""
            check("缩放按钮生效", before != after, f"{before[:24]} → {after[:24]}")
            page.screenshot(path=str(SHOTS / "02-导图放大后.png"), full_page=False)

            # 只点叶子节点（没有 .collapse-icon 的那些），根/章节节点本来就没有页码
            leaves = page.locator(".mindmap-node").filter(has_not=page.locator(".collapse-icon"))
            leaf_count = leaves.count()
            check("存在叶子知识点节点", leaf_count > 0, f"{leaf_count} 个")
            leaf_has_page = False
            clicked_name = ""
            for i in range(min(leaf_count, 10)):
                try:
                    node = leaves.nth(i)
                    clicked_name = node.get_attribute("aria-label") or ""
                    node.click(timeout=2000)
                    page.wait_for_timeout(400)
                    panel = page.inner_text("body")
                    tail = panel.split("原文出处")[-1] if "原文出处" in panel else ""
                    if re.search(r"第\s*\d+\s*页", tail) and "未提供页码" not in tail:
                        leaf_has_page = True
                        break
                except Exception:
                    continue
            check("点叶子节点可看到出处页码", leaf_has_page, clicked_name.replace("选择节点：", ""))
            page.screenshot(path=str(SHOTS / "03-导图节点详情.png"), full_page=False)

            print("[5/6] 错题本：列表 + 重做")
            page.goto(f"{base}/wrong-book", wait_until="networkidle")
            page.wait_for_timeout(1200)
            rows = page.locator(".el-table__row")
            check("错题列表有数据", rows.count() > 0, f"{rows.count()} 行")
            page.screenshot(path=str(SHOTS / "04-错题本列表.png"), full_page=False)
            if rows.count() > 0:
                page.locator('button:has-text("查看")').first.click()
                page.wait_for_timeout(800)
                has_radio = page.locator(".el-radio").count() > 0
                check("重做界面渲染选项", has_radio, f"{page.locator('.el-radio').count()} 个选项")
                if has_radio:
                    page.locator(".el-radio").first.click()
                    page.locator('button:has-text("重做提交")').click()
                    page.wait_for_timeout(1200)
                    body = page.inner_text("body")
                    check("重做后有判分反馈",
                          ("答对" in body) or ("答错" in body) or ("连对" in body))
                    page.screenshot(path=str(SHOTS / "05-错题重做反馈.png"), full_page=False)

            print("[6/6] 智能自测页可打开")
            page.goto(f"{base}/self-tests", wait_until="networkidle")
            page.wait_for_timeout(1200)
            body = page.inner_text("body")
            check("自测页包含任务选择", "任务" in body or "自测" in body)
            check("已关闭模拟数据提示", "模拟数据" not in body, "无「模拟数据」标签")
            page.screenshot(path=str(SHOTS / "06-自测页.png"), full_page=False)

            browser.close()

        print("\n" + "=" * 66)
        print("浏览器验收通过" if passed else "存在失败项，见上方 FAIL")
        print(f"截图目录：{SHOTS}")
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
