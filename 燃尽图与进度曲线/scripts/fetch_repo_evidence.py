# -*- coding: utf-8 -*-
"""拉取仓库证据，生成 data/commits.csv。

作用：
    进度曲线里的"实际完成日"不是凭回忆填的，而是按仓库提交、PR 合并时间判定的。
    本脚本把提交记录（含 UTC 与北京时间）存档，任何人都能复核某一天的完成度为什么这么算。

时区：
    GitHub 一律返回 UTC。北京时间 = UTC + 8。例如 PR #2 记为 2026-11-18T18:18Z，
    换算后是 11-19 02:18，所以"错题本后端"的完成日记为 11.19。

两种取数方式：
    1. 有本地克隆（推荐，不依赖 api.github.com 是否可达）：
       python scripts/fetch_repo_evidence.py --git D:\\repo\\FZU-SoftwareEngineeringTeamHW02
    2. 走 GitHub API（需要 HTTPS_PROXY 能通 api.github.com）：
       set HTTPS_PROXY=http://127.0.0.1:31180
       python scripts/fetch_repo_evidence.py

输出：
    data/commits.csv
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import ssl
import subprocess
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / "data" / "commits.csv"
REPO = "TCHHPK/FZU-SoftwareEngineeringTeamHW02"
API = f"https://api.github.com/repos/{REPO}"
CTX = ssl._create_unverified_context()  # 校园网/安全软件常替换证书链，抓公开数据时跳过校验


def to_bj(iso: str) -> tuple[str, str]:
    """ISO 时间 → (UTC 字符串, 北京时间字符串)。"""
    t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    utc = t.astimezone(dt.timezone.utc)
    bj = utc.astimezone(dt.timezone(dt.timedelta(hours=8)))
    return utc.strftime("%Y-%m-%d %H:%M"), bj.strftime("%Y-%m-%d %H:%M")


def from_git(path: str) -> list[dict]:
    out = subprocess.run(
        ["git", "-C", path, "log", "--all", "--pretty=format:%h%x1f%an%x1f%aI%x1f%s"],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout
    rows = []
    for line in out.splitlines():
        if not line.strip():
            continue
        sha, author, iso, msg = line.split("\x1f", 3)
        utc, bj = to_bj(iso)
        rows.append({"sha": sha, "date_utc": utc, "date_bj": bj, "author": author, "message": msg})
    rows.sort(key=lambda r: r["date_utc"])
    return rows


def from_api() -> list[dict]:
    def get(url: str):
        req = urllib.request.Request(url, headers={
            "User-Agent": "tian-sheng-yi-dui-evidence/1.0",
            "Accept": "application/vnd.github+json",
        })
        with urllib.request.urlopen(req, timeout=60, context=CTX) as resp:
            return json.loads(resp.read().decode("utf-8"))

    rows, page = [], 1
    while True:
        batch = get(f"{API}/commits?per_page=100&page={page}")
        if not batch:
            break
        for c in batch:
            utc, bj = to_bj(c["commit"]["author"]["date"])
            rows.append({
                "sha": c["sha"][:8], "date_utc": utc, "date_bj": bj,
                "author": c["commit"]["author"]["name"],
                "message": c["commit"]["message"].splitlines()[0],
            })
        if len(batch) < 100:
            break
        page += 1

    contrib = get(f"{API}/contributors?per_page=100")
    print(f"贡献者 {len(contrib)} 人：" + "、".join(f"{a['login']}({a['contributions']})" for a in contrib))
    prs = get(f"{API}/pulls?state=all&per_page=100")
    for p in prs:
        print(f"  PR #{p['number']} {p['state']} merged={bool(p.get('merged_at'))} "
              f"{p['title']} merged_at={p.get('merged_at')}")
    rows.sort(key=lambda r: r["date_utc"])
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 data/commits.csv（API 或本地 git 克隆）")
    ap.add_argument("--git", help="本地仓库路径；省略则走 GitHub API")
    args = ap.parse_args()

    rows = from_git(args.git) if args.git else from_api()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["sha", "date_utc", "date_bj", "author", "message"])
        w.writeheader()
        w.writerows(rows)

    print(f"\n提交 {len(rows)} 条 → {OUT}")
    if rows:
        print(f"  最早 {rows[0]['date_bj']}（北京时间）  {rows[0]['message']}")
        print(f"  最晚 {rows[-1]['date_bj']}（北京时间）  {rows[-1]['message']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
