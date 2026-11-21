"""对生产环境抓截图：用验收时创建的账号登录，拍导图与错题本。"""

from __future__ import annotations

import sys
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

BASE = "http://47.114.55.115:8000"
USER = sys.argv[1] if len(sys.argv) > 1 else ""
PASSWORD = "passw0rd"
OUT = Path(r"C:\Users\20378\Desktop\新建文件夹 (2)\验收截图-线上")

OUT.mkdir(parents=True, exist_ok=True)

if not USER:
    print("用法: python scripts/shot_prod.py <验收账号>")
    raise SystemExit(1)

s = requests.Session()
r = s.post(f"{BASE}/api/auth/login", json={"username": USER, "password": PASSWORD}, timeout=30)
if r.status_code != 200:
    print("登录失败:", r.status_code, r.text[:200])
    raise SystemExit(1)
s.headers["Authorization"] = "Bearer " + r.json()["data"]["token"]
sessions = s.get(f"{BASE}/api/sessions", timeout=20).json()["data"]
sid = sessions[0]["session_id"]
print(f"账号 {USER}，任务 #{sid}")

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2,
                              locale="zh-CN")
    page = ctx.new_page()

    page.goto(f"{BASE}/login", wait_until="networkidle")
    page.fill('input:not([type="password"])', USER)
    page.fill('input[type="password"]', PASSWORD)
    page.click('button:has-text("登录")')
    page.wait_for_timeout(2500)
    print("已登录")

    page.goto(f"{BASE}/sessions/{sid}/result", wait_until="networkidle")
    page.wait_for_timeout(1500)
    page.screenshot(path=str(OUT / "01-线上结果页.png"), full_page=False)
    print("  结果页 OK")

    page.goto(f"{BASE}/sessions/{sid}/mindmap", wait_until="networkidle")
    page.wait_for_timeout(1500)
    try:
        page.get_by_role("button", name="全部展开").click(timeout=3000)
        page.wait_for_timeout(400)
    except Exception:
        pass
    leaves = page.locator(".mindmap-node").filter(has_not=page.locator(".collapse-icon"))
    if leaves.count():
        leaves.first.click()
        page.wait_for_timeout(600)
    page.screenshot(path=str(OUT / "02-线上图形化导图.png"), full_page=False)
    print("  导图 OK")

    page.goto(f"{BASE}/wrong-book", wait_until="networkidle")
    page.wait_for_timeout(1200)
    page.screenshot(path=str(OUT / "03-线上错题本.png"), full_page=False)
    print("  错题本 OK")

    page.goto(f"{BASE}/self-tests", wait_until="networkidle")
    page.wait_for_timeout(1200)
    page.screenshot(path=str(OUT / "04-线上智能自测.png"), full_page=False)
    print("  自测页 OK")

    browser.close()

print(f"截图目录：{OUT}")
