"""打包完整源码，并做完整性自检。

为什么需要这个脚本：
    手工压缩容易漏文件，而「漏了模块」这种问题的表现是同事那边 import 失败、
    启动不了，排查起来很费时间。这里在打包后立刻解压到临时目录、逐个文件核对、
    并真正导入关键模块，确认交付包是可运行的。

用法：
    python scripts/make_release.py            # 生成并自检
    python scripts/make_release.py --no-check # 只打包
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT.parent / "course-note-agent-complete.zip"

# 必须存在于交付包内的文件（缺任何一个都说明打包失败）
REQUIRED = [
    "README.md",
    "requirements.txt",
    ".env.example",
    ".gitignore",
    "deploy.sh",
    # 应用主体
    "app/main.py",
    "app/__init__.py",
    "app/core/__init__.py",
    "app/core/config.py",
    "app/core/security.py",
    "app/db/__init__.py",
    "app/db/conn.py",
    "app/db/repo_business.py",
    "app/db/schema.sql",
    "app/schemas/__init__.py",
    "app/schemas/agent_io.py",
    "app/schemas/api_io.py",
    "app/services/__init__.py",
    "app/services/llm.py",
    "app/services/parse.py",
    "app/services/query.py",
    "app/services/ingest.py",
    "app/services/ocr.py",
    "app/agents/__init__.py",
    "app/agents/pipeline.py",
    "app/api/__init__.py",
    "app/api/router.py",
    "app/api/deps.py",
    "app/api/routes_meta.py",
    "app/api/routes_auth.py",
    "app/api/routes_uploads.py",
    "app/api/routes_sessions.py",
    "app/api/routes_chat.py",
    "app/api/routes_admin.py",
    # 脚本
    "scripts/init_db.py",
    "scripts/selftest_pipeline.py",
    "scripts/inspect_materials.py",
    # 测试
    "tests/test_contracts.py",
    "tests/test_parse.py",
    "tests/test_api.py",
]

# 不进包的运行时产物
EXCLUDE_DIRS = {"__pycache__", "storage", "logs", ".pytest_cache", ".venv", "venv",
                ".idea", ".vscode", "node_modules", "dist"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".db", ".db-wal", ".db-shm", ".log"}
# 绝对不能进交付包的文件：真实配置文件与其备份。
# .env 里可能带真实 API 密钥，一旦随包外发就等于把密钥公开，而压缩包不可撤销。
# 只允许 *.example 模板通过。
EXCLUDE_NAMES = {".env", ".env.bak", ".env.local", ".env.production"}
EXCLUDE_NAME_PREFIXES = (".env.bak-",)
# 泄露检测：包内任何文件命中这些模式都视为打包失败
_SECRET_PATTERN = re.compile(r"\bsk-[A-Za-z0-9]{16,}\b")


def _looks_like_real_secret(token: str) -> bool:
    """区分真实密钥与模板里的占位符，避免误报导致无法打包。

    占位符特征：连续的 x（如 sk-xxxxxxxxxxxxxxxx）、含中文（如 sk-主key）、
    字符种类极少（如 sk-aaaaaaaaaaaaaaaa）。
    """
    body = token[3:]
    if len(body) < 16:
        return False
    if re.search(r"[xX]{6,}", body):          # 占位符常用 xxx 填充
        return False
    if re.search(r"[^\x00-\x7F]", body):      # 含中文说明
        return False
    if len(set(body)) <= 3:                    # 单字符重复
        return False
    return True


def _is_secret_config(name: str) -> bool:
    if name in EXCLUDE_NAMES or name.startswith(EXCLUDE_NAME_PREFIXES):
        return True
    # 放行模板：.env.example / .env.gpt.example
    return name.startswith(".env.") and not name.endswith(".example")


def collect(root: Path) -> list[Path]:
    files: list[Path] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if _is_secret_config(p.name):
            continue
        if p.suffix in EXCLUDE_SUFFIXES:
            continue
        files.append(p)
    return files


def build(root: Path, output: Path) -> tuple[int, str]:
    files = collect(root)
    if output.exists():
        output.unlink()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            arc = f"course-note-agent/{f.relative_to(root).as_posix()}"
            zf.write(f, arc)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()[:16]
    return len(files), digest


def verify(output: Path) -> list[str]:
    """解压到临时目录，核对必需文件，并尝试导入关键模块。"""
    problems: list[str] = []
    with tempfile.TemporaryDirectory(prefix="cna-release-") as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(output) as zf:
            zf.extractall(tmp_path)
        base = tmp_path / "course-note-agent"
        if not base.is_dir():
            return ["解压后找不到 course-note-agent 目录，包结构不对"]

        missing = [rel for rel in REQUIRED if not (base / rel).exists()]
        if missing:
            problems.append("缺少必需文件：" + "、".join(missing))

        # 真正导入一遍关键模块（不启动服务，避免占用端口）
        code = (
            "import sys; sys.path.insert(0, r'%s');"
            "import app.main, app.services.parse, app.services.query, app.services.llm,"
            " app.services.ocr, app.db.conn, app.schemas.agent_io, app.agents.pipeline;"
            "print('IMPORT_OK')" % str(base)
        )
        # 必须继承当前进程的环境（否则拿不到已安装的 fastapi 等依赖），只覆盖必要的几个变量
        env = {
            **os.environ,
            "PYTHONPATH": str(base),
            "PYTHONIOENCODING": "utf-8",
            "STORAGE_DIR": str(tmp_path / "storage"),
            "STATIC_DIR": str(tmp_path / "static"),
        }
        try:
            result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                                    text=True, timeout=180, env=env)
        except subprocess.TimeoutExpired:
            problems.append("导入自检超时（180 秒）")
            return problems

        if "IMPORT_OK" not in (result.stdout or ""):
            tail = (result.stderr or result.stdout or "").strip().splitlines()[-8:]
            problems.append("关键模块导入失败：\n    " + "\n    ".join(tail))

        # 确认没有把数据库、日志、缓存打进去。
        # 注意：导入过程会在 app/ 下新建 __pycache__，所以只在 zip 条目层面检查，
        # 不能用磁盘扫描（否则永远误报）。
        with zipfile.ZipFile(output) as zf:
            names = zf.namelist()
            contents = {n: zf.read(n) for n in names if n.endswith((".py", ".md", ".txt",
                                                                   ".example", ".sql", ".sh"))}
        junk = [n for n in names
                if "/__pycache__/" in n or "/storage/" in n or "/logs/" in n
                or n.endswith((".db", ".db-wal", ".db-shm", ".pyc", ".log"))]
        if junk:
            problems.append("包里混入了运行时产物：" + "、".join(junk[:5]))

        # 最要紧的一项：确认包内没有任何真实密钥
        leaked: list[str] = []
        for name, raw in contents.items():
            try:
                text = raw.decode("utf-8", "ignore")
            except Exception:  # noqa: BLE001
                continue
            for match in _SECRET_PATTERN.finditer(text):
                if _looks_like_real_secret(match.group(0)):
                    leaked.append(name)
                    break
        if leaked:
            problems.append("包内含疑似真实密钥，禁止交付：" + "、".join(leaked[:5]))
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="打包完整源码并自检")
    parser.add_argument("--no-check", action="store_true", help="只打包，不做自检")
    parser.add_argument("--out", default=str(OUTPUT))
    args = parser.parse_args()

    out = Path(args.out)
    count, digest = build(ROOT, out)
    size_kb = out.stat().st_size / 1024
    print(f"[ok] 已生成：{out}")
    print(f"[ok] {count} 个文件，{size_kb:.1f} KB，sha256 前 16 位：{digest}")

    if args.no_check:
        return 0

    print("[..] 正在解压并核对……")
    problems = verify(out)
    if problems:
        print("[FAIL] 交付包自检未通过：")
        for p in problems:
            print("   -", p)
        return 1
    print("[ok] 自检通过：必需文件齐全，关键模块可正常导入")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
