# -*- coding: utf-8 -*-
"""静态复核发布包：用例计数、源码编译、路由计数。

作用：
    "58 项后端用例 + 4 项前端用例"这类数字，如果只是转述发布说明，无法证明。
    本脚本直接读源码做三件事，结果可复现：
      1. 用 ast 统计 tests/ 下每个文件的 test_ 函数数量；
      2. 统计 frontend/tests/*.mjs 里的 test( 用例数；
      3. 逐文件 py_compile，确认没有语法错误（不需要装 fastapi 等依赖）；
      4. 统计 app/api/routes_*.py 里注册的路由处理函数数量。

用法：
    python scripts/verify_release.py <发布包源码目录>
    # 例：python scripts/verify_release.py D:\\pkg\\course-note-agent-v1.2.0\\01-源码\\course-note-agent

输出：
    每个测试文件的用例数、合计、编译通过率、路由数。
"""
from __future__ import annotations

import argparse
import ast
import pathlib
import py_compile
import sys


def count_tests(root: pathlib.Path) -> tuple[list[tuple[str, int]], int]:
    rows: list[tuple[str, int]] = []
    total = 0
    for f in sorted((root / "tests").glob("test_*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        n = sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
        )
        rows.append((f.name, n))
        total += n
    return rows, total


def count_frontend_tests(root: pathlib.Path) -> int:
    n = 0
    for f in sorted((root / "frontend" / "tests").glob("*.mjs")):
        n += f.read_text(encoding="utf-8").count("test(")
    return n


def compile_all(root: pathlib.Path) -> tuple[int, int, list[str]]:
    files = [p for p in root.rglob("*.py") if ".venv" not in str(p) and "venv" not in p.parts]
    ok, bad = 0, []
    for p in files:
        cf = str(p) + ".pyc"
        try:
            py_compile.compile(str(p), cfile=cf, doraise=True)
            ok += 1
        except Exception as exc:  # noqa: BLE001 - 只要报告文件名与首行原因
            bad.append(f"{p.name}: {str(exc).splitlines()[0]}")
        finally:
            pathlib.Path(cf).unlink(missing_ok=True)
    return ok, len(files), bad


def count_routes(root: pathlib.Path) -> int:
    n = 0
    for p in (root / "app" / "api").glob("routes_*.py"):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for d in node.decorator_list:
                    if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                            and d.func.attr in {"get", "post", "put", "delete", "patch"}):
                        n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description="静态复核发布包（用例数 / 编译 / 路由数）")
    ap.add_argument("src", help="发布包源码根目录（含 app/、tests/、frontend/）")
    args = ap.parse_args()

    root = pathlib.Path(args.src).resolve()
    if not (root / "tests").is_dir():
        print(f"[错误] {root} 下没有 tests/，请指向源码根目录", file=sys.stderr)
        return 2

    rows, total = count_tests(root)
    print("后端用例：", total)
    for name, n in rows:
        print(f"  {name:34s} {n}")

    fe = count_frontend_tests(root)
    print(f"前端用例：{fe}（frontend/tests/*.mjs）")
    print(f"合计：{total + fe} 项")

    ok, all_files, bad = compile_all(root)
    print(f"\n语法编译：{ok}/{all_files} 通过")
    for item in bad:
        print("  FAIL", item)

    print(f"路由处理函数：{count_routes(root)} 个")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
