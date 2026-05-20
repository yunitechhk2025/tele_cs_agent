from __future__ import annotations

from typing import Any, Iterable

from app.services.i18n import SUPPORTED_LANGUAGE_SET, normalize_language_code, to_traditional_chinese


PRODUCT_TRANSLATABLE_FIELDS = (
    "name",
    "series",
    "space",
    "style",
    "color",
    "material",
    "size",
    "description",
    "detail_content",
)

TRANSLATION_ATTRS = {
    "name": "product_name",
    "series": "series_name",
    "space": "space",
    "style": "style",
    "color": "color",
    "material": "material",
    "size": "size",
    "description": "description_text",
    "detail_content": "detail_content_text",
}

SOURCE_FIELD_ALIASES = {
    "name": ("name", "product_name"),
    "series": ("series", "series_name"),
    "space": ("space",),
    "style": ("style",),
    "color": ("color",),
    "material": ("material",),
    "size": ("size",),
    "description": ("description", "description_text"),
    "detail_content": ("detail_content", "detail_content_text"),
}

OUTPUT_FIELD_ALIASES = {
    "name": ("name", "product_name"),
    "series": ("series", "series_name"),
    "description": ("description", "description_text"),
    "detail_content": ("detail_content", "detail_content_text"),
}


def _read_value(source: Any, field: str) -> str:
    aliases = SOURCE_FIELD_ALIASES.get(field, (field,))
    for key in aliases:
        if isinstance(source, dict):
            value = source.get(key)
        else:
            value = getattr(source, key, None)
        if value:
            return str(value).strip()
    return ""


def _normalize_translation_map(translations: dict[str, Any] | None) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    if not isinstance(translations, dict):
        return out
    for raw_lang, values in translations.items():
        lang = normalize_language_code(str(raw_lang), fallback=None)
        if lang not in SUPPORTED_LANGUAGE_SET or not isinstance(values, dict):
            continue
        bucket = out.setdefault(lang, {})
        for field in PRODUCT_TRANSLATABLE_FIELDS:
            value = values.get(field)
            if value is None:
                attr = TRANSLATION_ATTRS[field]
                value = values.get(attr)
            if value:
                bucket[field] = str(value).strip()
    return out


def translation_map_from_entries(entries: Iterable[Any]) -> dict[str, dict[str, str]]:
    """Serialize SQLAlchemy translation rows into the dict shape used by bot payloads."""
    out: dict[str, dict[str, str]] = {}
    for entry in entries or []:
        lang = normalize_language_code(getattr(entry, "language", None), fallback=None)
        if lang not in SUPPORTED_LANGUAGE_SET:
            continue
        values: dict[str, str] = {}
        for field, attr in TRANSLATION_ATTRS.items():
            value = getattr(entry, attr, None)
            if value:
                values[field] = str(value).strip()
        if values:
            out[lang] = values
    return out


def _translated_value(
    translations: dict[str, dict[str, str]],
    language: str,
    field: str,
) -> str:
    for lang in (language, "en", "zh-Hans"):
        value = (translations.get(lang) or {}).get(field, "")
        if value:
            return value
    return ""


def localize_product_payload(product: dict[str, Any], language: str | None) -> dict[str, Any]:
    """Return a product dict whose customer-facing fields match the requested language."""
    lang = normalize_language_code(language, fallback="en") or "en"
    translations = _normalize_translation_map(product.get("translations"))
    out = dict(product)
    out["translations"] = translations
    out["source_language"] = lang

    for field in PRODUCT_TRANSLATABLE_FIELDS:
        value = _translated_value(translations, lang, field) or _read_value(product, field)
        if value and lang == "zh-Hant" and not _translated_value(translations, lang, field):
            value = to_traditional_chinese(value)
        if not value:
            continue
        out[field] = value
        for alias in OUTPUT_FIELD_ALIASES.get(field, ()):
            out[alias] = value
    return out


def product_entry_to_payload(entry: Any) -> dict[str, Any]:
    """Serialize a ProductEntry-like object into the product dict used by bot flows."""
    images = list(getattr(entry, "images", []) or [])
    payload = {
        "id": getattr(entry, "id", None),
        "brand": getattr(entry, "brand", "") or "",
        "product_id_ext": getattr(entry, "product_id_ext", "") or "",
        "name": getattr(entry, "product_name", "") or "",
        "series": getattr(entry, "series_name", "") or "",
        "space": getattr(entry, "space", "") or "",
        "style": getattr(entry, "style", "") or "",
        "color": getattr(entry, "color", "") or "",
        "material": getattr(entry, "material", "") or "",
        "size": getattr(entry, "size", "") or "",
        "price_display": getattr(entry, "price_display", "") or "",
        "original_price": getattr(entry, "original_price", "") or "",
        "serial_number": getattr(entry, "serial_number", "") or "",
        "description": getattr(entry, "description_text", "") or "",
        "detail_content": getattr(entry, "detail_content_text", "") or "",
        "buy_url": getattr(entry, "buy_url", "") or "",
        "detail_url": getattr(entry, "detail_url", "") or "",
        "image_paths": [getattr(img, "local_path", "") for img in images if getattr(img, "local_path", "")],
        "translations": translation_map_from_entries(getattr(entry, "translations", []) or []),
    }
    payload["search_text"] = product_search_text(payload)
    return payload


def product_search_text(product: dict[str, Any]) -> str:
    """Build multilingual product text for local recall and LLM reranking."""
    parts: list[str] = []

    def add(value: Any):
        text = str(value or "").strip()
        if text and text not in parts:
            parts.append(text)

    for key in (
        "brand",
        "name",
        "product_name",
        "series",
        "series_name",
        "space",
        "style",
        "color",
        "material",
        "size",
        "description",
        "description_text",
        "detail_content",
        "detail_content_text",
    ):
        add(product.get(key))

    for values in _normalize_translation_map(product.get("translations")).values():
        for field in PRODUCT_TRANSLATABLE_FIELDS:
            add(values.get(field))
    return "\n".join(parts)


def _has_complete_translation(product: dict[str, Any], language: str) -> bool:
    translations = _normalize_translation_map(product.get("translations"))
    values = translations.get(language) or {}
    required_fields = [
        field for field in PRODUCT_TRANSLATABLE_FIELDS
        if _read_value(product, field)
    ]
    if not required_fields:
        return True
    return all(str(values.get(field) or "").strip() for field in required_fields)


def build_translation_request_items(
    products: Iterable[dict[str, Any]],
    *,
    target_languages: Iterable[str],
    only_missing: bool = True,
) -> list[dict[str, Any]]:
    """Return the product/language pairs an offline translation job should request."""
    items: list[dict[str, Any]] = []
    normalized_targets = [
        lang for lang in (
            normalize_language_code(language, fallback=None) for language in target_languages
        )
        if lang in SUPPORTED_LANGUAGE_SET
    ]
    for product in products:
        product_id = product.get("id")
        if product_id is None:
            continue
        source_fields = {
            field: _read_value(product, field)
            for field in PRODUCT_TRANSLATABLE_FIELDS
        }
        for language in normalized_targets:
            if only_missing and _has_complete_translation(product, language):
                continue
            items.append({
                "product_id": int(product_id),
                "language": language,
                "brand": str(product.get("brand") or ""),
                "fields": source_fields,
            })
    return items
