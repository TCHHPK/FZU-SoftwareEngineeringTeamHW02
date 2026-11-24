"""预合并检查：一个分支能不能合，先看它有没有动别人的文件。

为什么需要：
    11 个人并行开发，最容易在 12.02 晚上炸的不是逻辑 bug，是"两个人改了同一个文件"，
    或者"某人在自己分支里顺手改了共享文件"。等合并那天才发现，就会在最后一晚返工。

这个脚本按契约里的文件归属表（唯一主责）检查分支改动：
    --branch 某分支        检查该分支相对 main 的改动
    --staged               检查暂存区（提交前自查）

退出码：0 无越界；1 有越界或读不到 diff。

用法：
    python scripts/premerge_check.py --branch feature/review-swc
    python scripts/premerge_check.py --staged
"""

from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 文件归属（与 docs/契约-v1.3.md、任务分配卡保持一致）
OWNERS: list[tuple[str, str]] = [
    ("app/services/quiz.py", "徐张睿"),
    ("app/api/routes_self_test.py", "徐张睿"),
    ("app/db/conn.py", "徐张睿"),
    ("app/db/schema.sql", "徐张睿"),
    ("app/db/migrations/*", "徐张睿"),
    ("app/core/config.py", "徐张睿"),
    ("app/api/router.py", "徐张睿"),
    ("requirements.txt", "徐张睿"),
    ("app/schemas/api_io.py", "沈文驰"),
    ("app/services/wrong_book.py", "沈文驰"),
    ("app/api/routes_wrong.py", "沈文驰"),
    ("app/services/review_pack.py", "沈文驰"),
    ("app/services/review_plan.py", "沈文驰"),
    ("app/api/routes_review.py", "沈文驰"),
    ("app/agents/quiz.py", "陈瑀涵"),
    ("app/agents/pipeline.py", "陈瑀涵"),
    ("app/api/routes_sessions.py", "陈瑀涵"),
    ("app/services/query.py", "陈瑀涵"),
    ("scripts/eval_agent.py", "陈瑀涵"),
    ("frontend/src/views/SelfTestView.vue", "陈佳慧"),
    ("frontend/src/views/WrongBookView.vue", "陈佳慧"),
    ("frontend/src/views/ResultView.vue", "陈佳慧"),
    ("frontend/src/views/ReviewPackView.vue", "陈佳慧"),
    ("frontend/src/router/index.js", "陈佳慧"),
    ("frontend/src/utils/http.js", "陈佳慧"),
    ("frontend/src/style.css", "梁倩"),
    ("frontend/src/layouts/BasicLayout.vue", "梁倩"),
    ("frontend/src/components/PageHeader.vue", "梁倩"),
    ("frontend/src/components/EmptyState.vue", "梁倩"),
    ("frontend/src/components/EvidenceDrawer.vue", "庄剑钇"),
    ("frontend/src/components/TraceTimeline.vue", "庄剑钇"),
    ("frontend/src/components/DemoGuide.vue", "庄剑钇"),
    ("frontend/src/components/MindMapGraph.vue", "庄剑钇"),
    ("frontend/src/views/ProgressView.vue", "庄剑钇"),
    ("frontend/src/components/StatsCard.vue", "吴雅晴"),
    ("frontend/src/components/WeaknessChart.vue", "吴雅晴"),
    ("docs/*", "章玲"),
    ("README.md", "章玲"),
    ("CHANGELOG.md", "章玲"),
    ("tests/test_review_pack.py", "张佩琪"),
    ("tests/test_review_plan.py", "张佩琪"),
    ("tests/test_trace.py", "张佩琪"),
    ("tests/test_wrong_schedule.py", "张佩琪"),
]

# 这些目录是公共的，看新增文件归属到谁（新人写新文件不算越界）
NEW_FILE_HINT = {
    "app/services/": "沈文驰",
    "app/api/": "沈文驰",
    "frontend/src/components/": "（新建组件由创建者负责）",
    "scripts/": "（脚本由创建者负责）",
    "tests/": "张佩琪",
}


def owner_of(path: str) -> str | None:
    for pattern, who in OWNERS:
        if fnmatch.fnmatch(path, pattern):
            return who
    return None


def changed_files(args) -> list[str]:
    if args.branch:
        cmd = ["git", "diff", "--name-only", f"origin/main...{args.branch}"]
    else:
        cmd = ["git", "diff", "--cached", "--name-only"]
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"[失败] 取不到 diff：{proc.stderr.strip()[:200]}")
        sys.exit(2)
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--branch", help="检查该分支相对 origin/main 的改动")
    ap.add_argument("--staged", action="store_true", help="检查暂存区")
    ap.add_argument("--as", dest="who", help="提交人（用于判断是否越界），例如 沈文驰")
    args = ap.parse_args()
    if not (args.branch or args.staged):
        print("用法：--branch <分支名> 或 --staged")
        return 2

    files = changed_files(args)
    print(f"改动 {len(files)} 个文件" + (f"（提交人：{args.who}）" if args.who else ""))
    if not files:
        print("没有改动")
        return 0

    violations, shared, ok = [], [], []
    for f in files:
        who = owner_of(f)
        if who is None:
            ok.append(f)
        elif args.who and who != args.who:
            violations.append((f, who))
        else:
            shared.append((f, who))

    if shared:
        print("\n涉及共享文件（有主责，改动需经其同意）：")
        for f, who in shared:
            print(f"  · {f:<52} 归 {who}")
    if violations:
        print("\n越界（改的是别人的文件）：")
        for f, who in violations:
            print(f"  ! {f:<52} 应归 {who}")
    if ok:
        print(f"\n其他 {len(ok)} 个文件（无主责或新建）")

    print()
    if violations:
        print(f"结论：{len(violations)} 处越界，先和主责沟通再提 PR")
        return 1
    print("结论：没有越界")
    return 0


if __name__ == "__main__":
    sys.exit(main())
