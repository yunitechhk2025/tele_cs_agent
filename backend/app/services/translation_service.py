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
import re
from typing import Optional

import httpx

from app.services.llm_service import translate_text as _llm_translate

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
        # de=邮箱用于提升匿名额度，留空也可工作。
        "de": "",
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
    if _looks_like(text, target_lang):
        return text  # already in target language

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
