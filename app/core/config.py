"""应用配置：统一从环境变量读取，含功能开关。

不引入 pydantic-settings，减少依赖；所有默认值都必须是「安全且不依赖外部服务」的。

注意：settings 是模块级单例，所有字段在**导入本模块时**就取值完毕。
因此 .env 必须在取值之前加载好 —— 下面这段就是干这个的。
（曾经漏了这步，导致服务器上 .env 里的功能开关、上传限制全部被忽略，
 表现为「接口返回的 features 全是 false」，排查成本很高。）
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]

# 尽早加载 .env：settings 之后的所有 os.getenv 都依赖它
try:  # pragma: no cover - 取决于运行环境是否装了 python-dotenv
    from dotenv import load_dotenv

    _ENV_FILE = Path(os.getenv("ENV_FILE", BASE_DIR / ".env"))
    if _ENV_FILE.exists():
        # override=False：已存在的真实环境变量优先，便于临时覆盖
        load_dotenv(_ENV_FILE, override=False)
except ImportError:
    pass


def _clean(raw: str | None) -> str:
    """去掉首尾空白与行内注释。

    .env 里很常见的写法是 `ENABLE_EXAMPLE=1    # OP-01 例题整理`。
    python-dotenv 在部分写法下会把 ` # 注释` 一起当成值，导致
    `"1    # OP-01..."` 既不等于 "1"、转 int 还会直接抛错。
    本项目真踩过这个坑：服务器上所有功能开关都显示为 false，
    排查很久才定位到注释被读进了值里。
    """
    if raw is None:
        return ""
    return raw.split("#", 1)[0].strip()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return _clean(raw).lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = _clean(raw)
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = _clean(raw)
    try:
        return float(value)
    except ValueError:
        return default


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if not raw:
        return default
    # 必须在 split(",") 之前去掉注释，否则最后一项会带上一段注释文本
    cleaned = _clean(raw)
    items = [x.strip() for x in cleaned.split(",") if x.strip()]
    return items or default


@dataclass
class Settings:
    # 应用
    app_name: str = "大学生课程课件笔记整理与知识梳理 Agent"
    host: str = os.getenv("APP_HOST", "0.0.0.0")
    port: int = _env_int("APP_PORT", 8000)
    debug: bool = _env_bool("APP_DEBUG", False)
    # 会话签名密钥：上线必须改，否则任何人都能伪造登录态
    secret_key: str = os.getenv("SECRET_KEY", "dev-only-insecure-secret-change-me")
    session_max_age: int = _env_int("SESSION_MAX_AGE", 7 * 24 * 3600)
    cookie_name: str = "cna_session"

    # 存储与上传
    storage_dir: Path = Path(os.getenv("STORAGE_DIR", BASE_DIR / "storage"))
    upload_dir: Path = Path(os.getenv("UPLOAD_DIR", BASE_DIR / "storage" / "uploads"))
    max_upload_mb: int = _env_int("MAX_UPLOAD_MB", 50)
    # 与 app/services/parse.py 的 SUPPORTED_EXTENSIONS 保持一致；
    # 通过 ALLOWED_EXTENSIONS 可收紧（例如只允许 pdf 与 pptx）
    allowed_extensions: list[str] = field(default_factory=lambda: _env_list(
        "ALLOWED_EXTENSIONS",
        [".pdf", ".pptx", ".docx", ".txt", ".md", ".markdown", ".html", ".htm",
         ".csv", ".epub", ".png", ".jpg", ".jpeg"]))

    # 静态资源（前端构建产物）
    static_dir: Path = Path(os.getenv("STATIC_DIR", BASE_DIR / "app" / "static"))

    # 大模型（OpenAI 兼容协议；默认值写在 .env.example 里，这里只做兜底）
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
    llm_model: str = os.getenv("LLM_MODEL", "deepseek-chat")
    llm_timeout: int = _env_int("LLM_TIMEOUT", 120)
    llm_max_retries: int = _env_int("LLM_MAX_RETRIES", 3)
    llm_temperature: float = _env_float("LLM_TEMPERATURE", 0.2)
    llm_max_tokens: int = _env_int("LLM_MAX_TOKENS", 4096)

    # 功能开关：未实现的功能一律置 0，不在界面上留半成品入口
    enable_vector: bool = _env_bool("ENABLE_VECTOR", False)
    enable_example: bool = _env_bool("ENABLE_EXAMPLE", True)
    enable_note_merge: bool = _env_bool("ENABLE_NOTE_MERGE", True)
    enable_exam_scope: bool = _env_bool("ENABLE_EXAM_SCOPE", True)
    enable_quality_eval: bool = _env_bool("ENABLE_QUALITY_EVAL", True)
    enable_formula_ocr: bool = _env_bool("ENABLE_FORMULA_OCR", False)

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def features(self) -> dict[str, bool]:
        return {
            "vector_search": self.enable_vector,
            "example": self.enable_example,
            "note_merge": self.enable_note_merge,
            "exam_scope": self.enable_exam_scope,
            "quality_eval": self.enable_quality_eval,
            "formula_ocr": self.enable_formula_ocr,
        }


settings = Settings()
settings.upload_dir.mkdir(parents=True, exist_ok=True)
settings.storage_dir.mkdir(parents=True, exist_ok=True)
