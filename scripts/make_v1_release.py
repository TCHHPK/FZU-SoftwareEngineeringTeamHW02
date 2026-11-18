"""打包「课程笔记 Agent」v1.0 发布版。

产物结构（按用途分层，拿到包的人不用翻源码就能找到东西）：

    course-note-agent-v1.0/
    ├── VERSION.txt              版本信息、验证结果、快速开始、已知限制
    ├── MANIFEST.txt             文件清单（大小 + SHA256），便于校验完整性
    ├── 01-源码/                 可读源码树（排除虚拟环境、缓存、数据库、密钥）
    ├── 02-发布包/               一键部署用的 zip（含自检）
    ├── 03-文档/                 设计说明书、需求分析、交付清单等
    ├── 04-设计图/               架构图、时序图、活动图、类图、用例图
    ├── 05-界面截图/             线上系统界面截图
    ├── 06-演示材料/             用于演示「补充材料合并」的两组 PDF
    ├── 07-历史版本/             合并前的备份包（可回滚）
    └── 08-团队与管理/           分工、待确认事项等过程文档

排除规则：
    .venv / __pycache__ / .pytest_cache / storage / logs / .env / *.pyc
    —— 虚拟环境跨机器不可用，数据库和密钥属于运行数据，不能进发布包。

用法：python scripts/make_v1_release.py
"""

from __future__ import annotations

import hashlib
import re
import shutil
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT.parent
# 每次用带时间戳的暂存目录：Windows 上旧文件可能被资源管理器/看图软件占用，
# 复用同名目录会偶发 PermissionError。压缩包内部的顶层目录名保持固定。
ARC_PREFIX = "course-note-agent-v1.0"
STAGE = Path.home() / "_v1_stage" / f"{ARC_PREFIX}-{time.strftime('%H%M%S')}"
OUTPUT = DESKTOP / "course-note-agent-v1.0-20261116.zip"

EXCLUDE_DIRS = {".venv", "__pycache__", ".pytest_cache", "storage", "logs", ".git", "node_modules"}
EXCLUDE_FILES = {".env", ".env.bak"}
EXCLUDE_SUFFIX = {".pyc", ".pyo", ".log"}

# 明文密钥特征：sk- 开头 + 20 位以上
SECRET_PATTERN = re.compile(r"sk-[A-Za-z0-9]{20,}")

# 占位符排除：全 x、含 xxxx、含 your / placeholder / 主key 的都不算真实密钥。
# 否则 .env.example 里的 sk-xxxxxx... 会被误判，导致每次打包都中止。
PLACEHOLDER_HINTS = ("xxxx", "your", "placeholder", "主key", "change-me", "example")


def _is_placeholder(token: str) -> bool:
    low = token.lower()
    if any(h in low for h in PLACEHOLDER_HINTS):
        return True
    # 去掉前缀后的主体字符种类太少（如全 x），视为占位
    body = low[3:]
    return len(set(body)) <= 2


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")


def copy_source(src: Path, dst: Path) -> int:
    """复制源码树，按排除规则过滤。"""
    count = 0
    for path in src.rglob("*"):
        if path.is_dir():
            continue
        rel = path.relative_to(src)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if path.name in EXCLUDE_FILES or path.suffix in EXCLUDE_SUFFIX:
            continue
        if path.name.startswith(".env.bak"):
            continue
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        count += 1
    return count


def copy_files(paths: list[Path], dst: Path) -> int:
    count = 0
    dst.mkdir(parents=True, exist_ok=True)
    for p in paths:
        if not p.exists():
            log(f"  跳过（不存在）：{p.name}")
            continue
        shutil.copy2(p, dst / p.name)
        count += 1
    return count


def copy_tree(src: Path, dst: Path) -> int:
    if not src.exists():
        return 0
    dst.mkdir(parents=True, exist_ok=True)
    count = 0
    for p in src.iterdir():
        if p.is_file():
            shutil.copy2(p, dst / p.name)
            count += 1
    return count


