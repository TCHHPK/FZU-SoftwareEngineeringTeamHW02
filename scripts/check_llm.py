"""验证 .env 里的模型配置是否真的可用。

会真的调用一次模型，输出「通/不通」和原因，**不打印密钥**。
这是团队里唯一需要的检查命令——比在群里贴 key 让人帮看安全得多。

用法：
    python scripts/check_llm.py
    python scripts/check_llm.py --env C:\\path\\to\\.env
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.services.llm import LLMClient, LLMConfig, LLMError  # noqa: E402


def mask(key: str) -> str:
    if not key:
        return "（未配置）"
    return f"{key[:7]}***{key[-4:]}" if len(key) > 12 else "***"


def main() -> int:
    print("=" * 66)
    print("模型配置检查")
    print("=" * 66)
    print(f"  base_url   : {settings.llm_base_url}")
    print(f"  model      : {settings.llm_model}")
    print(f"  超时/重试   : {settings.llm_timeout}s / {settings.llm_max_retries} 次")

    cfg = LLMConfig.from_env()
    print(f"  api key    : {mask(cfg.api_keys[0]) if cfg.api_keys else '（未配置）'}"
          + (f"（共 {len(cfg.api_keys)} 个，会自动轮换）" if len(cfg.api_keys) > 1 else ""))

    if not cfg.api_keys:
        print("\n[失败] .env 里没有可用的 LLM_API_KEYS。")
        print("       修复：python scripts/set_env.py --key sk-你的密钥")
        return 2
    if cfg.api_keys[0].startswith("sk-主key") or "xxxx" in cfg.api_keys[0]:
        print("\n[失败] 检测到占位符，不是真实密钥。")
        print("       修复：python scripts/set_env.py --key sk-你的密钥")
        return 2

    print("\n[..] 正在调用模型（最多等 %d 秒）…" % settings.llm_timeout)
    client = LLMClient(cfg)
    try:
        reply = client.chat("你是一个测试助手。", "只回复两个字：可用", max_tokens=16)
    except LLMError as exc:
        print(f"\n[失败] 调用失败：{exc}")
        print("\n可能的原因：")
        print("  · 密钥无效、已删除或额度用尽 → 去 platform.deepseek.com 确认")
        print("  · base_url 与密钥不是同一家 → 检查 LLM_BASE_URL")
        print("  · 服务器无法访问外网 → curl -I https://api.deepseek.com")
        return 1

    print(f"[通过] 模型返回：{reply.strip()[:60]!r}")
    usage = client.usage.summary() if hasattr(client, "usage") else {}
    if usage:
        print(f"[通过] 用量：prompt={usage.get('prompt_tokens')} "
              f"completion={usage.get('completion_tokens')} "
              f"耗时={usage.get('elapsed_sec')}s")

    # JSON 模式单独检查：管线依赖它做结构化抽取
    print("\n[..] 检查 JSON 模式（管线依赖）…")
    try:
        data = client.json_call(
            "只输出 JSON，不要解释。",
            '以 JSON 返回：{"items":[{"name":"测试"}]}',
            default=None,
        )
    except LLMError as exc:
        print(f"[警告] JSON 模式调用失败：{exc}（系统会自动降级解析，不致命）")
        data = None
    if data is None:
        print("[警告] 模型未返回可解析的 JSON；系统会走文本兜底，功能可用但稳定性略降")
    else:
        print(f"[通过] JSON 模式可用：{str(data)[:80]}")

    print("\n" + "=" * 66)
    print("结论：配置可用，可以开始跑整理任务了")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
