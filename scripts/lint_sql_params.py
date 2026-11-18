"""检查 SQL 占位符数量与实际传入参数数量是否一致。

为什么需要这个脚本：
    SQLite 的报错只说 "uses 2, and there are 1 supplied"，不指出代码位置。
    本项目已被这类问题坑过三次（list_documents / list_courses / list_chats），
    每次都要靠翻 traceback 定位，所以做成静态检查。

检查方式：
    找出形如 xxx.execute( <SQL字符串>, <参数> ) 的调用，比较：
      * `?` 占位符个数 与 参数元组/列表的元素个数
      * `:name` 命名参数 与 参数字典的键
    只有能静态确定个数时才报错，动态拼接的语句跳过（避免误报）。

用法：python scripts/lint_sql_params.py
退出码：0 全部通过；1 发现不一致。
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = [ROOT / "app", ROOT / "scripts", ROOT / "tests"]

_EXECUTE_METHODS = {"execute", "executemany", "executescript"}
_SQL_HINT = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE)\b", re.I)
_QMARK = re.compile(r"\?")
_NAMED = re.compile(r"(?<![:@$]):([A-Za-z_][A-Za-z0-9_]*)")


def _sql_text(node: ast.AST) -> str | None:
    """尽力取出字符串常量（含简单拼接）的内容，取不到返回 None。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = [v.value for v in node.values
                 if isinstance(v, ast.Constant) and isinstance(v.value, str)]
        return "".join(parts) if parts else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _sql_text(node.left), _sql_text(node.right)
        if left is None or right is None:
            return None
        return left + right
    if isinstance(node, ast.Name):
        return None  # 变量，静态看不出来
    return None


def _static_len(node: ast.AST) -> int | None:
    """静态求出容器长度；无法确定返回 None。"""
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        if any(isinstance(e, ast.Starred) for e in node.elts):
            return None
        return len(node.elts)
    if isinstance(node, ast.Dict):
        if any(k is None for k in node.keys):
            return None
        return len(node.keys)
    return None


def _static_keys(node: ast.AST) -> set[str] | None:
    if isinstance(node, ast.Dict):
        keys = set()
        for k in node.keys:
            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                keys.add(k.value)
            else:
                return None
        return keys
    return None


def check_file(path: Path) -> tuple[int, list[str]]:
    """返回 (检查的语句数, 问题列表)。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        return 0, [f"{path.name}: 语法错误 {exc}"]

    checked, problems = 0, []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr not in _EXECUTE_METHODS:
            continue
        if not node.args:
            continue

        sql = _sql_text(node.args[0])
        if sql is None or not _SQL_HINT.search(sql):
            continue

        # executescript 不接受参数
        if func.attr == "executescript":
            continue

        qmarks = len(_QMARK.findall(sql))
        named = set(_NAMED.findall(sql))
        if not qmarks and not named:
            continue

        params_node = node.args[1] if len(node.args) > 1 else None
        keywords = {k.arg: k.value for k in node.keywords}
        params_node = params_node or keywords.get("parameters") or keywords.get("params")

        rel = f"{path.relative_to(ROOT)}:{node.lineno}"
        if params_node is None:
            checked += 1
            problems.append(f"{rel} SQL 有占位符但没找到参数（可能用了关键字传参或变量）")
            continue

        checked += 1
        if qmarks:
            size = _static_len(params_node)
            if size is not None and size != qmarks:
                problems.append(
                    f"{rel} ? 占位符 {qmarks} 个，实际传参 {size} 个 —— 运行时会报 "
                    f"ProgrammingError")
        if named:
            keys = _static_keys(params_node)
            if keys is not None:
                missing = named - keys
                if missing:
                    problems.append(
                        f"{rel} 命名参数 {sorted(missing)} 没有对应的传参键 {sorted(keys)}")
            elif isinstance(params_node, (ast.Tuple, ast.List)):
                problems.append(
                    f"{rel} SQL 用的是命名参数 {sorted(named)}，但传的是位置参数 —— "
                    "运行时会报 ProgrammingError")

    return checked, problems


def main() -> int:
    total, problems = 0, []
    for folder in SCAN_DIRS:
        if not folder.exists():
            continue
        for path in sorted(folder.rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            checked, found = check_file(path)
            total += checked
            problems.extend(found)

    for p in problems:
        print(f"[ERR] {p}")
    print("-" * 64)
    print(f"检查了 {total} 条带参数的 SQL 调用，"
          f"{'全部通过' if not problems else f'发现 {len(problems)} 处不一致'}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