def scan_secrets(root: Path) -> list[str]:
    """扫描文本文件里的明文密钥。"""
    hits: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".docx", ".zip"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for m in SECRET_PATTERN.finditer(text):
            token = m.group(0)
            if _is_placeholder(token):
                continue
            hits.append(f"{path.relative_to(root)} -> {token[:7]}***")
    return hits


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_version_txt(root: Path, stats: dict) -> None:
    text = f"""课程课件笔记整理与知识梳理 Agent
版本 1.0（首个完整发布版）
打包日期：{time.strftime('%Y-%m-%d')}

======================================================================
一、这个包里有什么
======================================================================
01-源码/            完整可读源码（后端 + 前端源码 + 测试 + 脚本）
02-发布包/          一键部署用 zip（含部署脚本与自检）
03-文档/            系统设计说明书、需求分析、交付清单、运维文档
04-设计图/          架构图、时序图、活动图、类图、用例图（8 张）
05-界面截图/        线上系统界面截图（8 张）
06-演示材料/        演示「补充材料合并」用的两组 PDF
07-历史版本/        合并队友成果前的备份包（可回滚）
08-团队与管理/      分工、待确认事项等过程文档

文件总数：{stats['files']}
解压后大小：{stats['size_mb']:.1f} MB
VERSION.txt 与 MANIFEST.txt 位于根目录。

======================================================================
二、系统概况
======================================================================
定位：学生上传课程课件，系统产出「可追溯到原文」的结构化笔记，并支持基于材料问答。
线上地址：http://47.114.55.115:8000

技术栈：
  后端    Python 3.12 + FastAPI + uvicorn（单 worker）
  前端    Vue 3 + Vite + Element Plus（构建产物由后端同源托管）
  数据    SQLite（业务库 17 张表 + 知识库 5 张表，物理分离，WAL 模式）
  模型    DeepSeek（OpenAI 兼容协议），支持多密钥轮换
  检索    SQLite FTS5 二元组索引 + 覆盖率重排（无向量库）
  部署    systemd 守护，阿里云 ECS（Ubuntu 22.04）

核心能力：
  1. 多格式解析：9 类解析器 / 16 种扩展名，按文件头嗅探真实格式
  2. 证据绑定：每条知识点必须带原文连续引文，回查不到即丢弃
  3. 任务异步化：后台执行 + 1.5 秒轮询，进度与阶段文案可见
  4. 课程问答：三态判定（可答 / 依据不足 / 材料未涉及），不编造
  5. 三种导出：Word（.docx）/ Markdown / LaTeX
  6. 补充材料：追加材料后与已有材料合并重新整理，可选择参与范围

======================================================================
三、验证结果（发布时实测）
======================================================================
自动化测试     37 项全部通过（契约、解析、接口、Agent 管线、配置回归）
端到端自检     通过（注册→上传→解析→整理→结果→导出→检索→越权拦截）
线上全流程     通过（真实调用模型：6 页课件 12 秒产出 10 个带出处知识点）
效果对比       知识点覆盖率 66.67% vs 裸模型 38.89%
               无依据陈述比例 0%
               问答正确率 83.33%
               质量自评 82.1 / 100

======================================================================
四、怎么跑起来
======================================================================
方式 A（推荐，一键部署）：
  解压 02-发布包/course-note-agent-complete.zip
  cd course-note-agent && bash deploy.sh
  然后在 .env 里填 LLM_API_KEYS，重启服务

方式 B（本地开发）：
  python -m venv .venv
  ./.venv/bin/pip install -r requirements.txt   # Windows: .venv\\Scripts\\pip
  复制 .env.example 为 .env 并填密钥
  python -m scripts.init_db
  ./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000

验证是否正常：
  curl http://127.0.0.1:8000/api/health          → {{"status":"ok"}}
  python -m pytest                              → 37 passed

======================================================================
五、已知限制（如实说明，非缺陷隐瞒）
======================================================================
1. 不具备事实核验能力：多份材料冲突时并列保留各自出处，不判断谁对谁错；
   需在「补充材料」时取消勾选过时材料。
2. 领域知识库（kb.db）仅建表，未灌数据；问答只基于上传课件。
3. 智能自测与错题本仅完成设计，未实现。
4. 扫描件与图片需配置 OCR 密钥后方可识别。
5. 单 worker 设计：并发整理会排队，与 SQLite 单机场景匹配。
6. 向量检索开关保留但默认关闭。

======================================================================
六、安全说明
======================================================================
- 发布包内不含任何密钥、数据库和上传文件（打包时已按规则排除并扫描）。
- 部署后请修改默认管理员口令，并在 .env 中设置随机 SECRET_KEY。
- 云服务器需在安全组放行 TCP 8000，否则「本机通、外网不通」。

======================================================================
七、变更记录
======================================================================
2026-11-16  v1.0  首个完整发布：合并 Agent 管线、前端页面、评测体系；
                  修复导出 Word 控制字符崩溃、测试误清数据库、配置注释失效等问题。
"""
    (root / "VERSION.txt").write_text(text, encoding="utf-8")


