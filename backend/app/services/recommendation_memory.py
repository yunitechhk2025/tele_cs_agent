from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import func, select

from app.database import AsyncSessionLocal
from app.models import (
    ConversationOutboundEvent,
    ConversationRecommendationTurn,
    Message,
    MessageRole,
)
from app.services.llm_service import (
    PRODUCT_CATEGORY_TERMS,
    _contains_any,
    _extract_product_query_profile,
    _normalize_match_text,
)
from app.services.product_reference_parser import parse_product_reference


def _safe_json_list(raw: str | None) -> list[Any]:
    try:
        data = json.loads(raw or "[]")
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _safe_json_dict(raw: str | None) -> dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _profile_to_jsonable(profile: dict[str, set[str]]) -> dict[str, list[str]]:
    return {
        key: sorted(str(item) for item in values if str(item).strip())
        for key, values in profile.items()
        if values
    }


def extract_recommendation_profile(text: str) -> dict[str, list[str]]:
    return _profile_to_jsonable(_extract_product_query_profile(text or ""))


def _normalize_message(text: str) -> str:
    return _normalize_match_text(
        str(text or "").translate(
            str.maketrans(
                {
                    "１": "1",
                    "２": "2",
                    "３": "3",
                    "４": "4",
                    "５": "5",
                    "６": "6",
                    "７": "7",
                    "８": "8",
                    "９": "9",
                    "＃": "#",
                    "﹟": "#",
                }
            )
        )
    )


def _turn_categories(turn: dict[str, Any]) -> set[str]:
    profile = turn.get("category_profile") or {}
    categories = profile.get("categories") if isinstance(profile, dict) else []
    return {str(item) for item in categories or [] if str(item).strip()}


def _item_text(item: dict[str, Any], product: dict[str, Any] | None = None) -> str:
    values: list[str] = []
    for source in (item, product or {}):
        if not isinstance(source, dict):
            continue
        for key in (
            "name",
            "product_name",
            "brand",
            "series",
            "series_name",
            "space",
            "style",
            "material",
        ):
            value = source.get(key)
            if value:
                values.append(str(value))
        translations = source.get("translations") or {}
        if isinstance(translations, dict):
            for translation in translations.values():
                if isinstance(translation, dict):
                    values.extend(str(v) for v in translation.values() if v)
    return _normalize_message(" ".join(values))


def _turn_matches_categories(
    turn: dict[str, Any],
    requested_categories: set[str],
    products_by_id: dict[int, dict[str, Any]] | None,
) -> bool:
    if _turn_categories(turn) & requested_categories:
        return True
    products_by_id = products_by_id or {}
    for item in turn.get("items") or []:
        if not isinstance(item, dict):
            continue
        product_id = item.get("product_id")
        try:
            product = products_by_id.get(int(product_id))
        except (TypeError, ValueError):
            product = None
        text = _item_text(item, product)
        if any(
            _contains_any(text, PRODUCT_CATEGORY_TERMS.get(category, []))
            for category in requested_categories
        ):
            return True
    return False


