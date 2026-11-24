"""契约与代码一致性校验：docs/契约-v1.3.md 里写的端点，代码里是否真的存在。

为什么需要：
    契约是"大家照着写"的依据，但它和代码会各自漂移。上一轮的教训是——
    文档写了接口、代码没注册，或路径前缀对不上，等 12.02 才发现。
    这个脚本随时能跑：已交付的端点必须全部命中，未交付的会列成待办，不算失败。

用法：
    python scripts/check_contract.py            # 列出已实现 / 待交付
    python scripts/check_contract.py --strict   # 待交付即失败（12.02 封板时用）
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CONTRACT = ROOT / "docs" / "契约-v1.3.md"

# 契约里承诺的六个端点（路径 + 方法），键是给人看的名字
EXPECTED = {
    "复习包生成": ("POST", "/api/sessions/{session_id}/review-pack"),
    "复习包导出": ("GET", "/api/review-packs/{pack_id}/export"),
    "冲刺计划": ("POST", "/api/sessions/{session_id}/review-plan"),
    "到期队列": ("GET", "/api/wrong-questions/due"),
    "出处原文": ("GET", "/api/chunks/{chunk_key}"),
    "执行轨迹": ("GET", "/api/sessions/{session_id}/trace"),
}

# 本轮对既有接口的承诺（字段级，靠代码里的字面量确认）
FIELD_PROMISES = {
    "自测取卷 target_count": ("app/services/quiz.py", "target_count"),
    "自测取卷 actual_count": ("app/services/quiz.py", "actual_count"),
    "自测取卷 shortfall": ("app/services/quiz.py", "shortfall"),
    "交卷 409 白名单": ("app/services/quiz.py", '"draft"'),
    "事务 BEGIN IMMEDIATE": ("app/db/conn.py", "BEGIN IMMEDIATE"),
    "迁移 003 轨迹表": ("app/db/migrations/003_review_plan.sql", "session_traces"),
    "开关 review_pack": ("app/core/config.py", "enable_review_pack"),
    "fsrs 依赖锁定": ("requirements.txt", "fsrs=="),
}


def norm(path: str) -> str:
    """把 FastAPI 的 {id} 与契约的 {session_id} 归一化成同一个形状。"""
    return re.sub(r"\{[^}]+\}", "{}", path.rstrip("/"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="存在待交付端点即返回非 0")
    args = ap.parse_args()

    from app.main import app  # noqa: PLC0415 - 延迟导入，避免 --help 时就初始化应用

    actual: set[tuple[str, str]] = set()
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api"):
            continue
        for method in getattr(route, "methods", set()) or set():
            if method in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                actual.add((method, norm(path)))

    print("=" * 70)
    print("一、契约承诺的六个端点")
    print("=" * 70)
    done, todo = [], []
    for name, (method, path) in EXPECTED.items():
        hit = (method, norm(path)) in actual
        if hit:
            done.append(name)
            print(f"  OK    {name:<10} {method:<5} {path}")
        else:
            todo.append(name)
            print(f"  待交付 {name:<9} {method:<5} {path}")
    print(f"\n  已实现 {len(done)} 个，待交付 {len(todo)} 个")

    print()
    print("=" * 70)
    print("二、契约里写的字段/机制是否落到代码")
    print("=" * 70)
    missing_fields = []
    for label, (rel, needle) in FIELD_PROMISES.items():
        path = ROOT / rel
        ok = path.exists() and needle in path.read_text(encoding="utf-8")
        if not ok:
            missing_fields.append(label)
        print(f"  {'OK   ' if ok else '缺失  '} {label:<22} {rel}")

    print()
    print("=" * 70)
    print("三、契约文档自身是否覆盖这六个端点")
    print("=" * 70)
    if CONTRACT.exists():
        text = CONTRACT.read_text(encoding="utf-8")
        for name, (_, path) in EXPECTED.items():
            ok = path.replace("/api", "") in text or path in text
            print(f"  {'OK   ' if ok else '缺失  '} 契约文档提到 {name}")
    else:
        print("  [缺失] docs/契约-v1.3.md 不存在")
        missing_fields.append("契约文档")

    print()
    print("=" * 70)
    print("四、路由遮蔽检查（静态路径不能被动态段吃掉）")
    print("=" * 70)
    # 已踩过的坑：/api/wrong-questions/due 会先匹配到 /api/wrong-questions/{wrong_id}，
    # "due" 转 int 失败直接 422。FastAPI 按注册顺序匹配，所以静态路径必须声明在前。
    shadow_risks = [
        ("/api/wrong-questions/due", "/api/wrong-questions/{wrong_id}"),
    ]
    shadow_ok = True
    for target, dynamic in shadow_risks:
        # 目标路径还没实现时只是"待办"，不算失败；只有真正注册了却被前面的
        # 动态路由吃掉，才是必须修的问题。
        if ("GET", norm(target)) not in actual:
            print(f"  待实现 {target}（实现时记得声明在 {dynamic} 之前）")
            continue
        first = None
        for route in app.routes:
            path = getattr(route, "path", "")
            regex = getattr(route, "path_regex", None)
            if regex is not None and regex.match(target):
                first = path
                break
        ok = first == target
        shadow_ok &= ok
        print(f"  {'OK   ' if ok else '被遮蔽'} {target}"
              + ("" if ok else f"　先命中 {first}，请求会返回 422"))

    print()
    print("=" * 70)
    failed = bool(missing_fields) or (args.strict and todo) or not shadow_ok
    print(f"结论：已实现 {len(done)}/6 端点；字段承诺 {'全部落实' if not missing_fields else f'缺 {len(missing_fields)} 项'}")
    if todo:
        print(f"      待交付：{'、'.join(todo)}（负责人见契约文档）")
    print("通过" if not failed else "未通过")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
