"""用无头浏览器给答辩 PPT 生成截图。

章玲（答辩组）需要能看到界面效果的截图，这个脚本自动完成：
    1. 登录页
    2. 上传页（课程可输入 + 支持格式）
    3. 历史任务（含补充材料按钮）
    4. 结果页全景（结构化笔记 + 出处角标 + 质量自评）
    5. 出处角标弹窗（展示原文引文，最有说服力的一张）
    6. 导出按钮区（Word / Markdown / LaTeX）
    7. 问答页：材料外问题的「未涉及」回答

前置：本机 8000 端口有服务在跑，且存在一个已完成的会话。
用法：python scripts/make_screenshots.py [--session 2]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
ACCOUNT = "verify_37777bd6"
PASSWORD = "verify123"
OUT_DIR = Path(r"C:\Users\20378\Desktop\新建文件夹 (2)\答辩截图")

VIEWPORT = {"width": 1440, "height": 900}


def shot(page, name: str, *, full: bool = False, note: str = "") -> None:
    path = OUT_DIR / f"{name}.png"
    page.screenshot(path=str(path), full_page=full)
    size = path.stat().st_size / 1024
    print(f"  [ok] {path.name:<34} {size:6.0f} KB  {note}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", type=int, default=2, help="用于截图的任务 ID")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        # 用本机已安装的 Chrome，避免下载 Playwright 自带浏览器
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport=VIEWPORT, device_scale_factor=2, locale="zh-CN")
        page = ctx.new_page()

        print("[1] 登录页")
        page.goto(f"{BASE}/login", wait_until="networkidle")
        page.wait_for_timeout(800)
        shot(page, "01-登录页", note="展示视觉设计与产品名")

        print("[2] 登录并进入上传页")
        page.fill('input[type="text"], input:not([type="password"])', ACCOUNT)
        page.fill('input[type="password"]', PASSWORD)
        page.click('button:has-text("登录")')
        page.wait_for_timeout(2500)
        page.goto(f"{BASE}/upload", wait_until="networkidle")
        page.wait_for_timeout(600)
        shot(page, "02-上传页", note="课程可输入 + 支持格式说明")

        print("[3] 历史任务列表")
        page.goto(f"{BASE}/sessions", wait_until="networkidle")
        page.wait_for_timeout(1200)
        shot(page, "03-历史任务", note="状态标签 + 补充材料入口")

        print("[4] 结果页全景")
        page.goto(f"{BASE}/sessions/{args.session}/result", wait_until="networkidle")
        page.wait_for_timeout(1500)
        shot(page, "04-结果页全景", full=True, note="结构化笔记 + 质量自评")

        print("[5] 出处角标弹窗")
        badge = page.query_selector(".el-tag")
        clicked = False
        for tag in page.query_selector_all(".el-tag"):
            text = (tag.inner_text() or "").strip()
            if text.startswith("第") and ("页" in text or "幻灯片" in text):
                tag.click()
                clicked = True
                break
        if clicked:
            page.wait_for_timeout(700)
            shot(page, "05-出处引文弹窗", note="点开出处的原文引文（最有说服力）")
        else:
            print("  [跳过] 没找到出处角标")

        print("[6] 导出按钮区")
        try:
            page.get_by_role("button", name="导出 Word").scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            page.screenshot(path=str(OUT_DIR / "06-三种导出格式.png"),
                            clip={"x": 0, "y": 0, "width": VIEWPORT["width"], "height": VIEWPORT["height"]})
            print(f"  [ok] 06-三种导出格式.png")
        except Exception as exc:  # noqa: BLE001
            print(f"  [跳过] 导出区截图失败：{exc}")

        print("[7] 问答页：材料外的问题")
        page.goto(f"{BASE}/chat", wait_until="networkidle")
        page.wait_for_timeout(800)
        try:
            page.fill('input[placeholder*="问题"]', "KNN 算法的核心思想是什么")
            page.get_by_role("button", name="发送").click()
            page.wait_for_timeout(9000)
            shot(page, "07-材料外问题不编造", note="如实回答「未涉及」")
        except Exception as exc:  # noqa: BLE001
            print(f"  [跳过] 问答截图失败：{exc}")

        ctx.close()
        browser.close()

    print(f"\n全部截图已保存到：{OUT_DIR}")
    for f in sorted(OUT_DIR.glob("*.png")):
        print(f"  {f.name:<34} {f.stat().st_size / 1024:6.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
