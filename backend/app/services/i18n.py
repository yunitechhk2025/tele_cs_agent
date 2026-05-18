from __future__ import annotations

from typing import Iterable


DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = ("zh-Hans", "zh-Hant", "en", "ja", "ko", "es", "fr")
SUPPORTED_LANGUAGE_SET = set(SUPPORTED_LANGUAGES)

_SIMPLIFIED_CHINESE_CODES = {"zh-cn", "zh-sg", "zh-my", "zh-hans"}
_TRADITIONAL_CHINESE_CODES = {"zh-tw", "zh-hk", "zh-mo", "zh-hant"}

_TRADITIONAL_ONLY_CHARS = set(
    "這個問請嗎嗎麼麼櫃櫥門體價錢質實裝運達聯蘋風燈臺檯牆顏色號後開關"
    "買賣推薦產品資料詳細說明適嗎廣廳臥餐衛兒童書辦公陽臺"
)
_SIMPLIFIED_ONLY_CHARS = set(
    "这个问请吗么柜橱门体价钱质实装运达联苹风灯台墙颜色号后开关"
    "买卖推荐产品资料详细说明适吗广厅卧餐卫儿童书办公阳台"
)

_SIMPLIFIED_TO_TRADITIONAL_PHRASES = {
    "链接": "連結",
}

_SIMPLIFIED_TO_TRADITIONAL_CHARS = str.maketrans({
    "为": "為",
    "这": "這",
    "个": "個",
    "问": "問",
    "请": "請",
    "吗": "嗎",
    "么": "麼",
    "柜": "櫃",
    "橱": "櫥",
    "门": "門",
    "体": "體",
    "价": "價",
    "钱": "錢",
    "质": "質",
    "实": "實",
    "装": "裝",
    "运": "運",
    "达": "達",
    "联": "聯",
    "苹": "蘋",
    "风": "風",
    "灯": "燈",
    "台": "臺",
    "墙": "牆",
    "颜": "顏",
    "号": "號",
    "后": "後",
    "开": "開",
    "关": "關",
    "买": "買",
    "卖": "賣",
    "荐": "薦",
    "发": "發",
    "产": "產",
    "资": "資",
    "详": "詳",
    "说": "說",
    "适": "適",
    "广": "廣",
    "厅": "廳",
    "卧": "臥",
    "卫": "衛",
    "儿": "兒",
    "书": "書",
    "办": "辦",
    "阳": "陽",
    "边": "邊",
    "类": "類",
    "现": "現",
    "暂": "暫",
    "没": "沒",
    "统": "統",
    "迟": "遲",
    "间": "間",
    "图": "圖",
    "张": "張",
    "导": "導",
    "处": "處",
    "补": "補",
    "复": "複",
    "单": "單",
    "绍": "紹",
    "与": "與",
    "虑": "慮",
    "议": "議",
    "项": "項",
    "务": "務",
    "转": "轉",
    "优": "優",
    "级": "級",
    "络": "絡",
    "线": "線",
    "户": "戶",
})


def detect_chinese_script(text: str | None) -> str | None:
    """Return the likely Chinese script for text containing Chinese characters."""
    value = text or ""
    if not value:
        return None
    traditional_hits = sum(1 for ch in value if ch in _TRADITIONAL_ONLY_CHARS)
    simplified_hits = sum(1 for ch in value if ch in _SIMPLIFIED_ONLY_CHARS)
    if traditional_hits > simplified_hits:
        return "zh-Hant"
    if traditional_hits or simplified_hits:
        return "zh-Hans"
    return None


def to_traditional_chinese(text: str | None) -> str:
    value = text or ""
    for source, target in _SIMPLIFIED_TO_TRADITIONAL_PHRASES.items():
        value = value.replace(source, target)
    return value.translate(_SIMPLIFIED_TO_TRADITIONAL_CHARS)


def _clean_language_code(language: str | None) -> str:
    return (language or "").strip().replace("_", "-").lower()


def normalize_language_code(
    language: str | None,
    *,
    text: str | None = None,
    fallback: str | None = DEFAULT_LANGUAGE,
) -> str | None:
    """Normalize user/provider language codes to the app-supported language keys."""
    code = _clean_language_code(language)
    if not code:
        return fallback

    if code in _SIMPLIFIED_CHINESE_CODES:
        return "zh-Hans"
    if code in _TRADITIONAL_CHINESE_CODES:
        return "zh-Hant"
    if code == "zh" or code.startswith("zh-"):
        return detect_chinese_script(text) or "zh-Hans"

    base = code.split("-", 1)[0]
    if base in {"en", "ja", "ko", "es", "fr"}:
        return base
    return fallback


def first_supported_language(candidates: Iterable[str | None]) -> str:
    for candidate in candidates:
        normalized = normalize_language_code(candidate, fallback=None)
        if normalized in SUPPORTED_LANGUAGE_SET:
            return normalized
    return DEFAULT_LANGUAGE


def resolve_reply_language(
    detected_language: str | None,
    *,
    previous_language: str | None = None,
    text: str | None = None,
) -> str:
    """Prefer the latest supported language, otherwise keep the previous supported language."""
    detected = normalize_language_code(detected_language, text=text, fallback=None)
    if detected in SUPPORTED_LANGUAGE_SET:
        return detected
    previous = normalize_language_code(previous_language, fallback=None)
    if previous in SUPPORTED_LANGUAGE_SET:
        return previous
    return DEFAULT_LANGUAGE


def get_localized_static_text(mapping: dict[str, str], language: str | None) -> str:
    lang = normalize_language_code(language, fallback=DEFAULT_LANGUAGE) or DEFAULT_LANGUAGE
    if lang in mapping:
        return mapping[lang]
    if lang == "zh-Hans" and "zh" in mapping:
        return mapping["zh"]
    if lang == "zh-Hant":
        if "zh-Hant" in mapping:
            return mapping["zh-Hant"]
        if "zh" in mapping:
            return to_traditional_chinese(mapping["zh"])
    return mapping.get(lang) or mapping.get(DEFAULT_LANGUAGE) or next(iter(mapping.values()), "")


def get_localized_static_dict(mapping: dict[str, dict[str, str]], language: str | None) -> dict[str, str]:
    lang = normalize_language_code(language, fallback=DEFAULT_LANGUAGE) or DEFAULT_LANGUAGE
    if lang in mapping:
        return mapping[lang]
    if lang == "zh-Hans" and "zh" in mapping:
        return mapping["zh"]
    if lang == "zh-Hant":
        if "zh-Hant" in mapping:
            return mapping["zh-Hant"]
        if "zh" in mapping:
            return {key: to_traditional_chinese(value) for key, value in mapping["zh"].items()}
    return mapping.get(lang) or mapping.get(DEFAULT_LANGUAGE) or next(iter(mapping.values()), {})
