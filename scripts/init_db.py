"""建库脚本：python -m scripts.init_db [--reset]

--reset 会删除 storage/*.db 重建（开发期用）；同时重置管理员账号口令。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.security import hash_password  # noqa: E402
from app.db.conn import business_db, init_databases  # noqa: E402

DEFAULT_ADMIN_PASSWORD = "admin123"


def main() -> int:
    parser = argparse.ArgumentParser(description="初始化 business.db 与 kb.db")
    parser.add_argument("--reset", action="store_true", help="删除已有数据库文件后重建")
    parser.add_argument("--admin-password", default=DEFAULT_ADMIN_PASSWORD)
    args = parser.parse_args()

    paths = init_databases(reset=args.reset)

    with business_db() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE username = 'admin'",
            (hash_password(args.admin_password),),
        )
        # 没有 admin 行时（schema 被改过）补一条
        conn.execute(
            """INSERT OR IGNORE INTO users (username, password_hash, nickname, role)
               VALUES ('admin', ?, '管理员', 'admin')""",
            (hash_password(args.admin_password),),
        )
        users = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        tables = [r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view') ORDER BY name")]
    print(f"[ok] business.db -> {paths['business']}（{len(tables)} 张表，{users} 个用户）")
    print(f"[ok] kb.db       -> {paths['kb']}")
    print(f"[info] 管理员账号：admin / {args.admin_password}（首次登录后请修改）")
    print(f"[info] business 表：{', '.join(tables)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
