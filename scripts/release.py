"""发版脚本：升版本号、写 CHANGELOG、打包、打印 tag 命令。

为什么要有它：
    手工改版本号最容易出错的地方是「三处不同步」——
    VERSION 文件、CHANGELOG、Git tag 各写各的，过两周就对不上了。
    这个脚本保证三者由同一次操作产生。

用法：
    python scripts/release.py --bump patch --dry-run   # 看会变成什么，不改文件
    python scripts/release.py --bump minor             # 1.0.0 → 1.1.0
    python scripts/release.py --version 1.2.0          # 直接指定
    python scripts/release.py --bump major --notes "换用 MySQL，接口路径调整"

约定：
    major  不兼容改动（接口路径/字段变了、换存储引擎）
    minor  向后兼容的新功能（新增接口、新增页面）
    patch  向后兼容的缺陷修复（只改实现，不改契约）
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"
CHANGELOG = ROOT / "CHANGELOG.md"
DESKTOP = ROOT.parent

SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z.-]+))?$")


def read_version() -> str:
    if not VERSION_FILE.exists():
        return "0.0.0"
    return VERSION_FILE.read_text(encoding="utf-8").strip()


def bump(current: str, part: str) -> str:
    """按 SemVer 规则升位：升了高位要把低位清零。"""
    match = SEMVER.match(current)
    if not match:
        raise SystemExit(f"[失败] 当前版本号 {current!r} 不是合法的 SemVer（形如 1.2.3）")
    major, minor, patch = (int(match.group(i)) for i in (1, 2, 3))
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise SystemExit(f"[失败] 未知的升位类型：{part}")


def update_changelog(new_version: str, notes: str) -> str:
    """把 [Unreleased] 段落落到新版本号下，并重新开一个空的 Unreleased。

    没有 Unreleased 段落时，插入一个只含本次说明的版本段。
    """
    text = CHANGELOG.read_text(encoding="utf-8") if CHANGELOG.exists() else "# 更新日志\n"
    today = time.strftime("%Y-%m-%d")

    if "## [Unreleased]" in text:
        head, _, rest = text.partition("## [Unreleased]")
        body, sep, tail = rest.partition("\n---\n")
        body = body.strip("\n")
        # Unreleased 为空时补一行说明，避免出现空的版本段
        if not body.strip():
            body = ("### 变更\n- " + notes) if notes else "### 变更\n- 见提交记录"
        elif notes:
            body = body + f"\n\n### 备注\n- {notes}"
        new_section = f"## [{new_version}] - {today}\n\n{body}\n\n---\n"
        text = f"{head}## [Unreleased]\n\n---\n\n{new_section}{tail}"
    else:
        block = f"\n## [{new_version}] - {today}\n\n### 变更\n- {notes or '见提交记录'}\n"
        text = text.rstrip() + "\n" + block

    CHANGELOG.write_text(text, encoding="utf-8")
    return today


def build_archive(version: str) -> Path:
    """打一个带版本号的发布包（复用 make_v1_release 的分层结构）。"""
    builder = ROOT / "scripts" / "make_v1_release.py"
    if not builder.exists():
        raise SystemExit("[失败] 找不到 scripts/make_v1_release.py")

    out = DESKTOP / f"course-note-agent-v{version}-{time.strftime('%Y%m%d')}.zip"
    # 让打包脚本用当前版本号命名
    code = (
        "import sys, runpy, pathlib\n"
        f"sys.argv = ['make_v1_release.py']\n"
        f"import importlib.util\n"
        f"spec = importlib.util.spec_from_file_location('m', r'{builder}')\n"
        f"m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        f"m.OUTPUT = pathlib.Path(r'{out}')\n"
        f"m.ARC_PREFIX = 'course-note-agent-v{version}'\n"
        f"m.main()\n"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT))
    if result.returncode != 0 or not out.exists():
        raise SystemExit("[失败] 打包失败")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="发版：升版本号 + 写 CHANGELOG + 打包")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--bump", choices=["major", "minor", "patch"])
    group.add_argument("--version", help="直接指定版本号，如 1.2.0")
    parser.add_argument("--notes", default="", help="本次发布的一句话说明")
    parser.add_argument("--dry-run", action="store_true", help="只打印结果，不修改文件")
    parser.add_argument("--no-build", action="store_true", help="只改版本号和日志，不打包")
    args = parser.parse_args()

    current = read_version()
    new = args.version or bump(current, args.bump)
    if not SEMVER.match(new):
        raise SystemExit(f"[失败] 目标版本号 {new!r} 不是合法 SemVer")

    kind = "major" if new.split(".")[0] != current.split(".")[0] else (
        "minor" if new.split(".")[1] != current.split(".")[1] else "patch")
    label = {"major": "不兼容改动", "minor": "新增功能", "patch": "问题修复"}[kind]

    print(f"当前版本 : {current}")
    print(f"目标版本 : {new}（{label}）")
    if args.notes:
        print(f"发布说明 : {args.notes}")

    if args.dry_run:
        print("\n[dry-run] 未修改任何文件。")
        return 0

    VERSION_FILE.write_text(new + "\n", encoding="utf-8")
    today = update_changelog(new, args.notes)
    print(f"\n[ok] VERSION 已更新为 {new}")
    print(f"[ok] CHANGELOG 已新增 [{new}] - {today}")

    archive = None
    if not args.no_build:
        print("[..] 打包中 ...")
        archive = build_archive(new)
        size = archive.stat().st_size / 1024
        print(f"[ok] 发布包：{archive.name}（{size:.0f} KB）")

    tag = f"v{new}"
    print("\n" + "=" * 64)
    print("接下来手动执行（确认无误后）：")
    print(f"    git add VERSION CHANGELOG.md")
    print(f'    git commit -m "chore(release): {tag}"')
    print(f"    git tag -a {tag} -m \"{args.notes or label}\"")
    print(f"    git push origin main --tags")
    print()
    print("在 GitHub 上用这个 tag 建 Release，说明填 CHANGELOG 里对应的段落。")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
