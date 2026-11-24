"""一键门禁：提交 PR 前跑这一条就够。

顺序（前一步失败就停，避免浪费时间）：
    1. pytest 全量
    2. e2e_smoke.py            端到端主链路
    3. smoke_learning_loop.py  学习闭环
    4. check_contract.py       契约与代码是否对得上（12.02 用 --release 严格要求 6/6）

用法：
    python scripts/gate.py                # 日常
    python scripts/gate.py --release      # 12.02 封板：契约必须 6/6 全实现
    python scripts/gate.py --browser      # 追加 Playwright 浏览器验收（较慢）
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def run(label: str, cmd: list[str], *, timeout: int = 1800) -> tuple[bool, float]:
    print(f"\n{'=' * 68}\n▶ {label}\n  $ {' '.join(cmd[-3:])}\n{'=' * 68}")
    start = time.time()
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=timeout)
    cost = time.time() - start
    tail = (proc.stdout + proc.stderr).strip().splitlines()
    for line in tail[-8:]:
        print("   " + line)
    ok = proc.returncode == 0
    print(f"  → {'通过' if ok else '失败'}（{cost:.1f}s）")
    return ok, cost


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", action="store_true", help="封板模式：契约要求 6/6")
    ap.add_argument("--browser", action="store_true", help="追加浏览器验收")
    args = ap.parse_args()

    steps = [
        ("pytest 全量", [PY, "-m", "pytest", "-q"]),
        ("端到端 e2e_smoke", [PY, "scripts/e2e_smoke.py"]),
        ("学习闭环 smoke_learning_loop", [PY, "scripts/smoke_learning_loop.py"]),
    ]
    if args.browser:
        steps.append(("浏览器验收 browser_check", [PY, "scripts/browser_check.py"]))

    results: list[tuple[str, bool, float]] = []
    for label, cmd in steps:
        ok, cost = run(label, cmd)
        results.append((label, ok, cost))
        if not ok:
            break

    # 契约校验放最后：它不阻塞日常开发，只在封板时当硬门槛
    contract_cmd = [PY, "scripts/check_contract.py"] + (["--strict"] if args.release else [])
    ok, cost = run("契约一致性 check_contract", contract_cmd)
    results.append(("契约一致性", ok, cost))

    print(f"\n{'=' * 68}\n汇总\n{'=' * 68}")
    for label, ok, cost in results:
        print(f"  {'OK  ' if ok else 'FAIL'} {label:<32} {cost:6.1f}s")
    failed = [label for label, ok, _ in results if not ok]
    total = sum(c for _, _, c in results)
    print(f"\n  总耗时 {total:.0f}s")
    if failed:
        print(f"  未通过：{'、'.join(failed)}")
        return 1
    print("  全部门禁通过" + ("（封板口径）" if args.release else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
