"""把合并版代码应用到克隆仓库，并在动手前做冲突预检。

预检逻辑：
    我手上的「基准」是 2026-11-21 上午拉的 main 快照（repo2.tar.gz）。
    如果克隆仓库里某个我要覆盖或删除的文件，其内容与快照不同，
    说明队友在这之后改过它 —— 此时必须停下来人工判断，不能盲覆盖。

用法：python scripts/apply_to_clone.py --clone <克隆目录> [--apply]
不带 --apply 时只做预检与清单输出。
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tarfile
from pathlib import Path

MERGED = Path(__file__).resolve().parents[1]
SNAPSHOT = Path.home() / "_gh_check" / "repo2.tar.gz"
DESKTOP = MERGED.parent
VERSION_DIRS = DESKTOP / "GitHub上传-三个版本"

SCOPE_DIRS = ["app", "frontend/src", "frontend/tests", "tests", "scripts", "docs"]
SCOPE_FILES = ["requirements.txt", "conftest.py", "pytest.ini", "deploy.sh",
               "CHANGELOG.md", "VERSION", "readme.md"]
SKIP_PARTS = {"node_modules", "dist", "__pycache__", ".venv", "storage", "logs",
              ".pytest_cache", ".git"}
SKIP_SUFFIX = {".pyc", ".pyo", ".log"}

# 明确要删的错位文件
DELETE_ALWAYS = ["router.py", "routes_mindmap.py", "app/static/export_docx.py"]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def skip(rel: Path) -> bool:
    return any(p in SKIP_PARTS for p in rel.parts) or rel.suffix in SKIP_SUFFIX


def snapshot_hashes() -> dict[str, str]:
    out: dict[str, str] = {}
    with tarfile.open(SNAPSHOT, "r:gz") as tf:
        for m in tf.getmembers():
            if not m.isfile():
                continue
            parts = m.name.split("/", 1)
            if len(parts) < 2:
                continue
            rel = Path(parts[1])
            if skip(rel):
                continue
            fp = tf.extractfile(m)
            if fp:
                out[rel.as_posix()] = sha(fp.read())
    return out


def local_files() -> dict[str, Path]:
    files: dict[str, Path] = {}
    for rel in SCOPE_DIRS:
        base = MERGED / rel
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.is_file() and not skip(p.relative_to(MERGED)):
                files[p.relative_to(MERGED).as_posix()] = p
    for name in SCOPE_FILES:
        p = MERGED / name
        if p.is_file():
            files[name] = p
    return files


def norm_text(data: bytes) -> list[str] | None:
    """把文本规范化成行列表：去 BOM、统一 LF、去行尾空白。

    Windows 上有人用编辑器重存文件会把 LF 变 CRLF，哈希就变了但内容没变。
    预检必须排除这种噪声，否则每次都会被误判成冲突。
    """
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    if "\x00" in text:
        return None
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return [line.rstrip() for line in text.split("\n")]


def same_content(a: bytes, b: bytes) -> bool:
    if a == b:
        return True
    na, nb = norm_text(a), norm_text(b)
    return na is not None and nb is not None and na == nb


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clone", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    clone = Path(args.clone)

    snap = snapshot_hashes()
    local = local_files()

    # 只在快照范围内比较（避免把仓库里我没碰过的文档算进差异）
    snap_scope = {k: v for k, v in snap.items()
                  if any(k.startswith(d + "/") for d in SCOPE_DIRS) or k in SCOPE_FILES}

    added = sorted(set(local) - set(snap_scope))
    modified = sorted(k for k in set(local) & set(snap_scope)
                      if sha(local[k].read_bytes()) != snap_scope[k])
    removed = sorted(set(snap_scope) - set(local))

    print(f"计划写入 {len(added) + len(modified)} 个文件，删除 {len(removed) + len(DELETE_ALWAYS)} 个")

    # 把快照解出一份到磁盘，预检时直接比内容（能识别"仅换行差异"）
    snap_dir = Path.home() / "_gh_check" / "snap_full"
    if not snap_dir.exists():
        print("解出快照到磁盘以便比较 ...")
        with tarfile.open(SNAPSHOT, "r:gz") as tf:
            for m in tf.getmembers():
                if not m.isfile():
                    continue
                parts = m.name.split("/", 1)
                if len(parts) < 2:
                    continue
                fp = tf.extractfile(m)
                if not fp:
                    continue
                dst = snap_dir / parts[1]
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(fp.read())

    print("\n冲突预检（队友是否在我拉快照之后改过内容）：")
    conflicts = []
    for rel in modified + removed + DELETE_ALWAYS:
        target = clone / rel
        base = snap_dir / rel
        if not target.exists() or not base.exists():
            continue
        if not same_content(target.read_bytes(), base.read_bytes()):
            conflicts.append(rel)
    if conflicts:
        print("  [中止] 以下文件与快照不一致，可能队友改过：")
        for c in conflicts:
            print("    !", c)
        print("  请人工确认后再执行（不要盲目覆盖）")
        return 2
    print("  OK：将要覆盖/删除的文件与快照一致")

    if not args.apply:
        print("\n（预检模式，未修改任何文件；加 --apply 执行）")
        return 0

    print("\n写入文件 ...")
    for rel in added + modified:
        dst = clone / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local[rel], dst)

    print("删除文件 ...")
    for rel in removed + DELETE_ALWAYS:
        dst = clone / rel
        if dst.exists():
            dst.unlink()
            print("  -", rel)

    # 版本归档目录
    print("复制三个版本目录 ...")
    for name in ("1.0版本", "1.1版本", "1.2版本"):
        src = VERSION_DIRS / name
        if not src.exists():
            print(f"  [跳过] 桌面缺少 {name}")
            continue
        dst = clone / name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        n = len(list(dst.rglob("*")))
        print(f"  + {name}/（{n} 项）")

    note = VERSION_DIRS / "上传步骤.txt"
    if note.exists():
        shutil.copy2(note, clone / "版本归档说明.txt")
        print("  + 版本归档说明.txt")

    print("\n完成。下一步在克隆目录里：")
    print("  git status --short")
    print("  python -m pytest -q")
    return 0


if __name__ == "__main__":
    sys.exit(main())
