"""导出课件逐页正文，供人工编写参考知识点清单用。

用法：python scripts/dump_pages.py "文件路径" [--pages 1-20]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.parse import parse_file  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print("用法：python scripts/dump_pages.py <文件> [--pages 1-20]")
        return 2
    path = Path(sys.argv[1])
    only = None
    if "--pages" in sys.argv:
        spec = sys.argv[sys.argv.index("--pages") + 1]
        lo, _, hi = spec.partition("-")
        only = (int(lo), int(hi or lo))

    doc = parse_file(path)
    print(f"# {path.name}  {doc.page_count} 页  类型 {doc.file_type}")
    print(f"# 章：{sorted({p.chapter_title for p in doc.pages if p.chapter_title})}")
    if doc.warnings:
        print(f"# 警告：{doc.warnings}")
    print()
    for page in doc.pages:
        if only and not (only[0] <= page.index <= only[1]):
            continue
        print(f"===== 第 {page.index} 页  节：{page.section_title or '（无）'} =====")
        print(page.text.strip() or "（空页）")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
