"""OCR 接入层：图片与扫描件 → 文字。

默认使用阿里云「文字识别（OCR）」的通用文字识别接口，
原因：国内直连、有每月免费额度、返回结构简单。
官方免费额度说明：https://help.aliyun.com/zh/ocr/product-overview/free-quota.md
（通用文字识别、公式识别等各有 200 次/月的免费额度，具体以官方页面为准）

未配置密钥时 ocr_available() 返回 False，调用方应给出**可操作的提示**，
而不是返回空文本假装解析成功。

在 .env 中配置：
    OCR_PROVIDER=aliyun
    OCR_ACCESS_KEY_ID=...
    OCR_ACCESS_KEY_SECRET=...
    OCR_ENDPOINT=ocr-api.cn-hangzhou.aliyuncs.com
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ENDPOINT = "ocr-api.cn-hangzhou.aliyuncs.com"
DEFAULT_ACTION = "RecognizeGeneral"      # 通用文字识别
FORMULA_ACTION = "RecognizeFormula"      # 公式识别（同样在免费额度内）
API_VERSION = "2021-07-07"


class OCRError(RuntimeError):
    """OCR 调用失败。消息面向用户，可直接展示。"""


@dataclass
class OCRConfig:
    provider: str = "aliyun"
    access_key_id: str = ""
    access_key_secret: str = ""
    endpoint: str = DEFAULT_ENDPOINT
    timeout: int = 30

    @classmethod
    def from_env(cls) -> "OCRConfig":
        return cls(
            provider=(os.getenv("OCR_PROVIDER", "aliyun") or "aliyun").strip().lower(),
            access_key_id=(os.getenv("OCR_ACCESS_KEY_ID") or "").strip(),
            access_key_secret=(os.getenv("OCR_ACCESS_KEY_SECRET") or "").strip(),
            endpoint=(os.getenv("OCR_ENDPOINT") or DEFAULT_ENDPOINT).strip(),
            timeout=int(os.getenv("OCR_TIMEOUT", "30")),
        )


def ocr_available() -> bool:
    cfg = OCRConfig.from_env()
    if cfg.provider != "aliyun":
        return False
    return bool(cfg.access_key_id and cfg.access_key_secret)


def ocr_status() -> str:
    """给管理端/诊断脚本看的一行状态说明。"""
    cfg = OCRConfig.from_env()
    if cfg.provider != "aliyun":
        return f"未启用（OCR_PROVIDER={cfg.provider} 暂不支持）"
    if not (cfg.access_key_id and cfg.access_key_secret):
        return "未配置密钥（需要 OCR_ACCESS_KEY_ID 与 OCR_ACCESS_KEY_SECRET）"
    return f"已配置：aliyun / {cfg.endpoint}"


# --------------------------------------------------------------------------
# 阿里云签名（POP RPC 风格，v3 签名，HMAC-SHA256）
# --------------------------------------------------------------------------
def _percent_encode(value: str) -> str:
    return urllib.parse.quote(str(value), safe="~")


def _sign(cfg: OCRConfig, action: str, body: bytes) -> tuple[str, dict[str, str]]:
    """构造带签名的请求 URL 与请求头。"""
    now = time.gmtime()
    date = time.strftime("%Y-%m-%dT%H:%M:%SZ", now)
    nonce = uuid.uuid4().hex

    payload_hash = hashlib.sha256(body).hexdigest()
    query = {
        "Action": action,
        "Version": API_VERSION,
        "Format": "JSON",
        "Timestamp": date,
        "SignatureNonce": nonce,
        "SignatureMethod": "HMAC-SHA256",
        "SignatureVersion": "1.0",
        "AccessKeyId": cfg.access_key_id,
    }
    canonical_query = "&".join(
        f"{_percent_encode(k)}={_percent_encode(v)}" for k, v in sorted(query.items()))

    # POP v3：签名串 = METHOD\nAccept\nContent-MD5\nContent-Type\nDate\nHeaders\nPathAndQuery
    string_to_sign = "\n".join([
        "POST",
        "application/json",
        hashlib.md5(body).hexdigest(),
        "application/json",
        date,
        f"x-acs-signature-nonce:{nonce}\nx-acs-version:{API_VERSION}",
        f"/?{canonical_query}",
    ])
    signature = base64.b64encode(
        hmac.new(cfg.access_key_secret.encode(), string_to_sign.encode(),
                 hashlib.sha256).digest()).decode()

    url = f"https://{cfg.endpoint}/?{canonical_query}&Signature={_percent_encode(signature)}"
    headers = {
        "Content-Type": "application/json",
        "Date": date,
        "x-acs-signature-nonce": nonce,
        "x-acs-version": API_VERSION,
        "x-acs-action": action,
    }
    return url, headers


def _call(cfg: OCRConfig, action: str, payload: dict) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    url, headers = _sign(cfg, action, body)
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        if exc.code in (401, 403):
            raise OCRError(f"OCR 鉴权失败（HTTP {exc.code}）：请检查 AccessKey 是否正确、"
                           f"是否已开通文字识别服务。{detail}") from exc
        raise OCRError(f"OCR 调用失败（HTTP {exc.code}）：{detail}") from exc
    except urllib.error.URLError as exc:
        raise OCRError(f"OCR 服务无法连接：{exc}。请确认服务器网络可访问 {cfg.endpoint}") from exc
    except json.JSONDecodeError as exc:
        raise OCRError(f"OCR 返回内容无法解析：{exc}") from exc


def _extract_text(data: dict) -> str:
    """从阿里云返回结构里取文字。

    不同接口的字段位置略有差异，这里做兼容：优先取 Data.content（JSON 字符串），
    再退回 Data 里的 words / Content 字段。
    """
    payload = data.get("Data", data)
    content = payload.get("content") or payload.get("Content")
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return content
        payload = parsed

    if isinstance(payload, dict):
        words = payload.get("words") or payload.get("Words")
        if isinstance(words, str):
            return words
        if isinstance(words, list):
            return "\n".join(str(w) for w in words)
        blocks = payload.get("prism_wordsInfo") or payload.get("blocks")
        if isinstance(blocks, list):
            lines = []
            for b in blocks:
                if isinstance(b, dict):
                    lines.append(str(b.get("word") or b.get("text") or ""))
            joined = "\n".join(x for x in lines if x)
            if joined:
                return joined
    return ""


def image_to_text(path: str | Path, *, action: str = DEFAULT_ACTION) -> str:
    """识别单张图片里的文字。未配置密钥时抛 OCRError（消息可直接展示给用户）。"""
    cfg = OCRConfig.from_env()
    if not (cfg.access_key_id and cfg.access_key_secret):
        raise OCRError("未配置 OCR 密钥，无法识别图片文字")

    p = Path(path)
    if not p.exists():
        raise OCRError(f"图片不存在：{p}")
    raw = p.read_bytes()
    if len(raw) > 10 * 1024 * 1024:
        raise OCRError("图片超过 10MB，请压缩后再上传")

    data = _call(cfg, action, {"body": base64.b64encode(raw).decode(), "url": ""})
    text = _extract_text(data)
    if not text.strip():
        raise OCRError("OCR 未识别出文字（可能是纯图形、照片或分辨率过低）")
    return text


def pdf_page_ocr(path: str | Path, page_index: int, *, dpi: int = 200) -> str:
    """把 PDF 的某一页渲染成图片再 OCR。

    page_index 从 1 开始，与系统的页码定位保持一致。
    """
    import pymupdf

    p = Path(path)
    try:
        doc = pymupdf.open(p)
    except Exception as exc:  # noqa: BLE001
        raise OCRError(f"PDF 无法打开：{exc}") from exc
    try:
        if not (1 <= page_index <= doc.page_count):
            raise OCRError(f"页码超出范围：{page_index}（共 {doc.page_count} 页）")
        page = doc[page_index - 1]
        pix = page.get_pixmap(dpi=dpi)
        png = pix.tobytes("png")
    finally:
        doc.close()

    cfg = OCRConfig.from_env()
    if not (cfg.access_key_id and cfg.access_key_secret):
        raise OCRError("未配置 OCR 密钥，无法识别扫描页")

    tmp = p.parent / f".__ocr_p{page_index}.png"
    try:
        tmp.write_bytes(png)
        return image_to_text(tmp)
    finally:
        tmp.unlink(missing_ok=True)


if __name__ == "__main__":  # 自检：python -m app.services.ocr
    print("OCR 状态：", ocr_status())
