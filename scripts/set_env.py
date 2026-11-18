"""安全地写 .env 里的模型配置。

为什么需要这个脚本：
    手动编辑 .env 容易出三类错——漏引号、把 key 写进注释、改完忘记重启服务。
    更糟的是在群里/文档里贴 key 检查是否正确。这个脚本只接收 key、不回显 key，
    并且自动备份原文件，改坏了能还原。

用法（在服务器上或本地都能用）：
    python scripts/set_env.py --key sk-xxxxxxxx
    python scripts/set_env.py --key sk-xxx --base-url https://api.deepseek.com/v1 --model deepseek-chat
    python scripts/set_env.py --show            # 只看当前配置（key 打码）
    python scripts/set_env.py --backup-only     # 只备份，不改

改完后需要重启服务才生效：
    systemctl restart course-note-agent
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
EXAMPLE_FILE = ROOT / ".env.example"

# 以 `python scripts/set_env.py` 方式运行时，sys.path[0] 是 scripts/，
# 直接 import app.* 会失败；把项目根目录补进来。
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"


def mask(key: str) -> str:
    if not key:
        return "（空）"
    if len(key) <= 12:
        return key[:3] + "***"
    return f"{key[:7]}***{key[-4:]}"


def _read_lines(path: Path) -> list[str]:
    """读 .env。

    必须用 utf-8-sig：Windows 上用记事本/Set-Content 保存的 .env 常带 BOM，
    若按 utf-8 读，第一行的键名会变成 '\\ufeffALLOWED_EXTENSIONS'，
    导致「明明写了却读不到、于是又追加一行」这种隐蔽问题。
    """
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8-sig").splitlines()


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in _read_lines(path):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        values[k.strip()] = v.split(" #")[0].strip().strip('"').strip("'")
    return values


def write_env(path: Path, updates: dict[str, str]) -> None:
    """按行替换，保留注释与顺序；键不存在则追加到末尾。

    额外处理两种情况：
      1. 文件带 UTF-8 BOM（Windows 常见）——用 utf-8-sig 读，写出时不带 BOM；
      2. 同一键出现多次（历史误追加）——保留第一次出现的位置并写入新值，
         后续重复行删除，避免「改了但没生效」的错觉。
    """
    lines = _read_lines(path)
    remaining = dict(updates)
    seen: set[str] = set()
    out: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                if key in seen:
                    continue          # 删除重复行
                seen.add(key)
                out.append(f"{key}={updates[key]}")
                remaining.pop(key, None)
                continue
        out.append(line.lstrip("\ufeff") if line.startswith("\ufeff") else line)

    if remaining:
        if out and out[-1].strip():
            out.append("")
        out.append("# 由 scripts/set_env.py 写入")
        for k, v in remaining.items():
            out.append(f"{k}={v}")

    # 写回时统一不带 BOM，避免 Linux 上首行被污染
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="安全写入模型配置到 .env")
    parser.add_argument("--key", help="API 密钥（不会回显）")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                        help="设置任意配置项，可重复。例如 "
                             "--set ALLOWED_EXTENSIONS=.pdf,.docx,.md")
    parser.add_argument("--formats-all", action="store_true",
                        help="把 ALLOWED_EXTENSIONS 设为解析器支持的全部格式"
                             "（省得手打一长串，也避免和代码不一致）")
    parser.add_argument("--show", action="store_true", help="查看当前配置（密钥打码）")
    parser.add_argument("--backup-only", action="store_true")
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()

    if args.show:
        cfg = read_env(ENV_FILE)
        if not cfg:
            print(f"未找到 {ENV_FILE}")
            return 1
        print(f"配置文件：{ENV_FILE}")
        for k in ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEYS", "SECRET_KEY", "OCR_ACCESS_KEY_ID"):
            if k not in cfg:
                continue
            v = cfg[k]
            if "KEY" in k or "SECRET" in k:
                first = v.split(",")[0]
                print(f"  {k:<18} = {mask(first)}" + (f"（共 {len(v.split(','))} 个）"
                                                      if "," in v else ""))
            else:
                print(f"  {k:<18} = {v}")
        return 0

    if not ENV_FILE.exists():
        if not EXAMPLE_FILE.exists():
            print(f"[失败] 既没有 .env 也没有 .env.example，路径不对？当前目录 {ROOT}")
            return 1
        shutil.copy(EXAMPLE_FILE, ENV_FILE)
        print(f"[ok] 已从 .env.example 创建 .env")

    if not args.no_backup:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = ENV_FILE.with_name(f".env.bak-{stamp}")
        shutil.copy(ENV_FILE, backup)
        print(f"[ok] 已备份原文件：{backup.name}")
    if args.backup_only:
        return 0

    updates: dict[str, str] = {}
    if args.key:
        key = args.key.strip()
        if not key.startswith("sk-"):
            print("[警告] 这个 key 不以 sk- 开头，多数模型的密钥都是这个前缀，请确认没有复制错")
        if re.search(r"\s", key):
            print("[失败] key 里包含空白字符，可能是复制时带进了换行，请重新复制")
            return 1
        if "主key" in key or "xxxx" in key:
            print("[失败] 这是 .env.example 里的占位符，不是真实密钥")
            return 1
        updates["LLM_API_KEYS"] = key
    if args.base_url:
        updates["LLM_BASE_URL"] = args.base_url.rstrip("/")
    if args.model:
        updates["LLM_MODEL"] = args.model
    if args.formats_all:
        # 直接从解析器取支持的扩展名，避免"代码支持了但配置没放行"这种不一致
        try:
            from app.services.parse import supported_formats

            formats = supported_formats()
        except Exception as exc:  # noqa: BLE001 - 依赖缺失时给出可操作的提示
            print(f"[失败] 无法读取解析器支持的格式：{exc}")
            print("       请确认在项目根目录执行，且已安装依赖"
                  "（./.venv/bin/python scripts/set_env.py ...）")
            return 1
        if not formats:
            print("[失败] 解析器没有返回任何支持的格式")
            return 1
        updates["ALLOWED_EXTENSIONS"] = ",".join(formats)
    for pair in args.set:
        if "=" not in pair:
            print(f"[失败] --set 需要 KEY=VALUE 形式，收到：{pair}")
            return 1
        k, _, v = pair.partition("=")
        k = k.strip()
        if not k:
            print(f"[失败] --set 的键为空：{pair}")
            return 1
        updates[k] = v.strip()
    if not updates:
        print("没有要改的项。用 --key 传密钥，或用 --show 查看当前配置。")
        return 2

    write_env(ENV_FILE, updates)

    cfg = read_env(ENV_FILE)
    print("[ok] 已写入：")
    print(f"     LLM_BASE_URL = {cfg.get('LLM_BASE_URL', DEFAULT_BASE_URL)}")
    print(f"     LLM_MODEL    = {cfg.get('LLM_MODEL', DEFAULT_MODEL)}")
    print(f"     LLM_API_KEYS = {mask(cfg.get('LLM_API_KEYS', '').split(',')[0])}")
    print()
    print("下一步：重启服务让配置生效")
    print("     systemctl restart course-note-agent       # 服务器上")
    print("     或直接重启你本地的 uvicorn 进程")
    print()
    print("然后验证（会真的调用一次模型）：")
    print("     python scripts/check_llm.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
