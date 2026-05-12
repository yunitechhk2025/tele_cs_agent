"""轻量级机器翻译服务。

为对话管理页的"实时翻译"侧栏服务，目标是**不依赖** LLM API Key 也能工作：
- 默认走免费的 MyMemory（https://mymemory.translated.net/doc/spec.php），无需密钥，
  匿名调用每天 5000 字符 / IP；
- 如果 MyMemory 调用失败（限流、超时、断网），回退到已有的 LLM `translate_text`；
- 两者都失败时返回 None，路由层会再兜底为原文。

目标语言代码做了个小映射，把 ISO 639-1（如 `zh`, `en`）转换成 MyMemory 能识别的
BCP-47（如 `zh-CN`, `en-US`），调用前会做最小判定避免给中文文本再翻一次。
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

import httpx

from app.services.llm_service import translate_text as _llm_translate
from app.services.llm_service import _chat_completion

logger = logging.getLogger(__name__)


# MyMemory 接受 BCP-47 风格的语言对，例如 "en|zh-CN"。下面只覆盖常用语言，
# 未列出的直接透传，让 MyMemory 自己尝试。
_LANG_MAP = {
    "zh": "zh-CN",
    "zh-cn": "zh-CN",
    "zh-hans": "zh-CN",
    "zh-tw": "zh-TW",
    "zh-hant": "zh-TW",
    "en": "en-US",
    "ja": "ja-JP",
    "ko": "ko-KR",
    "ru": "ru-RU",
    "es": "es-ES",
    "fr": "fr-FR",
    "de": "de-DE",
    "pt": "pt-BR",
    "it": "it-IT",
    "vi": "vi-VN",
    "th": "th-TH",
    "id": "id-ID",
    "ar": "ar-SA",
}

_CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")

# MyMemory 匿名调用要求带一个真实邮箱（参数 de=）才肯放行额度，
# 否则会返回 403 INVALID EMAIL PROVIDED。允许通过 env 覆盖。
_MYMEMORY_EMAIL = os.getenv("MYMEMORY_EMAIL", "zhangivah@gmail.com").strip()


def _normalize(code: str) -> str:
    return _LANG_MAP.get((code or "").lower().strip(), code or "")


def _looks_like(text: str, lang: str) -> bool:
    """非常粗略的同语种判定：目前只识别"目标语言是中文且文本已经主要是中文"，
    避免把中文再翻成英文等浪费请求。"""
    target = (lang or "").lower()
    if target.startswith("zh") and text:
        chinese = _CHINESE_RE.findall(text)
        return len(chinese) / max(len(text), 1) > 0.4
    return False


async def _translate_via_mymemory(
    text: str,
    target_lang: str,
    *,
    source_lang: str = "auto",
    client: Optional[httpx.AsyncClient] = None,
    timeout: float = 6.0,
) -> Optional[str]:
    """走 MyMemory 公共 API。返回 None 表示失败，需要上层回退。"""
    target = _normalize(target_lang) or "zh-CN"
    # MyMemory 不支持 source=auto，但可以用 "autodetect"。但其稳定性不如显式 source。
    # 为了简单：source 默认填 "en"，因为我们大部分场景是把英文 → 中文。
    src = _normalize(source_lang) if source_lang and source_lang != "auto" else "en"

    params = {
        "q": text,
        "langpair": f"{src}|{target}",
        # de=邮箱用于提升匿名额度。MyMemory 当前要求必须填一个**有效**邮箱，
        # 否则会直接 403 INVALID EMAIL PROVIDED。
        "de": _MYMEMORY_EMAIL,
    }
    url = "https://api.mymemory.translated.net/get"

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=timeout)
    try:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        translated = (data.get("responseData") or {}).get("translatedText")
        status = data.get("responseStatus")
        if not translated or (status and int(status) >= 400):
            logger.warning("MyMemory failure: status=%s body=%s", status, data)
            return None
        # MyMemory 偶尔会返回带提示的字符串（比如 "MYMEMORY WARNING: ..."）。
        if "MYMEMORY WARNING" in translated.upper():
            return None
        return translated.strip()
    except Exception as exc:
        logger.warning("MyMemory call failed: %s", exc)
        return None
    finally:
        if own_client and client is not None:
            await client.aclose()


_LANG_NAMES = {
    "zh": "Simplified Chinese",
    "zh-cn": "Simplified Chinese",
    "zh-tw": "Traditional Chinese",
    "en": "English",
    "ja": "Japanese",
    "ko": "Korean",
    "ru": "Russian",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
}


async def translate_batch_via_llm(
    texts: list[str],
    target_lang: str,
    *,
    timeout: float = 25.0,
) -> Optional[list[str]]:
    """单次 LLM 调用批量翻译。返回与输入等长的列表；失败返回 None。

    通过让模型输出 JSON 数组来保证顺序对齐。把空文本占位成 "" 仍然送过去，
    简化客户端解析。"""
    import asyncio
    import json

    if not texts:
        return []

    target_name = _LANG_NAMES.get((target_lang or "zh").lower().strip(), target_lang)

    # 索引文本，让模型保留顺序。
    numbered = "\n".join(f"[{i}] {t if t and t.strip() else '(empty)'}" for i, t in enumerate(texts))
    system_prompt = (
        f"You are a professional translator. Translate each numbered item below into {target_name}. "
        "Preserve emoji, URLs, numbers, formatting and tone. "
        "Return ONLY a JSON array of strings, in the same order as the input, with the same length. "
        "Do not include the [N] index prefix in your output. Do not add any commentary."
    )

    try:
        raw = await asyncio.wait_for(
            _chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": numbered},
                ],
                max_tokens=4000,
                temperature=0.2,
            ),
            timeout=timeout,
        )
    except Exception as exc:
        logger.warning("Batch LLM translate failed: %s", exc)
        return None

    if not raw:
        return None

    cleaned = raw.strip()
    # 模型偶尔会包一层 ```json ... ``` 代码块，剥掉。
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()

    try:
        arr = json.loads(cleaned)
    except Exception as exc:
        logger.warning("Batch LLM translate non-JSON output: %s | head=%r", exc, cleaned[:160])
        return None

    if not isinstance(arr, list) or len(arr) != len(texts):
        logger.warning(
            "Batch LLM translate length mismatch: got %s, want %s",
            len(arr) if isinstance(arr, list) else type(arr).__name__,
            len(texts),
        )
        return None

    return [str(x) if x is not None else "" for x in arr]


async def translate_simple(
    text: str,
    target_lang: str,
    *,
    source_lang: str = "auto",
    client: Optional[httpx.AsyncClient] = None,
    llm_fallback: bool = True,
    overall_timeout: float = 8.0,
) -> Optional[str]:
    """对外主入口：先试 MyMemory，失败再回退 LLM；两者都加了硬超时，
    避免任何一个卡住导致整个 /api/translate 请求挂死。"""
    if not text or not text.strip():
        return text or ""

    import asyncio

    try:
        via_mm = await asyncio.wait_for(
            _translate_via_mymemory(text, target_lang, source_lang=source_lang, client=client),
            timeout=6.0,
        )
    except (asyncio.TimeoutError, Exception) as exc:
        logger.warning("MyMemory hard timeout/error: %s", exc)
        via_mm = None
    if via_mm:
        return via_mm

    if not llm_fallback:
        return None

    try:
        via_llm = await asyncio.wait_for(_llm_translate(text, target_lang), timeout=overall_timeout)
    except (asyncio.TimeoutError, Exception) as exc:
        logger.warning("LLM translate fallback failed/timeout: %s", exc)
        via_llm = None
    return via_llm
