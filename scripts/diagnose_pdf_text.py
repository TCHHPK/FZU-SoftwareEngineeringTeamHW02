"""诊断课件文本层质量：打印真实提取结果，判断是「中文正常」还是「乱码」。

用法：python scripts/diagnose_pdf_text.py "课件目录"
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymupdf  # noqa: E402


def char_profile(text: str) -> dict:
    """统计字符构成，用数据判断是否乱码。"""
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    digit = sum(1 for c in text if c.isdigit())
    punct = sum(1 for c in text if c in "，。、；：？！（）【】《》“”‘’—…·")
    symbol = len(text) - cjk - latin - digit - punct
    total = max(len(text), 1)
    return {
        "总字符": len(text),
        "中文": cjk,
        "中文占比": f"{cjk / total:.0%}",
        "英文": latin,
        "数字": digit,
        "中文标点": punct,
        "其他符号": symbol,
    }


def main() -> int:
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    samples = sys.argv[2:] or None
    pdfs = sorted(folder.glob("*.pdf"))
    if samples:
        pdfs = [p for p in pdfs if p.name in samples or p.stem in samples]

    for pdf in pdfs:
        print("=" * 96)
        print(f"文件：{pdf.name}   （{pdf.stat().st_size / 1024 / 1024:.1f} MB）")
        print("=" * 96)
        try:
            doc = pymupdf.open(pdf)
        except Exception as exc:  # noqa: BLE001
            print(f"  打不开：{exc}\n")
            continue

        # 找出字符最多的 3 页来抽样，避免抽到封面页
        page_texts = []
        for i, page in enumerate(doc):
            try:
                page_texts.append((i + 1, page.get_text("text") or ""))
            except Exception:  # noqa: BLE001
                page_texts.append((i + 1, ""))
        ranked = sorted(page_texts, key=lambda t: len(t[1]), reverse=True)[:3]

        print(f"  总页数 {len(page_texts)}；文本最多的 3 页：{[p for p, _ in ranked]}")
        print(f"  全文统计：{char_profile(''.join(t for _, t in page_texts))}")

        for pno, text in ranked[:2]:
            print(f"\n  ── 第 {pno} 页原始提取（前 400 字）────────────────────────")
            clean = text.strip()
            print("  " + (clean[:400].replace("\n", "\n  ") if clean else "（空页）"))
            print(f"\n  ── 该页统计：{char_profile(text)}")

        # 用字典接口看字体的真实编码情况
        try:
            page = doc[ranked[0][0] - 1]
            fonts = Counter()
            for block in page.get_text("dict").get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        fonts[span.get("font", "?")] += len(span.get("text", ""))
            print(f"\n  ── 第 {ranked[0][0]} 页使用的字体：{dict(fonts)}")
        except Exception:  # noqa: BLE001
            pass

        # 尝试用不同提取方式对比，看哪种能拿到正确中文
        print("\n  ── 不同提取方式对比（第 %d 页）" % ranked[0][0])
        page = doc[ranked[0][0] - 1]
        for mode in ("text", "blocks", "rawdict"):
            try:
                if mode == "blocks":
                    got = " ".join(b[4] for b in page.get_text("blocks") if len(b) > 4)[:120]
                elif mode == "rawdict":
                    chars = []
                    for block in page.get_text("rawdict").get("blocks", []):
                        for line in block.get("lines", []):
                            for span in line.get("spans", []):
                                for ch in span.get("chars", []):
                                    chars.append(ch.get("c", ""))
                    got = "".join(chars)[:120]
                else:
                    got = page.get_text("text")[:120]
                print(f"     {mode:8s}: {got!r}")
            except Exception as exc:  # noqa: BLE001
                print(f"     {mode:8s}: 失败 {exc}")
        doc.close()
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
