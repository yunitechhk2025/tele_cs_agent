import asyncio
import json
import logging
import re
import time
from typing import Any

from app.services.i18n import DEFAULT_LANGUAGE, normalize_language_code
from app.services.product_taxonomy import (
    PROFILE_DIMENSIONS,
    canonicalize_values,
    contains_any,
    normalize_text,
)

logger = logging.getLogger(__name__)

PROFILE_DIMENSION_ALIASES = {
    "category": "categories",
    "categories": "categories",
    "space": "spaces",
    "spaces": "spaces",
    "room": "spaces",
    "rooms": "spaces",
    "style": "styles",
    "styles": "styles",
    "color": "colors",
    "colors": "colors",
    "material": "materials",
    "materials": "materials",
    "brand": "brands",
    "brands": "brands",
}

SCENE_NAME_ALIASES = {
    "living_room": "客厅",
    "living room": "客厅",
    "客厅": "客厅",
    "客廳": "客厅",
    "dining_room": "餐厅",
    "dining room": "餐厅",
    "餐厅": "餐厅",
    "餐廳": "餐厅",
    "bedroom": "卧室",
    "卧室": "卧室",
    "臥室": "卧室",
    "study": "书房",
    "office": "书房",
    "书房": "书房",
    "書房": "书房",
    "entryway": "玄关",
    "foyer": "玄关",
    "玄关": "玄关",
    "玄關": "玄关",
}

ORDINAL_SLOT_WORDS = {
    "一": 1,
    "第一": 1,
    "第一个": 1,
    "第一款": 1,
    "first": 1,
    "1st": 1,
    "primero": 1,
    "primera": 1,
    "premier": 1,
    "一番目": 1,
    "첫번째": 1,
    "二": 2,
    "第二": 2,
    "第二个": 2,
    "第二款": 2,
    "second": 2,
    "2nd": 2,
    "segundo": 2,
    "segunda": 2,
    "deuxieme": 2,
    "二番目": 2,
    "두번째": 2,
    "三": 3,
    "第三": 3,
    "第三个": 3,
    "第三款": 3,
    "third": 3,
    "3rd": 3,
    "tercero": 3,
    "tercera": 3,
    "troisieme": 3,
    "三番目": 3,
    "세번째": 3,
}

GENERIC_TABLE_CATEGORY_TERMS = [
    "桌子",
    "桌",
    "桌类",
    "table",
    "mesa",
    "table",
    "テーブル",
    "机",
    "테이블",
    "탁자",
]

GENERIC_TABLE_CATEGORIES = ["dining_table", "coffee_table", "desk"]


def _coerce_json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}
    text = raw.strip()
    if not text:
        return {}
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        text = match.group(0)
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _clamp_confidence(value: Any, default: float = 0.0) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = default
    return max(0.0, min(1.0, confidence))


def _normalize_language(value: Any, fallback_language: str) -> str:
    return normalize_language_code(str(value or ""), fallback=fallback_language or DEFAULT_LANGUAGE) or DEFAULT_LANGUAGE


def _normalize_hard_constraints(raw: Any) -> list[str]:
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, list):
        values = raw
    else:
        values = []
    out: list[str] = []
    for value in values:
        alias = PROFILE_DIMENSION_ALIASES.get(str(value or "").strip())
        if alias and alias in PROFILE_DIMENSIONS and alias not in out:
            out.append(alias)
    return out


def _profile_from_local_rules(user_message: str) -> dict[str, list[str]]:
    from app.services.llm_service import _extract_product_query_profile

    extracted = _extract_product_query_profile(user_message)
    profile = {
        dimension: sorted(str(value) for value in extracted.get(dimension, set()) if value)
        for dimension in PROFILE_DIMENSIONS
    }
    if not profile.get("categories") and contains_any(normalize_text(user_message), GENERIC_TABLE_CATEGORY_TERMS):
        profile["categories"] = list(GENERIC_TABLE_CATEGORIES)
    return profile


