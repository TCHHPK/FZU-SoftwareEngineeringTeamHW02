"""对比「当前 GitHub main」与「本地合并版」，生成只含代码改动的更新包。

为什么不用整包覆盖：
    仓库里同时有队友的答辩 pptx、燃尽图、验收报告。整包覆盖会把这些删掉或冲掉。
    所以这里做三件事：
        1. 逐个文件比对（相对路径 + sha256），分出「新增 / 修改 / 删除」；
        2. 只把新增与修改的文件打进 zip；
        3. 把「需要在仓库里删除的文件」写进 说明.txt（删除必须手工做，zip 做不到）。

用法：python scripts/make_code_update.py
"""

from __future__ import annotations

import hashlib
import sys
import tarfile
import time
import zipfile
from pathlib import Path

MERGED = Path(__file__).resolve().parents[1]
SNAPSHOT = Path.home() / "_gh_check" / "repo2.tar.gz"
DESKTOP = MERGED.parent
OUTPUT = DESKTOP / "代码更新到仓库-v1.2.0.zip"

# 只比较这些目录/文件；其余（文档、设计图、node_modules）一律不动
SCOPE_DIRS = ["app", "frontend/src", "frontend/tests", "tests", "scripts", "docs"]
SCOPE_FILES = ["requirements.txt", "conftest.py", "pytest.ini", "deploy.sh",
               "CHANGELOG.md", "VERSION", "readme.md"]

# 这些内容不参与比对（构建产物、缓存、运行数据）
SKIP_PARTS = {"node_modules", "dist", "__pycache__", ".venv", "storage", "logs",
              ".pytest_cache", ".git"}
SKIP_SUFFIX = {".pyc", ".pyo", ".log"}


def skip(rel: Path) -> bool:
    return any(part in SKIP_PARTS for part in rel.parts) or rel.suffix in SKIP_SUFFIX


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_snapshot() -> dict[str, str]:
    """读取 tar 快照，返回 {相对路径: sha256}。"""
    if not SNAPSHOT.exists():
        print(f"[失败] 快照不存在：{SNAPSHOT}")
        sys.exit(1)
    files: dict[str, str] = {}
    with tarfile.open(SNAPSHOT, "r:gz") as tf:
        for member in tf.getmembers():
            if not member.isfile():
                continue
            parts = member.name.split("/", 1)
            if len(parts) < 2:
                continue
            rel = Path(parts[1])
            if skip(rel):
                continue
            fp = tf.extractfile(member)
            if fp is None:
                continue
            files[rel.as_posix()] = sha(fp.read())
    return files


def load_local() -> dict[str, str]:
    files: dict[str, str] = {}
    for rel in SCOPE_DIRS:
        base = MERGED / rel
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            sub = path.relative_to(MERGED)
            if skip(sub):
                continue
            files[sub.as_posix()] = sha(path.read_bytes())
    for name in SCOPE_FILES:
        path = MERGED / name
        if path.is_file():
            files[name] = sha(path.read_bytes())
    return files


def main() -> int:
    print("读取 GitHub main 快照 ...")
    remote = {k: v for k, v in load_snapshot().items()
              if any(k.startswith(d + "/") for d in SCOPE_DIRS) or k in SCOPE_FILES}
    print(f"  main 侧共 {len(remote)} 个文件（限定范围内）")

    print("读取本地合并版 ...")
    local = load_local()
    print(f"  本地共 {len(local)} 个文件")

    added = sorted(set(local) - set(remote))
    modified = sorted(k for k in set(local) & set(remote) if local[k] != remote[k])
    removed = sorted(set(remote) - set(local))

    print(f"\n差异：新增 {len(added)}，修改 {len(modified)}，"
          f"仓库里有但本地没有 {len(removed)}")

    if added:
        print("\n[新增]")
        for k in added:
            print("  +", k)
    if modified:
        print("\n[修改]")
        for k in modified:
            print("  M", k)
    if removed:
        print("\n[建议在仓库删除]")
        for k in removed:
            print("  -", k)

    payload = added + modified
    if not payload:
        print("\n没有需要上传的改动")
        return 0

    if OUTPUT.exists():
        OUTPUT.unlink()
    with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for rel in payload:
            z.write(MERGED / rel, rel)

    note = build_note(added, modified, removed)
    with zipfile.ZipFile(OUTPUT, "a", zipfile.ZIP_DEFLATED) as z:
        z.writestr("_上传说明.txt", note)

    size = OUTPUT.stat().st_size / 1024
    print(f"\n[ok] 已生成：{OUTPUT.name}（{size:.0f} KB，{len(payload)} 个文件 + 说明）")
    print(f"     SHA256: {sha(OUTPUT.read_bytes())[:16]}")
    return 0


def build_note(added: list[str], modified: list[str], removed: list[str]) -> str:
    lines = [
        "代码更新到 GitHub（v1.2.0）",
        "=" * 60,
        "",
        "这个包只含「代码改动」，不含文档、设计图、node_modules。",
        f"生成时间：{time.strftime('%Y-%m-%d %H:%M')}",
        "",
        "一、怎么用（网页上传，3 分钟）",
        "-" * 60,
        "1. 打开仓库 → Add file → Upload files",
        "2. 把这个 zip 解压后，把里面的 app/ frontend/ tests/ scripts/ docs/",
        "   以及根目录的 requirements.txt 等文件，按原路径拖进去（会提示覆盖，正常）",
        "3. Commit 信息建议：",
        "     feat: 合并学习闭环（智能自测/错题本/图形化导图）并修复集成问题",
        "",
        "注意：网页上传只能「覆盖同路径文件」，不能删除文件。",
        "      下面第二节列出的文件，需要在网页上手工删除。",
        "",
        "二、需要在仓库里手工删除的文件",
        "-" * 60,
    ]
    if removed:
        for k in removed:
            lines.append(f"  - {k}")
        lines += [
            "",
            "  其中 router.py 与 routes_mindmap.py 是放在仓库根目录的错位文件",
            "  （不在 app/api/ 包里，永远不会被注册），删除后由 app/api/ 下的正式文件替代。",
        ]
    else:
        lines.append("  （无）")

    lines += ["", "三、本包含的文件", "-" * 60, f"新增 {len(added)} 个："]
    lines += [f"  + {k}" for k in added] or ["  （无）"]
    lines += ["", f"修改 {len(modified)} 个："]
    lines += [f"  M {k}" for k in modified] or ["  （无）"]

    lines += [
        "",
        "四、上传后请验证",
        "-" * 60,
        "  python -m pytest -q                    # 期望全过（58 项）",
        "  python scripts/e2e_smoke.py            # 端到端",
        "  python scripts/smoke_learning_loop.py  # 学习闭环",
        "",
        "  线上已部署同一份代码，可直接对照：http://47.114.55.115:8000",
        "",
        "五、不要做的两件事",
        "-" * 60,
        "  1. 不要用整个 v1.2.0 发布包覆盖仓库——里面有文档和 node_modules，",
        "     会冲掉队友的答辩 pptx、燃尽图等文件。",
        "  2. 不要提交 storage/、.env、node_modules、dist/。",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