def _candidate_turns_for_categories(
    turns: list[dict[str, Any]],
    requested_categories: set[str],
    products_by_id: dict[int, dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    profile_matches = [turn for turn in turns if _turn_categories(turn) & requested_categories]
    if profile_matches:
        return profile_matches
    return [
        turn
        for turn in turns
        if _turn_matches_categories(turn, requested_categories, products_by_id)
    ]


def _turn_sort_key(turn: dict[str, Any]) -> tuple[int, int]:
    try:
        turn_index = int(turn.get("turn_index") or 0)
    except (TypeError, ValueError):
        turn_index = 0
    try:
        turn_id = int(turn.get("id") or 0)
    except (TypeError, ValueError):
        turn_id = 0
    return (turn_index, turn_id)


def _pick_turn_slot(turn: dict[str, Any], slot: int) -> dict[str, Any] | None:
    if slot < 1:
        return None
    items = [item for item in (turn.get("items") or []) if isinstance(item, dict)]
    for item in items:
        try:
            if int(item.get("slot") or 0) == slot:
                return item
        except (TypeError, ValueError):
            continue
    product_ids = turn.get("product_ids") or []
    if slot <= len(product_ids):
        return {"slot": slot, "product_id": product_ids[slot - 1]}
    return None


def _turn_item_count(turn: dict[str, Any]) -> int:
    product_ids = [item for item in (turn.get("product_ids") or []) if str(item).isdigit()]
    items = [item for item in (turn.get("items") or []) if isinstance(item, dict)]
    return max(len(product_ids), len(items))


def _match_product_name(
    user_message: str,
    turns: list[dict[str, Any]],
    products_by_id: dict[int, dict[str, Any]] | None,
) -> dict[str, Any]:
    normalized = _normalize_message(user_message)
    if len(normalized) < 2:
        return {}
    products_by_id = products_by_id or {}
    for turn in sorted(turns, key=_turn_sort_key, reverse=True):
        for item in turn.get("items") or []:
            if not isinstance(item, dict):
                continue
            try:
                product_id = int(item.get("product_id"))
            except (TypeError, ValueError):
                continue
            product = products_by_id.get(product_id)
            aliases = [
                _normalize_message(str(item.get(key) or ""))
                for key in ("name", "product_name", "series")
            ]
            if product:
                aliases.extend(
                    _normalize_message(str(product.get(key) or ""))
                    for key in ("name", "product_name", "series", "series_name")
                )
            aliases = [alias for alias in aliases if len(alias) >= 4]
            if any(alias and alias in normalized for alias in aliases):
                return {
                    "target_product_id": product_id,
                    "turn_id": turn.get("id"),
                    "turn_index": turn.get("turn_index"),
                    "slot": item.get("slot"),
                    "needs_clarification": False,
                    "reason": "matched_product_name_in_recommendation_history",
                }
    return {}


def resolve_product_reference_from_history(
    user_message: str,
    turns: list[dict[str, Any]],
    products_by_id: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve references like "second bed" against recommendation turns."""
    empty = {
        "target_product_id": None,
        "turn_id": None,
        "turn_index": None,
        "turn_product_ids": [],
        "slot": None,
        "needs_clarification": False,
        "reason": "",
    }
    valid_turns = [turn for turn in turns or [] if isinstance(turn, dict)]
    if not valid_turns:
        return empty

    name_match = _match_product_name(user_message, valid_turns, products_by_id)
    if name_match:
        return {**empty, **name_match}

    reference = parse_product_reference(user_message)
    profile = extract_recommendation_profile(user_message)
    requested_categories = set(profile.get("categories") or [])
    if not (reference.slot or reference.relative_kind):
        return empty

    if requested_categories:
        candidate_turns = _candidate_turns_for_categories(
            valid_turns, requested_categories, products_by_id
        )
        if not candidate_turns:
            return {
                **empty,
                "slot": reference.slot,
                "needs_clarification": True,
                "reason": "no_recommendation_turn_matches_requested_category",
            }
    else:
        candidate_turns = valid_turns

    selected_turn = sorted(candidate_turns, key=_turn_sort_key, reverse=True)[0]
    resolved_reference = parse_product_reference(
        user_message,
        item_count=_turn_item_count(selected_turn),
    )
    slot = resolved_reference.slot or reference.slot
    if slot is None:
        return {
            **empty,
            "turn_id": selected_turn.get("id"),
            "turn_index": selected_turn.get("turn_index"),
            "turn_product_ids": selected_turn.get("product_ids") or [],
            "needs_clarification": True,
            "reason": "ambiguous_relative_product_reference",
        }
    item = _pick_turn_slot(selected_turn, slot)
    if not item:
        return {
            **empty,
            "turn_id": selected_turn.get("id"),
            "turn_index": selected_turn.get("turn_index"),
            "turn_product_ids": selected_turn.get("product_ids") or [],
            "slot": slot,
            "needs_clarification": True,
            "reason": "slot_out_of_range_for_recommendation_turn",
        }
    try:
        product_id = int(item.get("product_id"))
    except (TypeError, ValueError):
        product_id = None
    return {
        "target_product_id": product_id,
        "turn_id": selected_turn.get("id"),
        "turn_index": selected_turn.get("turn_index"),
        "turn_product_ids": selected_turn.get("product_ids") or [],
        "slot": slot,
        "needs_clarification": product_id is None,
        "reason": "matched_recommendation_turn_slot",
    }


def _turn_to_dict(turn: ConversationRecommendationTurn) -> dict[str, Any]:
    return {
        "id": turn.id,
        "turn_index": turn.turn_index,
        "request_text": turn.request_text or "",
        "language": turn.language or "en",
        "category_profile": _safe_json_dict(turn.category_profile_json),
        "product_ids": [int(x) for x in _safe_json_list(turn.product_ids_json) if str(x).isdigit()],
        "items": _safe_json_list(turn.items_json),
        "created_at": turn.created_at.isoformat() if turn.created_at else "",
    }


def _caption_slot(caption: str | None) -> int | None:
    match = re.match(r"\s*\[#([1-9])\]", caption or "")
    return int(match.group(1)) if match else None


def _caption_product_name(caption: str | None) -> str:
    first_line = (caption or "").splitlines()[0] if caption else ""
    return re.sub(r"^\s*\[#\d+\]\s*", "", first_line).replace("*", "").strip()


def _event_product_id(url: str | None) -> int | None:
    match = re.search(r"/api/products/(\d+)/images/", url or "")
    if not match:
        return None
    return int(match.group(1))


async def _legacy_turns_from_outbound_events(
    conversation_id: int, limit: int
) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ConversationOutboundEvent)
            .where(
                ConversationOutboundEvent.conversation_id == conversation_id,
                ConversationOutboundEvent.event_type == "photo",
            )
            .order_by(ConversationOutboundEvent.created_at, ConversationOutboundEvent.id)
        )
        events = result.scalars().all()
        groups: list[list[ConversationOutboundEvent]] = []
        current: list[ConversationOutboundEvent] = []
        last_slot = 0
        for event in events:
            slot = _caption_slot(event.caption)
            product_id = _event_product_id(event.url)
            if not slot or not product_id:
                continue
            if current and (slot == 1 or slot <= last_slot):
                groups.append(current)
                current = []
            current.append(event)
            last_slot = slot
        if current:
            groups.append(current)

        turns: list[dict[str, Any]] = []
        for index, group in enumerate(groups[-limit:], start=1):
            first_event = group[0]
            request_result = await db.execute(
                select(Message)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.role == MessageRole.USER,
                    Message.created_at <= first_event.created_at,
                )
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(1)
            )
            request = request_result.scalar_one_or_none()
            request_text = request.content if request else ""
            items: list[dict[str, Any]] = []
            product_ids: list[int] = []
            for event in group:
                slot = _caption_slot(event.caption)
                product_id = _event_product_id(event.url)
                if not slot or not product_id:
                    continue
                product_ids.append(product_id)
                items.append(
                    {
                        "slot": slot,
                        "product_id": product_id,
                        "name": _caption_product_name(event.caption),
                    }
                )
            if product_ids:
                turns.append(
                    {
                        "id": None,
                        "turn_index": index,
                        "request_text": request_text,
                        "language": request.language if request else "en",
                        "category_profile": extract_recommendation_profile(request_text),
                        "product_ids": product_ids,
                        "items": items,
                        "created_at": (
                            first_event.created_at.isoformat() if first_event.created_at else ""
                        ),
                    }
                )
        return turns


async def get_recent_recommendation_turns(
    conversation_id: int, limit: int = 8
) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ConversationRecommendationTurn)
            .where(ConversationRecommendationTurn.conversation_id == conversation_id)
            .order_by(
                ConversationRecommendationTurn.turn_index.desc(),
                ConversationRecommendationTurn.id.desc(),
            )
            .limit(limit)
        )
        turns = [_turn_to_dict(turn) for turn in result.scalars().all()]
    if turns:
        return list(reversed(turns))
    return await _legacy_turns_from_outbound_events(conversation_id, limit)


async def record_recommendation_turn(
    *,
    conversation_id: int,
    request_text: str,
    product_ids: list[int],
    language: str,
    products: list[dict[str, Any]] | None = None,
    category_profile: dict[str, Any] | None = None,
) -> None:
    clean_ids = [int(product_id) for product_id in product_ids if str(product_id).isdigit()]
    if not clean_ids:
        return
    products_by_id = {
        int(product["id"]): product
        for product in (products or [])
        if isinstance(product, dict) and product.get("id") is not None
    }
    items = []
    for slot, product_id in enumerate(clean_ids, start=1):
        product = products_by_id.get(product_id, {})
        items.append(
            {
                "slot": slot,
                "product_id": product_id,
                "name": product.get("name") or product.get("product_name") or "",
                "brand": product.get("brand") or "",
                "series": product.get("series") or product.get("series_name") or "",
                "space": product.get("space") or "",
                "style": product.get("style") or "",
                "material": product.get("material") or "",
            }
        )

    async with AsyncSessionLocal() as db:
        last_index = await db.scalar(
            select(func.max(ConversationRecommendationTurn.turn_index)).where(
                ConversationRecommendationTurn.conversation_id == conversation_id
            )
        )
        latest = await db.scalar(
            select(ConversationRecommendationTurn)
            .where(ConversationRecommendationTurn.conversation_id == conversation_id)
            .order_by(
                ConversationRecommendationTurn.turn_index.desc(),
                ConversationRecommendationTurn.id.desc(),
            )
            .limit(1)
        )
        product_ids_json = json.dumps(clean_ids, ensure_ascii=False)
        if (
            latest
            and latest.request_text == (request_text or "")
            and latest.product_ids_json == product_ids_json
        ):
            return
        db.add(
            ConversationRecommendationTurn(
                conversation_id=conversation_id,
                turn_index=int(last_index or 0) + 1,
                request_text=request_text or "",
                language=language or "en",
                category_profile_json=json.dumps(
                    category_profile or extract_recommendation_profile(request_text),
                    ensure_ascii=False,
                ),
                product_ids_json=product_ids_json,
                items_json=json.dumps(items, ensure_ascii=False),
            )
        )
        await db.commit()
