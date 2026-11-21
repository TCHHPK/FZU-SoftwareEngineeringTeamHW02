"""规范化比较快照与克隆：排除换行符/行尾空白/BOM 的干扰，看内容是否真的不同。"""

from __future__ import annotations

import difflib
import sys
from pathlib import Path

SNAP = Path.home() / "_gh_check" / "snap"
CLONE = Path(r"C:\Users\20378\Desktop\新建文件夹 (2)\_push_repo")
FILES = [
    "app/api/router.py",
    "app/db/conn.py",
    "app/db/migrations/002_learning_loop.sql",
    "app/db/schema.sql",
    "app/schemas/api_io.py",
    "app/services/wrong_book.py",
]


def norm(path: Path) -> list[str]:
    text = path.read_bytes().decode("utf-8-sig", "ignore")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return [line.rstrip() for line in text.split("\n")]


def main() -> int:
    print("规范化比较（统一 LF、去行尾空白、去 BOM）：")
    real = []
    for rel in FILES:
        a, b = norm(SNAP / rel), norm(CLONE / rel)
        same = a == b
        print(f"  {rel:<46} {'内容一致（仅换行/空白差异）' if same else '内容真的不同'}")
        if not same:
            real.append(rel)
            diff = list(difflib.unified_diff(a, b, "snapshot", "clone", lineterm="", n=1))
            for line in diff[:20]:
                print("      " + line[:110])
    print()
    if real:
        print(f"需要人工合并的文件：{len(real)} 个")
        for r in real:
            print("  -", r)
    else:
        print("结论：六个文件只是换行符差异，可以直接用合并版覆盖（内容等价，且我们的版本是 LF）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