def build_fallback_product_request_profile(user_message: str, fallback_language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
    local = _profile_from_local_rules(user_message)
    hard_constraints = [dimension for dimension, values in local.items() if values]
    return {
        "intent": "product_recommendation",
        "language": _normalize_language(fallback_language, DEFAULT_LANGUAGE),
        **local,
        "hard_constraints": hard_constraints,
        "confidence": 0.72 if hard_constraints else 0.35,
        "needs_human": False,
        "source": "local_rules",
        "reason": "local multilingual rules",
    }


def normalize_product_request_profile(
    raw_profile: Any,
    *,
    user_message: str,
    fallback_language: str = DEFAULT_LANGUAGE,
) -> dict[str, Any]:
    data = _coerce_json_object(raw_profile)
    fallback = build_fallback_product_request_profile(user_message, fallback_language)
    profile: dict[str, Any] = {
        "intent": "product_recommendation",
        "language": _normalize_language(data.get("language"), fallback["language"]),
        "hard_constraints": _normalize_hard_constraints(data.get("hard_constraints")),
        "confidence": _clamp_confidence(data.get("confidence"), 0.0),
        "needs_human": bool(data.get("needs_human", False)),
        "source": str(data.get("source") or "llm"),
        "reason": str(data.get("reason") or ""),
    }
    for dimension in PROFILE_DIMENSIONS:
        normalized = canonicalize_values(dimension, data.get(dimension))
        profile[dimension] = normalized or list(fallback.get(dimension, []))
    if not profile["hard_constraints"]:
        profile["hard_constraints"] = list(fallback.get("hard_constraints", []))
    if profile["confidence"] <= 0 and any(profile.get(d) for d in PROFILE_DIMENSIONS):
        profile["confidence"] = 0.65
    if (
        profile["needs_human"]
        and profile["confidence"] < 0.55
        and any(fallback.get(d) for d in PROFILE_DIMENSIONS)
    ):
        fallback["source"] = "local_rules_after_profile_handoff"
        fallback["reason"] = "low-confidence LLM handoff overridden by local product constraints"
        return fallback
    return profile


def _format_candidate_catalog(products: list[dict[str, Any]], limit: int = 30) -> str:
    lines: list[str] = []
    for idx, product in enumerate(products[:limit], start=1):
        lines.append(
            " | ".join(
                [
                    f"SLOT:{idx}",
                    f"ID:{product.get('id')}",
                    f"name:{product.get('name') or product.get('product_name') or ''}",
                    f"category:{product.get('primary_category') or ''}",
                    f"space:{product.get('normalized_space') or product.get('space') or ''}",
                    f"style:{product.get('normalized_style') or product.get('style') or ''}",
                ]
            )
        )
    return "\n".join(lines)


async def parse_product_request_profile(
    user_message: str,
    *,
    language: str = DEFAULT_LANGUAGE,
    conversation_memory: str = "",
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    from app.services.llm_service import profile_chat_completion, get_llm_settings

    fallback = build_fallback_product_request_profile(user_message, language)
    cfg = await get_llm_settings()
    timeout = float(timeout_seconds or cfg.get("profile_llm_timeout_seconds") or 4)
    prompt = (
        "You normalize furniture product recommendation requests into strict JSON.\n"
        "The customer may speak any language. Do not answer the customer.\n"
        "Use only these canonical enum values:\n"
        "categories: sofa, dining_table, dining_chair, bed, nightstand, coffee_table, tv_cabinet, cabinet, wardrobe, desk, bookshelf, bar, chair, mattress, bedding, dressing_table, coat_rack, magazine_rack\n"
        "spaces: living_room, dining_room, bedroom, study, entryway\n"
        "styles: modern, minimalist, luxury, nordic, chinese, japanese, vintage, french, italian\n"
        "colors: white, black, gray, brown, wood, red, blue, green, purple, pink, yellow, beige\n"
        "materials: leather, fabric, solid_wood, walnut, teak, stone, metal\n"
        "brands: landbond, redapple, zuoyou\n\n"
        "Return ONLY compact JSON with keys: language, categories, spaces, styles, colors, materials, brands, "
        "hard_constraints, confidence, needs_human, reason.\n"
        "hard_constraints must contain dimensions the user explicitly requires. If unclear, confidence must be low.\n"
        "Do NOT set needs_human merely because optional details like style, color, size, or material are missing "
        "when a furniture category or broad product family can be inferred; recommend reasonable catalog matches instead.\n"
        "Only set needs_human=true for requests that are impossible to map to catalog products, unsafe, or require human-only decisions.\n\n"
        f"Conversation memory:\n{conversation_memory or '(none)'}"
    )
    start = time.perf_counter()
    try:
        raw = await asyncio.wait_for(
            profile_chat_completion(
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=400,
                temperature=0,
            ),
            timeout=timeout,
        )
        profile = normalize_product_request_profile(raw, user_message=user_message, fallback_language=language)
        profile["source"] = "profile_llm"
        logger.info(
            "Product profile parsed source=profile_llm confidence=%.2f elapsed_ms=%d profile=%s",
            profile.get("confidence") or 0.0,
            int((time.perf_counter() - start) * 1000),
            {k: profile.get(k) for k in [*PROFILE_DIMENSIONS, "hard_constraints"]},
        )
        if profile["confidence"] < 0.35 and any(fallback.get(d) for d in PROFILE_DIMENSIONS):
            fallback["source"] = "local_rules_after_low_confidence_llm"
            return fallback
        return profile
    except Exception as exc:
        fallback["source"] = "local_rules_after_profile_error"
        fallback["reason"] = f"profile parser fallback: {type(exc).__name__}"
        logger.warning("Product profile parsing failed, using local fallback: %s", exc)
        return fallback


def _infer_slot_from_text(user_message: str) -> int | None:
    normalized = (user_message or "").strip().lower().translate(str.maketrans({
        "１": "1", "２": "2", "３": "3", "４": "4", "５": "5",
        "６": "6", "７": "7", "８": "8", "９": "9", "＃": "#",
    }))
    compact = re.sub(r"\s+", "", normalized)
    direct = re.search(r"(?:#|第|no\.?|number|num|nº)?\s*([1-9])(?:个|款|件|号)?", normalized)
    if direct:
        return int(direct.group(1))
    for word, slot in ORDINAL_SLOT_WORDS.items():
        if word in compact:
            return slot
    return None


def _canonical_scene_name(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    key = raw.lower().replace("-", "_")
    return SCENE_NAME_ALIASES.get(key) or SCENE_NAME_ALIASES.get(raw) or raw


def normalize_scene_request_profile(
    raw_profile: Any,
    *,
    user_message: str,
    fallback_language: str = DEFAULT_LANGUAGE,
) -> dict[str, Any]:
    data = _coerce_json_object(raw_profile)
    slot = data.get("target_product_slot")
    try:
        slot = int(slot) if slot is not None and str(slot).strip() else None
    except (TypeError, ValueError):
        slot = None
    if slot is None:
        slot = _infer_slot_from_text(user_message)
    target_id = data.get("target_product_id")
    try:
        target_id = int(target_id) if target_id is not None and str(target_id).strip() else None
    except (TypeError, ValueError):
        target_id = None
    requirements = data.get("requirements")
    if isinstance(requirements, str):
        requirements = [requirements]
    if not isinstance(requirements, list):
        requirements = []
    return {
        "intent": "scene_image_request",
        "language": _normalize_language(data.get("language"), fallback_language),
        "is_scene_request": bool(data.get("is_scene_request", True)),
        "target_product_slot": slot,
        "target_product_id": target_id,
        "scene_name": _canonical_scene_name(data.get("scene_name")),
        "style_hint": str(data.get("style_hint") or "").strip(),
        "requirements": [str(x).strip() for x in requirements if str(x).strip()][:8],
        "confidence": _clamp_confidence(data.get("confidence"), 0.0),
        "needs_human": bool(data.get("needs_human", False)),
        "source": str(data.get("source") or "llm"),
        "reason": str(data.get("reason") or ""),
    }


async def parse_scene_request_profile(
    user_message: str,
    *,
    language: str = DEFAULT_LANGUAGE,
    recent_products: list[dict[str, Any]] | None = None,
    conversation_memory: str = "",
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    from app.services.llm_service import profile_chat_completion, get_llm_settings

    cfg = await get_llm_settings()
    timeout = float(timeout_seconds or cfg.get("profile_llm_timeout_seconds") or 4)
    catalog = _format_candidate_catalog(recent_products or [], limit=12)
    prompt = (
        "You normalize furniture scene-image requests into strict JSON.\n"
        "The user may refer to a recently recommended product by slot number, ordinal, name, or ID.\n"
        "Return ONLY compact JSON with keys: language, is_scene_request, target_product_slot, target_product_id, "
        "scene_name, style_hint, requirements, confidence, needs_human, reason.\n"
        "scene_name should be one of: living_room, dining_room, bedroom, study, entryway, or a literal user scene if outside these.\n"
        "If the target product cannot be identified, keep target fields null and lower confidence.\n\n"
        f"Conversation memory:\n{conversation_memory or '(none)'}\n\n"
        f"Recent products:\n{catalog or '(none)'}"
    )
    start = time.perf_counter()
    fallback = normalize_scene_request_profile(
        {"is_scene_request": True, "confidence": 0.5, "language": language},
        user_message=user_message,
        fallback_language=language,
    )
    try:
        raw = await asyncio.wait_for(
            profile_chat_completion(
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=400,
                temperature=0,
            ),
            timeout=timeout,
        )
        profile = normalize_scene_request_profile(raw, user_message=user_message, fallback_language=language)
        profile["source"] = "profile_llm"
        logger.info(
            "Scene profile parsed source=profile_llm confidence=%.2f elapsed_ms=%d profile=%s",
            profile.get("confidence") or 0.0,
            int((time.perf_counter() - start) * 1000),
            {k: profile.get(k) for k in ["target_product_slot", "target_product_id", "scene_name", "style_hint"]},
        )
        if profile["confidence"] < 0.35:
            fallback["source"] = "local_rules_after_low_confidence_llm"
            return fallback
        return profile
    except Exception as exc:
        fallback["source"] = "local_rules_after_profile_error"
        fallback["reason"] = f"profile parser fallback: {type(exc).__name__}"
        logger.warning("Scene profile parsing failed, using local fallback: %s", exc)
        return fallback
