"""
Backfill standardized product metadata for existing product_entries.

Run inside the backend container:
    python scripts/backfill_product_metadata.py
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import ProductEntry
from app.services.product_taxonomy import infer_product_metadata


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def main():
    updated = 0
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ProductEntry).order_by(ProductEntry.id))
        products = result.scalars().all()
        for product in products:
            metadata = infer_product_metadata({
                "brand": product.brand,
                "name": product.product_name,
                "product_name": product.product_name,
                "series": product.series_name,
                "series_name": product.series_name,
                "space": product.space,
                "style": product.style,
                "color": product.color,
                "material": product.material,
                "description": product.description_text,
                "description_text": product.description_text,
                "detail_content": product.detail_content_text,
                "detail_content_text": product.detail_content_text,
            })
            product.primary_category = metadata["primary_category"]
            product.secondary_categories_json = json.dumps(metadata["secondary_categories"], ensure_ascii=False)
            product.normalized_brand = metadata["normalized_brand"]
            product.normalized_space = metadata["normalized_space"]
            product.normalized_style = metadata["normalized_style"]
            product.normalized_color = metadata["normalized_color"]
            product.normalized_materials_json = json.dumps(metadata["normalized_materials"], ensure_ascii=False)
            product.category_confidence = metadata["category_confidence"]
            product.classification_source = metadata["classification_source"]
            product.classification_reason = metadata["classification_reason"]
            updated += 1
        await db.commit()
    logger.info("Backfilled standardized metadata for %d products", updated)


if __name__ == "__main__":
    asyncio.run(main())
