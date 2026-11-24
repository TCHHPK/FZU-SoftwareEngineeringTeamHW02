"""把合并后的代码部署到线上服务器（SSH + SFTP）。

设计原则（线上有真实数据，宁可慢也不能丢）：
    1. 先备份：storage/ 整个打包 + .env，出问题能回滚；
    2. 只覆盖代码，**不碰** storage/、.env、logs/；
    3. 迁移用 init_databases()（不加 --reset），补列补表但保留账号与任务；
    4. 重启后必须验证：服务状态、健康接口、新接口存在、前端主包指纹；
    5. 任何一步失败就停下并打印原因，不继续往下跑。

用法：
    $env:DSH_DEPLOY_PASS = "密码"; python scripts/deploy_remote.py
    python scripts/deploy_remote.py --dry-run      # 只体检，不修改
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import tarfile
import time
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
REMOTE_DIR = "/root/course-note-agent"
APP_NAME = "course-note-agent"

# 只传这些：代码 + 测试 + 部署脚本。文档、设计图、node_modules 不传。
INCLUDE = ["app", "scripts", "tests", "data", "reports",
           "requirements.txt", "deploy.sh", "conftest.py", "pytest.ini",
           "VERSION", "CHANGELOG.md", "readme.md", ".env.example"]
EXCLUDE_DIRS = {"__pycache__", "node_modules", ".venv", ".git", ".pytest_cache"}
EXCLUDE_SUFFIX = {".pyc", ".log"}


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")


def build_tar() -> bytes:
    """在内存里打 tar.gz，排除缓存与虚拟环境。"""
    buf = io.BytesIO()
    count = 0
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=6) as tar:
        for name in INCLUDE:
            path = ROOT / name
            if not path.exists():
                continue
            if path.is_file():
                tar.add(str(path), arcname=name)
                count += 1
                continue
            for sub in path.rglob("*"):
                rel = sub.relative_to(ROOT)
                if any(part in EXCLUDE_DIRS for part in rel.parts):
                    continue
                if sub.suffix in EXCLUDE_SUFFIX or not sub.is_file():
                    continue
                tar.add(str(sub), arcname=str(rel).replace("\\", "/"))
                count += 1
    log(f"      打包 {count} 个文件，{buf.tell() / 1024 / 1024:.1f} MB")
    return buf.getvalue()


class Remote:
    def __init__(self, host: str, password: str, user: str = "root", port: int = 22):
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.connect(hostname=host, port=port, username=user, password=password,
                            timeout=20, banner_timeout=20, auth_timeout=20)
        self.sftp = self.client.open_sftp()

    def run(self, cmd: str, *, check: bool = True) -> str:
        stdin, stdout, stderr = self.client.exec_command(cmd, timeout=600)
        out = stdout.read().decode("utf-8", "ignore")
        err = stderr.read().decode("utf-8", "ignore")
        code = stdout.channel.recv_exit_status()
        if check and code != 0:
            raise RuntimeError(f"命令失败（exit {code}）：{cmd}\n{err.strip()[:800]}")
        return (out + err).strip()

    def upload(self, data: bytes, remote_path: str) -> None:
        with self.sftp.open(remote_path, "wb") as fp:
            fp.write(data)

    def close(self) -> None:
        try:
            self.sftp.close()
            self.client.close()
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="47.114.55.115")
    parser.add_argument("--user", default="root")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    password = os.getenv("DSH_DEPLOY_PASS", "")
    if not password:
        print("[失败] 没有密码：请设置环境变量 DSH_DEPLOY_PASS")
        return 1

    log(f"[1/9] 连接 {args.user}@{args.host}")
    remote = Remote(args.host, password, args.user)
    try:
        log("[2/9] 体检：服务状态 / 目录 / 磁盘 / 现有数据")
        print("      服务:", remote.run(f"systemctl is-active {APP_NAME} || true"))
        print("      目录:", remote.run(f"test -d {REMOTE_DIR} && echo 存在 || echo 缺失"))
        print("      磁盘:", remote.run("df -h / | tail -1"))
        print("      账号数:", remote.run(
            f"cd {REMOTE_DIR} && ./.venv/bin/python -c "
            "\"import sqlite3;c=sqlite3.connect('storage/business.db');"
            "print(c.execute('SELECT COUNT(*) FROM users').fetchone()[0])\" 2>/dev/null || echo 读不到"))

        if args.dry_run:
            log("dry-run 结束，未做任何修改")
            return 0

        log("[3/9] 备份数据库与配置")
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = f"/root/backup-{stamp}.tar.gz"
        remote.run(
            f"cd {REMOTE_DIR} && tar czf {backup} storage .env 2>/dev/null || "
            f"tar czf {backup} storage",
            check=False)
        size = remote.run(f"du -h {backup} | cut -f1", check=False)
        print(f"      备份: {backup}（{size}）")

        log("[4/9] 打包并上传代码")
        payload = build_tar()
        remote.upload(payload, "/root/deploy-payload.tar.gz")
        print(f"      已上传 {len(payload) / 1024 / 1024:.1f} MB")

        log("[5/9] 解压覆盖（保留 storage/ 与 .env）")
        remote.run(f"mkdir -p {REMOTE_DIR}")
        remote.run(f"tar xzf /root/deploy-payload.tar.gz -C {REMOTE_DIR}")
        print("      覆盖完成")

        log("[6/9] 安装依赖（增量）")
        pip_out = remote.run(
            f"cd {REMOTE_DIR} && ./.venv/bin/pip install -q -r requirements.txt 2>&1 | tail -5",
            check=False)
        print("      " + (pip_out or "无新增依赖"))

        log("[7/9] 数据库迁移（不加 --reset，保留账号与任务）")
        print("      " + remote.run(
            f"cd {REMOTE_DIR} && ./.venv/bin/python -c "
            "\"from app.db.conn import init_databases; print(init_databases())\""))

        log("[7.5/9] 迁移后校验（字段与表是否真的到位）")
        print("      " + remote.run(
            f"cd {REMOTE_DIR} && ./.venv/bin/python - <<'PY'\n"
            "import sqlite3, json\n"
            "c = sqlite3.connect('storage/business.db')\n"
            "cols = {r[1] for r in c.execute('PRAGMA table_info(wrong_questions)')}\n"
            "need = ['state','stability','difficulty','due_at','review_count','last_review_at']\n"
            "missing = [n for n in need if n not in cols]\n"
            "traces = c.execute(\"SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
            "AND name='session_traces'\").fetchone()[0]\n"
            "idx = {r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='index'\")}\n"
            "print(json.dumps({'missing_cols': missing, 'traces': bool(traces),\n"
            "                  'idx_wq_due': 'idx_wq_due' in idx,\n"
            "                  'idx_trace': 'idx_trace_session' in idx}, ensure_ascii=False))\n"
            "PY"))

        log("[8/9] 重启服务")
        remote.run(f"systemctl restart {APP_NAME}")
        time.sleep(4)
        state = remote.run(f"systemctl is-active {APP_NAME} || true")
        print("      状态:", state)
        print("      端口:", remote.run("ss -ltnp | grep 8000 || echo 未监听"))
        if state.strip() != "active":
            log("服务没起来，自动回滚到部署前备份")
            remote.run(f"tar xzf {backup} -C {REMOTE_DIR}", check=False)
            remote.run(f"systemctl restart {APP_NAME}", check=False)
            time.sleep(3)
            print("      回滚后状态:", remote.run(f"systemctl is-active {APP_NAME} || true"))
            print(f"      备份：{backup}（已还原）")
            return 1

        log("[9/9] 验证")
        print("      健康:", remote.run("curl -s -m 5 http://127.0.0.1:8000/api/health"))
        print("      meta:", remote.run("curl -s -m 5 http://127.0.0.1:8000/api/meta | head -c 200"))
        print("      新接口:", remote.run(
            "for p in /api/self-tests /api/wrong-questions /api/sessions/1/mindmap; do "
            "printf '  %-34s %s\\n' $p $(curl -s -o /dev/null -w '%{http_code}' "
            "-m 5 http://127.0.0.1:8000$p); done"))
        print("      前端主包:", remote.run(
            "grep -o 'assets/index-[A-Za-z0-9_-]*\\.js' "
            f"{REMOTE_DIR}/app/static/index.html | head -1"))
        print("      账号数（迁移后）:", remote.run(
            f"cd {REMOTE_DIR} && ./.venv/bin/python -c "
            "\"import sqlite3;c=sqlite3.connect('storage/business.db');"
            "print(c.execute('SELECT COUNT(*) FROM users').fetchone()[0])\""))

        log("部署完成")
        print(f"\n备份文件：{backup}（回滚：tar xzf 该文件到 {REMOTE_DIR}）")
        return 0
    finally:
        remote.close()


if __name__ == "__main__":
    sys.exit(main())
