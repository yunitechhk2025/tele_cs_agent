"""调用当前推荐链路生成 golden case 的结构化评测结果。

该脚本显式要求 --allow-live-llm，避免开发者误把模型调用、费用和外部网络依赖带进
普通单元测试。它只写入 case_id、结构化意图/profile 和稳定商品键，不写入客户会话数据。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_CASES_PATH = PROJECT_ROOT / "evaluations" / "recommendation_golden_cases.json"
HANDOFF_INTENTS = {"quote_handoff", "human_handoff", "complaint"}


def _product_key(product: dict[str, Any]) -> str:
    """生成评测用稳定商品键，防止跨品牌 product_id_ext 重号。"""
    brand = str(product.get("brand") or "").strip()
    external_id = str(product.get("product_id_ext") or "").strip()
    return f"{brand}:{external_id}" if brand and external_id else ""


def _as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    return [str(item).strip() for item in values if str(item or "").strip()]


async def _load_catalog() -> tuple[list[dict[str, Any]], dict[str, int], dict[int, dict[str, Any]]]:
    """读取与 Telegram 推荐链路一致的商品 payload，并建立稳定键映射。"""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.database import AsyncSessionLocal
    from app.models import ProductEntry
    from app.services.product_i18n import product_entry_to_payload

    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(ProductEntry)
            .options(selectinload(ProductEntry.images), selectinload(ProductEntry.translations))
            .order_by(ProductEntry.id)
        )
        products = [product_entry_to_payload(entry) for entry in rows.scalars().all()]
    id_by_key = {_product_key(product): int(product["id"]) for product in products if _product_key(product)}
    products_by_id = {int(product["id"]): product for product in products if product.get("id") is not None}
    return products, id_by_key, products_by_id


def _build_context_turns(case: dict[str, Any], id_by_key: dict[str, int]) -> list[dict[str, Any]]:
    """把 golden case 的商品键上下文转换为现有推荐记忆服务使用的内部 ID。"""
    context = _as_mapping(case.get("context"))
    raw_turns = context.get("recommendation_turns")
    turns: list[dict[str, Any]] = []
    for index, raw_turn in enumerate(raw_turns if isinstance(raw_turns, list) else [], start=1):
        turn = _as_mapping(raw_turn)
        product_ids = [id_by_key[key] for key in _string_list(turn.get("product_keys")) if key in id_by_key]
        turns.append(
            {
                "turn_index": index,
                "product_ids": product_ids,
                "category_profile": _as_mapping(turn.get("profile")),
            }
        )
    return turns


def _response_kind_for_intent(intent_name: str, selected_ids: list[int]) -> str:
    if intent_name in HANDOFF_INTENTS:
        return "handoff"
    if intent_name == "product_recommendation":
        return "product_recommendation" if selected_ids else "product_not_found"
    return intent_name


async def _run_case(
    case: dict[str, Any],
    products: list[dict[str, Any]],
    id_by_key: dict[str, int],
    products_by_id: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """回放单个案例的意图、需求解析、换批和商品选择核心链路。"""
    from app.services.llm_service import (
        ai_select_products,
        classify_customer_intent,
        detect_language,
        is_recommendation_refresh_text,
    )
    from app.services.profile_parser_service import parse_product_request_profile
    from app.telegram_bot import (
        build_recommendation_refresh_profile,
        collect_recommendation_refresh_excluded_ids,
        resolve_product_reference_from_history,
        should_use_recommendation_refresh,
    )

    input_data = _as_mapping(case.get("input"))
    message = str(input_data.get("message") or "")
    recommendation_turns = _build_context_turns(case, id_by_key)
    recent_product_ids = [product_id for turn in recommendation_turns for product_id in turn["product_ids"]]
    detected_language = await detect_language(message)
    intent = await classify_customer_intent(
        message,
        products=products,
        recent_product_ids=recent_product_ids,
        chat_history=[],
    )
    intent_name = str(intent.get("primary_intent") or "general_question")
    slots = _as_mapping(intent.get("slots"))
    confidence = float(intent.get("confidence") or 0.0)
    is_product_recommendation = (
        intent_name == "product_recommendation"
        or "product_recommendation" in _string_list(intent.get("secondary_intents"))
    ) and confidence >= 0.55
    result: dict[str, Any] = {
        "case_id": case["case_id"],
        "intent": intent_name,
        "language": detected_language,
        "intent_slots": slots,
        "profile": {},
        "selected_product_keys": [],
        "response_kind": _response_kind_for_intent(intent_name, []),
        "error": "",
    }

    if not is_product_recommendation:
        history_reference = resolve_product_reference_from_history(
            message,
            recommendation_turns,
            products_by_id,
        )
        target_id = history_reference.get("target_product_id")
        if isinstance(target_id, int) and target_id in products_by_id:
            result["target_product_key"] = _product_key(products_by_id[target_id])
        return result

    profile = await parse_product_request_profile(
        message,
        language=detected_language,
        conversation_memory="",
    )
    refresh_requested = is_recommendation_refresh_text(message) or bool(
        slots.get("is_recommendation_refresh")
    )
    is_refresh = should_use_recommendation_refresh(message, slots, recommendation_turns)
    result["intent_slots"] = {**slots, "is_recommendation_refresh": is_refresh}
    if refresh_requested and not is_refresh:
        result["profile"] = profile
        result["response_kind"] = "clarification"
        return result

    excluded_product_ids: list[int] = []
    require_full_match = False
    if is_refresh:
        profile = build_recommendation_refresh_profile(profile, recommendation_turns)
        excluded_product_ids = collect_recommendation_refresh_excluded_ids(recommendation_turns)
        require_full_match = any(
            _string_list(profile.get(dimension))
            for dimension in ("categories", "spaces", "styles", "colors", "materials", "brands")
        )
    selected_ids = await ai_select_products(
        message,
        products,
        request_profile=profile,
        exclude_product_ids=excluded_product_ids,
        require_full_match=require_full_match,
    )
    result["profile"] = profile
    result["selected_product_keys"] = [
        _product_key(products_by_id[product_id])
        for product_id in selected_ids
        if product_id in products_by_id and _product_key(products_by_id[product_id])
    ]
    result["response_kind"] = _response_kind_for_intent(intent_name, selected_ids)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run live recommendation golden cases")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--allow-live-llm", action="store_true")
    return parser


async def run() -> int:
    args = build_parser().parse_args()
    if not args.allow_live_llm:
        raise SystemExit("Refusing live model calls without --allow-live-llm")
    from app.services.recommendation_evaluation_service import (
        load_recommendation_evaluation_cases,
    )

    cases = load_recommendation_evaluation_cases(args.cases)
    selected_case_ids = set(args.case_id)
    if selected_case_ids:
        cases = [case for case in cases if case["case_id"] in selected_case_ids]
    if not cases:
        raise SystemExit("No golden cases selected")

    products, id_by_key, products_by_id = await _load_catalog()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for case in cases:
        try:
            result = await _run_case(case, products, id_by_key, products_by_id)
        except Exception as exc:
            result = {
                "case_id": case["case_id"],
                "intent": "",
                "language": "",
                "profile": {},
                "selected_product_keys": [],
                "response_kind": "error",
                "error": f"{type(exc).__name__}: {exc}",
            }
        results.append(result)

    args.output.write_text(
        "".join(json.dumps(result, ensure_ascii=False) + "\n" for result in results),
        encoding="utf-8",
    )
    print(f"Wrote {len(results)} evaluation results to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