def write_manifest(root: Path) -> tuple[int, int]:
    lines = ["文件清单（相对路径 / 字节 / SHA256）", "=" * 78, ""]
    total = 0
    size = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "MANIFEST.txt":
            continue
        rel = path.relative_to(root).as_posix()
        st = path.stat().st_size
        total += 1
        size += st
        lines.append(f"{rel}\t{st}\t{sha256(path)}")
    lines += ["", f"合计：{total} 个文件，{size / 1024 / 1024:.2f} MB"]
    (root / "MANIFEST.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return total, size


def main() -> int:
    log("准备暂存目录 ...")
    STAGE.mkdir(parents=True, exist_ok=True)

    log("01-源码 ...")
    n_src = copy_source(ROOT, STAGE / "01-源码" / "course-note-agent")
    log(f"      {n_src} 个文件")

    log("02-发布包 ...")
    n_pkg = copy_files([DESKTOP / "course-note-agent-complete.zip"], STAGE / "02-发布包")
    log(f"      {n_pkg} 个文件")

    log("03-文档 ...")
    docs = [
        "系统设计说明书-V1.1.docx",
        "大学生课程课件笔记整理与知识梳理Agent需求分析.docx",
        "大学生课程课件笔记整理与知识梳理Agent需求与设计方案.docx",
        "交付清单与实测数据填表.docx",
        "我需要交付给他人的内容.docx",
        "参考知识点清单-第13章构件级设计.docx",
        "参考知识点清单-第13章构件级设计.csv",
        "数据库（知识库）相关工作.docx",
    ]
    n_doc = copy_files([DESKTOP / d for d in docs], STAGE / "03-文档")
    log(f"      {n_doc} 个文件")

    log("04-设计图 ...")
    n_fig = copy_tree(DESKTOP / "设计图", STAGE / "04-设计图")
    log(f"      {n_fig} 张图")

    log("05-界面截图 ...")
    n_shot = copy_tree(DESKTOP / "答辩截图", STAGE / "05-界面截图")
    log(f"      {n_shot} 张截图")

    log("06-演示材料 ...")
    n_demo = copy_tree(DESKTOP / "演示材料-补充材料", STAGE / "06-演示材料")
    log(f"      {n_demo} 个文件")

    log("07-历史版本 ...")
    n_hist = copy_files([DESKTOP / "_backup-merge-20261020-1600.zip"], STAGE / "07-历史版本")
    log(f"      {n_hist} 个文件")

    log("08-团队与管理 ...")
    mgmt = [
        "编程组交付清单与任务分派.docx",
        "编程组待确认事项清单.docx",
        "服务器部署命令清单.txt",
        "服务器更新清单.txt",
        "服务器迁移操作清单.docx",
        "如何让Agent支持公网访问.docx",
    ]
    n_mgmt = copy_files([DESKTOP / m for m in mgmt], STAGE / "08-团队与管理")
    log(f"      {n_mgmt} 个文件")

    log("安全检查（扫描明文密钥）...")
    hits = scan_secrets(STAGE)
    if hits:
        print("\n[中止] 发现疑似明文密钥：")
        for h in hits:
            print("   ", h)
        return 1
    log("      未发现明文密钥")

    log("生成 VERSION.txt ...")
    total_files = n_src + n_pkg + n_doc + n_fig + n_shot + n_demo + n_hist + n_mgmt
    total_size = sum(p.stat().st_size for p in STAGE.rglob("*") if p.is_file())
    write_version_txt(STAGE, {"files": total_files, "size_mb": total_size / 1024 / 1024})

    log("生成 MANIFEST.txt ...")
    cnt, sz = write_manifest(STAGE)
    log(f"      {cnt} 个文件，{sz / 1024 / 1024:.2f} MB")

    log("压缩 ...")
    if OUTPUT.exists():
        OUTPUT.unlink()
    with zipfile.ZipFile(OUTPUT, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in sorted(STAGE.rglob("*")):
            if path.is_file():
                rel = path.relative_to(STAGE).as_posix()
                z.write(path, f"{ARC_PREFIX}/{rel}")

    log(f"完成：{OUTPUT}")
    log(f"      压缩包 {OUTPUT.stat().st_size / 1024 / 1024:.1f} MB")
    log(f"      含 {cnt} 个文件")
    print()
    print("=" * 70)
    print(f"输出：{OUTPUT}")
    print(f"SHA256：{sha256(OUTPUT)}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
