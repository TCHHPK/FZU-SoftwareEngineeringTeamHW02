"""GPT（OpenAI 兼容接口）连通性验证脚本。

用途：拿到别人的 API Key 后，先确认「这台机器能不能真的调通」，再决定是否作为备用/基线。
很多组的备用 key 从来没验证过，出事时才发现是死的 —— 这个脚本就是防这个。

用法（三种方式任选，推荐第一种）：

    # 1. 复制 .env.gpt.example 为 .env.gpt，填好后运行
    python scripts/verify_gpt.py --env .env.gpt

    # 2. 直接给参数（key 会留在命令历史里，不推荐）
    python scripts/verify_gpt.py --base-url https://xxx/v1 --model gpt-4o-mini --key sk-xxx

    # 3. 用环境变量
    set GPT_BASE_URL=https://xxx/v1 & set GPT_MODEL=gpt-4o-mini & set GPT_API_KEY=sk-xxx
    python scripts/verify_gpt.py

脚本会依次检查：
    ① 网络能否连通到 base_url
    ② key 是否有效（401/403 会明确提示）
    ③ 模型名是否存在（404 会提示）
    ④ 普通对话是否正常返回
    ⑤ JSON 模式是否可用（本系统的结构化抽取依赖它，不可用会自动降级解析）
    ⑥ 反应时间与用量
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TIMEOUT = 60


def load_env_file(path: Path) -> dict[str, str]:
    """极简 .env 解析：只支持 KEY=VALUE，忽略注释与空行。"""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def mask(secret: str) -> str:
    if len(secret) <= 12:
        return "***"
    return f"{secret[:7]}...{secret[-4:]}"


def preflight(base_url: str, timeout: int = 8) -> str | None:
    """先做 TCP 可达性预检，把「网络不通」与「服务慢/报错」区分开。

    返回 None 表示可达；否则返回给用户看的诊断建议。
    """
    from urllib.parse import urlparse

    parsed = urlparse(base_url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not host:
        return f"base_url 格式不对：{base_url}"

    import socket

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return None
    except socket.timeout:
        return (f"连接 {host}:{port} 超时（{timeout}s）。\n"
                "       若这是 api.openai.com，说明当前网络无法直连：\n"
                "       OpenAI 的服务不在中国大陆可用区域内，需要代理或改用第三方中转地址。")
    except OSError as exc:
        return (f"无法连接 {host}:{port} —— {exc}\n"
                "       请检查 base_url 是否写错（常见错误：漏了 /v1、协议写成 http）。")


def main() -> int:
    parser = argparse.ArgumentParser(description="验证 OpenAI 兼容接口是否可用")
    parser.add_argument("--env", default=".env.gpt", help="存放配置的文件（默认 .env.gpt）")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--key", default=None)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    args = parser.parse_args()

    env_file = load_env_file(ROOT / args.env)
    base_url = (args.base_url or env_file.get("GPT_BASE_URL")
                or os.getenv("GPT_BASE_URL") or "").rstrip("/")
    model = args.model or env_file.get("GPT_MODEL") or os.getenv("GPT_MODEL") or ""
    key = args.key or env_file.get("GPT_API_KEY") or os.getenv("GPT_API_KEY") or ""

    print("=" * 68)
    print("GPT 接口连通性验证")
    print("=" * 68)
    print(f"  base_url : {base_url or '（未提供）'}")
    print(f"  model    : {model or '（未提供）'}")
    print(f"  api key  : {mask(key) if key else '（未提供）'}")

    if not base_url or not model or not key:
        print("\n[失败] 缺少参数。请复制 .env.gpt.example 为 .env.gpt 并填写，"
              "或使用 --base-url / --model / --key 传入。")
        return 2

    print("\n[0/3] 网络可达性预检 ...")
    problem = preflight(base_url)
    if problem:
        print(f"      [失败] {problem}")
        return 1
    print("      [通过] 目标地址可连接")

    url = f"{base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def call(payload: dict) -> tuple[int, dict | str]:
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=args.timeout)
        except requests.exceptions.Timeout:
            return 0, f"请求超时（{args.timeout}s）。可能是网络不通或需要代理。"
        except requests.exceptions.SSLError as exc:
            return 0, f"TLS 握手失败：{exc}。若使用中转服务，请确认地址协议是否正确。"
        except requests.exceptions.ConnectionError as exc:
            return 0, (f"无法连接到 {base_url}：{exc}\n"
                       "       若是 api.openai.com，说明当前网络无法直连（需要代理或改用中转服务）。")
        except Exception as exc:  # noqa: BLE001
            return 0, f"请求异常：{type(exc).__name__}: {exc}"
        try:
            return resp.status_code, resp.json()
        except ValueError:
            return resp.status_code, resp.text[:400]

    # ① 普通对话
    print("\n[1/3] 普通对话测试 ...")
    started = time.time()
    code, body = call({
        "model": model,
        "messages": [{"role": "user", "content": "回复两个字：可用"}],
        "max_tokens": 16,
    })
    elapsed = time.time() - started

    if code == 0:
        print(f"      [失败] {body}")
        return 1
    if code in (401, 403):
        print(f"      [失败] HTTP {code}：key 无效、已吊销或无权访问该模型。{body}")
        return 1
    if code == 404:
        print(f"      [失败] HTTP 404：模型名 `{model}` 可能不存在，或 base_url 路径不对"
              f"（应为 .../v1）。响应：{body}")
        return 1
    if code == 429:
        print(f"      [警告] HTTP 429：key 可用但当前被限流或额度已用尽。{body}")
        return 1
    if code >= 400:
        print(f"      [失败] HTTP {code}：{body}")
        return 1

    try:
        content = body["choices"][0]["message"]["content"]
        usage = body.get("usage", {})
        print(f"      [通过] 返回：{content.strip()[:40]!r}")
        print(f"             耗时 {elapsed:.1f}s，tokens: "
              f"prompt={usage.get('prompt_tokens')} completion={usage.get('completion_tokens')}")
    except (KeyError, IndexError, TypeError):
        print(f"      [警告] 返回结构不是标准 OpenAI 格式：{str(body)[:200]}")
        return 1

    # ② JSON 模式（本系统结构化抽取依赖）
    print("\n[2/3] JSON 模式测试 ...")
    code, body = call({
        "model": model,
        "messages": [{"role": "user",
                      "content": '以 JSON 返回：{"items":[{"name":"导数的定义"}]}'}],
        "response_format": {"type": "json_object"},
        "max_tokens": 64,
    })
    if code == 200:
        print("      [通过] 支持 response_format=json_object")
    else:
        print(f"      [提示] 不支持 JSON 模式（HTTP {code}）。"
              "本系统会自动降级为「从文本中抠 JSON」，功能不受影响。")

    # ③ 中文长文本（模拟真实课件片段）
    print("\n[3/3] 中文长文本测试（模拟课件片段抽取）...")
    sample = ("函数 y=f(x) 在点 x0 处的导数记作 f'(x0)，描述函数在该点附近的变化率。"
              "几何意义：曲线在点 (x0, f(x0)) 处切线的斜率。"
              "可导必连续，连续不一定可导。")
    started = time.time()
    code, body = call({
        "model": model,
        "messages": [
            {"role": "system",
             "content": "你是课件笔记整理助手。只依据给定原文输出，禁止编造。"
                        '以 JSON 返回：{"items":[{"name":"","definition":"",'
                        '"key_points":[],"quote":""}]}，quote 必须是原文连续片段。'},
            {"role": "user", "content": f"【课件原文】\n{sample}"},
        ],
        "temperature": 0.2,
        "max_tokens": 512,
    })
    if code != 200:
        print(f"      [失败] HTTP {code}：{str(body)[:300]}")
        return 1

    content = body["choices"][0]["message"]["content"]
    print(f"      [通过] 耗时 {time.time() - started:.1f}s")
    print("      原始返回：")
    for line in content.strip().splitlines()[:12]:
        print(f"        {line[:100]}")

    # 顺带检查它是否遵守了「引文必须是原文片段」
    try:
        parsed = json.loads(content[content.find("{"):content.rfind("}") + 1])
        quotes = [it.get("quote", "") for it in parsed.get("items", [])]
        hit = [q for q in quotes if q and q in sample]
        print(f"\n      引文核验：{len(hit)}/{len(quotes)} 条能在原文中找到"
              f"{'（表现良好）' if hit else '（未给出可核验引文，整理结果需依赖系统侧证据校验兜底）'}")
    except Exception:  # noqa: BLE001
        print("\n      [提示] 返回内容不是合法 JSON，系统会自动降级解析。")

    print("\n" + "=" * 68)
    print("结论：该接口可用。可将以下三行写入 .env 作为备用或对比实验基线：")
    print(f"  LLM_BASE_URL={base_url}")
    print(f"  LLM_MODEL={model}")
    print(f"  LLM_API_KEYS={mask(key)}   # 真实值请勿写入仓库或聊天群")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
