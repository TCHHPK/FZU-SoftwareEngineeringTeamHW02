"""本地 mock OpenAI 接口，用于在**没有真实密钥**的情况下验证客户端代码路径。

用途：
  1. 自测 scripts/verify_gpt.py 与 app/services/llm.py 的解析、错误处理逻辑；
  2. 前端/后端联调时不必消耗真实额度。

支持通过 URL 参数或请求内容触发特定错误，便于测试异常分支：
    /v1/chat/completions           正常返回
    带 header X-Mock-Status: 401   返回 401
    带 header X-Mock-Status: 404   返回 404
    带 header X-Mock-Status: 429   返回 429
    model 名包含 "badjson"         返回无法解析的文本（测试 JSON 兜底）
    model 名包含 "nojsonmode"      对 response_format 请求返回 400（测试降级）

运行：python scripts/mock_openai_server.py [端口]
"""

from __future__ import annotations

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SAMPLE_JSON = {
    "items": [
        {
            "name": "导数的定义",
            "definition": "函数在点 x0 处的导数描述函数在该点附近的变化率。",
            "key_points": ["记作 f'(x0)", "左导数与右导数相等才可导"],
            "quote": "函数 y=f(x) 在点 x0 处的导数记作 f'(x0)，描述函数在该点附近的变化率。",
        },
        {
            "name": "导数的几何意义",
            "definition": "曲线在点 (x0, f(x0)) 处切线的斜率。",
            "key_points": [],
            "quote": "几何意义：曲线在点 (x0, f(x0)) 处切线的斜率。",
        },
    ]
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # noqa: A003 - 覆盖父类，静音访问日志
        pass

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - http.server 约定
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._send(400, {"error": {"message": "invalid json"}})
            return

        forced = self.headers.get("X-Mock-Status")
        if forced:
            code = int(forced)
            self._send(code, {"error": {"message": f"mock forced status {code}"}})
            return

        auth = self.headers.get("Authorization") or ""
        if not auth.startswith("Bearer ") or len(auth) < 12:
            self._send(401, {"error": {"message": "missing or invalid api key (mock)"}})
            return

        model = str(payload.get("model") or "")
        wants_json = (payload.get("response_format") or {}).get("type") == "json_object"
        if wants_json and "nojsonmode" in model:
            self._send(400, {"error": {"message": "response_format not supported (mock)"}})
            return

        time.sleep(0.05)  # 模拟一点网络延迟
        if wants_json or "json" in model:
            content = "```json\n" + json.dumps(SAMPLE_JSON, ensure_ascii=False) + "\n```"
        elif "badjson" in model:
            content = "抱歉，我今天不太想输出 JSON。"
        else:
            content = "可用"

        self._send(200, {
            "id": "chatcmpl-mock",
            "object": "chat.completion",
            "model": model or "mock-model",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 128, "completion_tokens": 64, "total_tokens": 192},
        })


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8899
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"[mock] OpenAI 兼容接口已启动：http://127.0.0.1:{port}/v1")
    print("[mock] 可用任意长度 >= 12 的 Bearer key 调用；Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[mock] 已停止")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
