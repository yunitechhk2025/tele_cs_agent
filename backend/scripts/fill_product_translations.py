"""
Offline-fill product translations from the configured LLM provider.

Run from the backend container:
    python scripts/fill_product_translations.py --only-missing --batch-size 8

This script is intentionally offline-only. It is never imported or called from the
Telegram customer message path.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.i18n import SUPPORTED_LANGUAGES, normalize_language_code, to_traditional_chinese
from app.services.product_i18n import (
    PRODUCT_TRANSLATABLE_FIELDS,
    TRANSLATION_ATTRS,
    build_translation_request_items,
    product_entry_to_payload,
)


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


LANGUAGE_LABELS = {
    "zh-Hans": "Simplified Chinese",
    "zh-Hant": "Traditional Chinese",
    "en": "English",
    "ja": "Japanese",
    "ko": "Korean",
    "es": "Spanish",
    "fr": "French",
}


def format_progress_bar(completed: int, total: int, *, width: int = 30) -> str:
    total = max(0, int(total))
    if total == 0:
        completed = 0
        ratio = 1.0
    else:
        completed = max(0, min(int(completed), total))
        ratio = completed / total
    filled = width if total == 0 else int(width * ratio)
    filled = max(0, min(filled, width))
    return f"[{'#' * filled}{'-' * (width - filled)}] {completed}/{total} {ratio * 100:.1f}%"


def _emit_progress(
    completed: int,
    total: int,
    *,
    batch_index: int,
    total_batches: int,
    upserted_total: int,
) -> None:
    line = (
        f"Translation progress {format_progress_bar(completed, total)} "
        f"batches {batch_index}/{total_batches} upserted={upserted_total}"
    )
    if sys.stderr.isatty():
        sys.stderr.write("\r" + line)
        if total == 0 or completed >= total:
            sys.stderr.write("\n")
        sys.stderr.flush()
    else:
        logger.info(line)


def build_translation_messages(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    payload = {
        "items": [
            {
                "product_id": item["product_id"],
                "language": item["language"],
                "target_language": LANGUAGE_LABELS.get(item["language"], item["language"]),
                "brand": item.get("brand", ""),
                "fields": item.get("fields") or {},
            }
            for item in items
        ]
    }
    system = (
        "You are translating furniture catalog fields for customer-facing product cards. "
        "Return strict JSON only, with no Markdown and no commentary. "
        "Preserve brand names, model numbers, URLs, measurements, and product IDs. "
        "Translate field values naturally for the target language while keeping furniture terminology precise. "
        "Return this shape: {\"translations\":[{\"product_id\":10,\"language\":\"en\",\"fields\":{\"name\":\"...\"}}]}."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
    ]


def _strip_json_fence(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def parse_translation_response(raw: str) -> dict[tuple[int, str], dict[str, str]]:
    data = json.loads(_strip_json_fence(raw))
    if isinstance(data, dict):
        rows = data.get("translations") or data.get("items") or []
    else:
        rows = data
    if not isinstance(rows, list):
        raise ValueError("translation response must contain a translations array")

    out: dict[tuple[int, str], dict[str, str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            product_id = int(row.get("product_id"))
        except (TypeError, ValueError):
            continue
        language = normalize_language_code(row.get("language"), fallback=None)
        if not language:
            continue
        raw_fields = row.get("fields") if isinstance(row.get("fields"), dict) else row
        fields = {
            field: str(raw_fields.get(field) or "").strip()
            for field in PRODUCT_TRANSLATABLE_FIELDS
            if str(raw_fields.get(field) or "").strip()
        }
        if fields:
            out[(product_id, language)] = fields
    return out


def _source_fields(product: dict[str, Any]) -> dict[str, str]:
    return {
        field: str(product.get(field) or "").strip()
        for field in PRODUCT_TRANSLATABLE_FIELDS
    }


def _has_complete_translation(product: dict[str, Any], language: str) -> bool:
    values = (product.get("translations") or {}).get(language) or {}
    required_fields = [
        field for field, value in _source_fields(product).items()
        if str(value or "").strip()
    ]
    if not required_fields:
        return True
    return all(str(values.get(field) or "").strip() for field in required_fields)


def traditional_rows_from_products(
    products: list[dict[str, Any]],
    *,
    only_missing: bool = True,
) -> dict[tuple[int, str], dict[str, str]]:
    rows: dict[tuple[int, str], dict[str, str]] = {}
    for product in products:
        product_id = product.get("id")
        if product_id is None:
            continue
        if only_missing and _has_complete_translation(product, "zh-Hant"):
            continue
        rows[(int(product_id), "zh-Hant")] = {
            field: to_traditional_chinese(value)
            for field, value in _source_fields(product).items()
        }
    return rows


async def _load_products(limit: int | None = None) -> list[dict[str, Any]]:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.database import AsyncSessionLocal
    from app.models import ProductEntry

    query = (
        select(ProductEntry)
        .options(
            selectinload(ProductEntry.images),
            selectinload(ProductEntry.translations),
        )
        .order_by(ProductEntry.id)
    )
    if limit:
        query = query.limit(limit)
    async with AsyncSessionLocal() as db:
        result = await db.execute(query)
        return [product_entry_to_payload(product) for product in result.scalars().all()]


async def _upsert_translation_rows(rows: dict[tuple[int, str], dict[str, str]]) -> int:
    from sqlalchemy import select

    from app.database import AsyncSessionLocal
    from app.models import ProductEntryTranslation

    count = 0
    async with AsyncSessionLocal() as db:
        for (product_id, language), fields in rows.items():
            result = await db.execute(
                select(ProductEntryTranslation).where(
                    ProductEntryTranslation.product_entry_id == product_id,
                    ProductEntryTranslation.language == language,
                )
            )
            row = result.scalar_one_or_none()
            if not row:
                row = ProductEntryTranslation(product_entry_id=product_id, language=language)
                db.add(row)
            for field, value in fields.items():
                attr = TRANSLATION_ATTRS[field]
                setattr(row, attr, value)
            count += 1
        await db.commit()
    return count


async def _translate_batch(items: list[dict[str, Any]], *, max_tokens: int) -> dict[tuple[int, str], dict[str, str]]:
    from app.services.llm_service import _chat_completion

    raw = await _chat_completion(
        messages=build_translation_messages(items),
        max_tokens=max_tokens,
        temperature=0,
        disable_thinking=True,
    )
    return parse_translation_response(raw)


def _chunks(items: list[dict[str, Any]], size: int):
    for index in range(0, len(items), size):
        yield items[index:index + size]


async def fill_product_translations(
    *,
    languages: list[str],
    limit: int | None,
    batch_size: int,
    max_tokens: int,
    only_missing: bool,
    dry_run: bool,
) -> None:
    target_languages = [
        lang for lang in (
            normalize_language_code(language, fallback=None) for language in languages
        )
        if lang
    ]
    products = await _load_products(limit=limit)
    logger.info("Loaded %d product(s)", len(products))

    source_rows = {
        (int(product["id"]), "zh-Hans"): _source_fields(product)
        for product in products
        if product.get("id") is not None
    }
    traditional_rows = traditional_rows_from_products(products, only_missing=only_missing) if "zh-Hant" in target_languages else {}
    request_languages = [lang for lang in target_languages if lang not in {"zh-Hans", "zh-Hant"}]
    items = build_translation_request_items(
        products,
        target_languages=request_languages,
        only_missing=only_missing,
    )
    logger.info(
        "Source zh-Hans rows: %d; local zh-Hant rows: %d; LLM translation requests: %d",
        len(source_rows),
        len(traditional_rows),
        len(items),
    )

    if dry_run:
        logger.info("Dry run only. First requests: %s", json.dumps(items[:3], ensure_ascii=False, indent=2))
        return

    if "zh-Hans" in target_languages:
        upserted = await _upsert_translation_rows(source_rows)
        logger.info("Upserted %d zh-Hans source row(s)", upserted)

    if traditional_rows:
        upserted = await _upsert_translation_rows(traditional_rows)
        logger.info("Upserted %d local zh-Hant row(s)", upserted)

    total = 0
    completed_requests = 0
    total_requests = len(items)
    batch_size = max(1, batch_size)
    total_batches = (total_requests + batch_size - 1) // batch_size
    if total_requests:
        _emit_progress(0, total_requests, batch_index=0, total_batches=total_batches, upserted_total=0)
    else:
        logger.info("No LLM translation requests to process.")

    for batch_index, batch in enumerate(_chunks(items, batch_size), start=1):
        translated = await _translate_batch(batch, max_tokens=max_tokens)
        upserted = await _upsert_translation_rows(translated)
        total += upserted
        completed_requests += len(batch)
        _emit_progress(
            completed_requests,
            total_requests,
            batch_index=batch_index,
            total_batches=total_batches,
            upserted_total=total,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline-fill multilingual product translations.")
    parser.add_argument(
        "--languages",
        default=",".join(SUPPORTED_LANGUAGES),
        help="Comma-separated target languages. Default: all supported languages.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Optional product limit for testing.")
    parser.add_argument("--batch-size", type=int, default=6, help="LLM translation request batch size.")
    parser.add_argument("--max-tokens", type=int, default=12000, help="Maximum output tokens per LLM translation batch.")
    parser.add_argument("--only-missing", action="store_true", help="Skip languages with complete existing translations.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned work without calling the LLM or writing DB rows.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    languages = [item.strip() for item in args.languages.split(",") if item.strip()]
    asyncio.run(fill_product_translations(
        languages=languages,
        limit=args.limit or None,
        batch_size=args.batch_size,
        max_tokens=args.max_tokens,
        only_missing=bool(args.only_missing),
        dry_run=bool(args.dry_run),
    ))


if __name__ == "__main__":
    main()
