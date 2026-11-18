"""pytest 配置：项目根目录加入 sys.path，并把存储目录隔离到临时路径。

为什么要隔离（踩过的坑）：
    测试里有"建库 → 注册 → 上传 → 整理"的完整流程，会调用 init_db 重建表。
    如果 STORAGE_DIR 仍指向项目的 storage/，跑一次 `python -m pytest`
    就会把**真实数据库里的账号和任务清空**。
    本机被清过两次，如果在服务器上执行，线上用户会一起消失。

做法：
    在导入任何 app 模块之前，先把 STORAGE_DIR / UPLOAD_DIR / KB_DB
    指向临时目录；同时关掉真实模型调用（走占位实现），避免测试花钱。
    python-dotenv 默认不覆盖已存在的环境变量（override=False），
    所以这里设置的优先级高于 .env。

用法：
    python -m pytest -q                 # 全部测试
    python -m pytest tests/test_api.py -q
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ---- 存储隔离（必须在 import app.* 之前执行）----
_TMP = Path(tempfile.mkdtemp(prefix="cna-test-"))
os.environ["STORAGE_DIR"] = str(_TMP)
os.environ["UPLOAD_DIR"] = str(_TMP / "uploads")
os.environ["KB_DB"] = str(_TMP / "kb.db")
os.environ["BUSINESS_DB"] = str(_TMP / "business.db")

# 测试不调用真实模型：省费用，也避免网络导致的偶发失败
os.environ["AGENT_STUB"] = "1"
os.environ["LLM_API_KEYS"] = ""

atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))
