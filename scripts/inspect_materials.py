"""批量体检课件文件：判断能否被系统解析、章节结构是否清晰。

用法：
    python scripts/inspect_materials.py "课件目录"

输出每份文件的关键指标：
    页数、有文本层的页数占比、抽取字符数、识别到的章/节数、告警
并给出「建议选用哪几份作为首期范围」的结论。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.parse import ParseError, parse_file  # noqa: E402

MIN_TEXT_PER_PAGE = 40          # 平均每页字符数低于此值 → 疑似扫描件
GOOD_TEXT_PER_PAGE = 150        # 高于此值 → 文本层质量良好


def inspect(path: Path) -> dict:
    try:
        doc = parse_file(path)
    except ParseError as exc:
        return {"file": path.name, "ok": False, "error": str(exc)}

    pages = doc.page_count
    text_chars = doc.text_chars
    per_page = text_chars / max(pages, 1)
    empty_pages = sum(1 for p in doc.pages if not p.text.strip())
    chapters = sorted({p.chapter_title for p in doc.pages if p.chapter_title})
    sections = sorted({p.section_title for p in doc.pages if p.section_title})
    garbled = [w for w in doc.warnings if "乱码" in w or "缺字" in w]

    if not doc.has_text_layer:
        verdict = "扫描件，不可用"
    elif per_page >= GOOD_TEXT_PER_PAGE:
        verdict = "质量良好"
    else:
        verdict = "文本偏少，需人工确认"

    return {
        "file": path.name,
        "ok": True,
        "pages": pages,
        "per_page": round(per_page, 1),
        "chars": text_chars,
        "empty_pages": empty_pages,
        "chapters": chapters,
        "sections": sections[:6],
        "n_sections": len(sections),
        "garbled": len(garbled),
        "warnings": doc.warnings[:2],
        "verdict": verdict,
        "size_mb": round(path.stat().st_size / 1024 / 1024, 1),
    }


def main() -> int:
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    pdfs = sorted(folder.glob("*.pdf"), key=lambda p: p.name)
    if not pdfs:
        print(f"目录中没有 PDF：{folder}")
        return 1

    results = []
    print("=" * 100)
    print(f"课件体检：{folder}    共 {len(pdfs)} 份")
    print("=" * 100)
    for pdf in pdfs:
        r = inspect(pdf)
        results.append(r)
        if not r["ok"]:
            print(f"\n✗ {r['file']:<16} 解析失败：{r['error']}")
            continue
        print(f"\n● {r['file']:<16} {r['size_mb']:>6} MB   {r['pages']:>4} 页   "
              f"每页均 {r['per_page']:>6} 字   空页 {r['empty_pages']:>3}   "
              f"章节 {len(r['chapters'])} 章 / {r['n_sections']} 节   → {r['verdict']}")
        if r["chapters"]:
            for c in r["chapters"][:4]:
                print(f"      章：{c}")
            if len(r["chapters"]) > 4:
                print(f"      ...（共 {len(r['chapters'])} 章）")
        elif r["sections"]:
            print(f"      节（未识别到章）：{' / '.join(r['sections'][:3])}")
        if r["garbled"]:
            print(f"      ⚠ {r['garbled']} 页疑似字体缺字/编码异常")
        for w in r["warnings"]:
            print(f"      ⚠ {w}")

    # ---------------- 汇总 ----------------
    usable = [r for r in results if r["ok"] and r["verdict"] == "质量良好"]
    weak = [r for r in results if r["ok"] and r["verdict"] == "文本偏少，需人工确认"]
    scanned = [r for r in results if r["ok"] and r["verdict"] == "扫描件，不可用"]
    broken = [r for r in results if not r["ok"]]

    print("\n" + "=" * 100)
    print("汇总")
    print("=" * 100)
    print(f"  质量良好，可直接用作演示材料：{len(usable)} 份")
    for r in usable:
        print(f"      {r['file']}（{r['pages']} 页，{len(r['chapters'])} 章 / {r['n_sections']} 节）")
    if weak:
        print(f"  文本偏少，需要人工看一眼：{len(weak)} 份")
        for r in weak:
            print(f"      {r['file']}（每页均 {r['per_page']} 字）")
    if scanned:
        print(f"  扫描件，系统无法解析（需要 OCR，本期不支持）：{len(scanned)} 份")
        for r in scanned:
            print(f"      {r['file']}（每页均 {r['per_page']} 字）")
    if broken:
        print(f"  解析失败：{len(broken)} 份")
        for r in broken:
            print(f"      {r['file']}：{r['error']}")

    print("\n  建议首期范围：从「质量良好」里挑 1~2 份、章节结构最清楚的作为演示课程；")
    print("  不要一次性把 10 份全部纳入范围——课件越多，评测和调优的工作量越大。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
