"""
Import product data from Furniture-Crawler CSV into the product_entries / product_images tables.

Usage (run from inside the backend container or locally with correct env):
    python scripts/import_products.py \
        --csv /path/to/Furniture-Crawler/data/csv/landbond/landbond_furniture.csv \
        --images-root /path/to/Furniture-Crawler/data/images/landbond \
        --uploads-dir ./uploads

Defaults assume the script is run from the /app directory inside the Docker container
and the Furniture-Crawler repo is mounted at /app/Furniture-Crawler.
"""

import argparse
import asyncio
import csv
import logging
import os
import re
import shutil
import sys
from pathlib import Path

# Allow running directly from /app inside container (sys.path resolution).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from app.database import AsyncSessionLocal, engine, Base
from app.models import ProductEntry, ProductImage

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_CSV = Path("/app/Furniture-Crawler/data/csv/landbond/landbond_furniture.csv")
DEFAULT_IMAGES_ROOT = Path("/app/Furniture-Crawler/data/images/landbond")
DEFAULT_UPLOADS_DIR = Path("/app/uploads")


def _strip_bom(s: str) -> str:
    return s.lstrip("\ufeff")


def _parse_paths(raw: str) -> list[str]:
    """Split '|'-separated local paths, ignore empty strings."""
    return [p.strip() for p in raw.split("|") if p.strip()]


async def ensure_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def import_csv(csv_path: Path, images_root: Path, uploads_dir: Path):
    await ensure_tables()

    products_dest = uploads_dir / "products" / "landbond"
    products_dest.mkdir(parents=True, exist_ok=True)

    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    logger.info(f"Loaded {len(rows)} rows from {csv_path}")
    created = updated = skipped = 0

    async with AsyncSessionLocal() as db:
        for row in rows:
            product_id_ext = _strip_bom(row.get("product_id", "")).strip()
            brand = row.get("brand", "联邦家私").strip()

            if not product_id_ext:
                logger.warning("Row missing product_id, skipping")
                skipped += 1
                continue

            # Upsert: check existing
            result = await db.execute(
                select(ProductEntry).where(
                    ProductEntry.brand == brand,
                    ProductEntry.product_id_ext == product_id_ext,
                )
            )
            entry = result.scalar_one_or_none()

            fields = dict(
                brand=brand,
                product_id_ext=product_id_ext,
                product_name=row.get("product_name", "").strip(),
                series_name=row.get("series_name", "").strip(),
                space=row.get("space", "").strip(),
                style=row.get("style", "").strip(),
                color=row.get("color", "").strip(),
                material=row.get("material", "").strip(),
                size=row.get("size", "").strip(),
                price_display=row.get("price_display", "").strip(),
                original_price=row.get("original_price", "").strip(),
                serial_number=row.get("serial_number", "").strip(),
                description_text=row.get("description_text", "").strip(),
                detail_content_text=row.get("detail_content_text", "").strip(),
                buy_url=row.get("buy_url", "").strip(),
                detail_url=row.get("detail_url", "").strip(),
            )

            is_new = entry is None
            if is_new:
                entry = ProductEntry(**fields)
                db.add(entry)
                await db.flush()
                created += 1
            else:
                for k, v in fields.items():
                    setattr(entry, k, v)
                # Delete old images before re-inserting
                old_imgs_result = await db.execute(
                    select(ProductImage).where(ProductImage.product_entry_id == entry.id)
                )
                for img in old_imgs_result.scalars().all():
                    await db.delete(img)
                await db.flush()
                updated += 1

            # Handle images
            raw_paths = _parse_paths(row.get("display_image_local_paths", ""))
            for order, rel_path in enumerate(raw_paths):
                # CSV may use Windows backslashes; split on both / and \
                parts = [p for p in re.split(r'[/\\]', rel_path.strip()) if p]
                # Locate brand folder and take everything after it
                try:
                    idx = next(
                        i for i, p in enumerate(parts)
                        if p.lower() == "landbond"
                    )
                    sub_parts = parts[idx + 1:]   # e.g. ["104", "display_01.jpg"]
                except StopIteration:
                    # Fallback: product_id subfolder + filename
                    sub_parts = [product_id_ext, parts[-1]] if parts else []

                if not sub_parts:
                    logger.warning(f"Cannot resolve image path: {rel_path}")
                    continue

                sub = Path(*sub_parts)   # e.g. Path("104/display_01.jpg")
                src = images_root / sub
                dst = products_dest / sub
                dst.parent.mkdir(parents=True, exist_ok=True)

                # stored_rel uses forward slashes (POSIX) for consistency
                stored_rel = "uploads/products/landbond/" + "/".join(sub_parts)

                if src.exists():
                    shutil.copy2(src, dst)
                else:
                    logger.debug(f"Image not found locally: {src}")

                img = ProductImage(
                    product_entry_id=entry.id,
                    local_path=stored_rel,
                    display_order=order,
                )
                db.add(img)

        await db.commit()

    logger.info(
        f"Import done. created={created} updated={updated} skipped={skipped}"
    )


def main():
    parser = argparse.ArgumentParser(description="Import Furniture-Crawler data into product DB")
    parser.add_argument("--csv", default=str(DEFAULT_CSV), help="Path to landbond_furniture.csv")
    parser.add_argument("--images-root", default=str(DEFAULT_IMAGES_ROOT), help="Path to landbond images folder")
    parser.add_argument("--uploads-dir", default=str(DEFAULT_UPLOADS_DIR), help="Backend uploads directory")
    args = parser.parse_args()

    asyncio.run(
        import_csv(
            csv_path=Path(args.csv),
            images_root=Path(args.images_root),
            uploads_dir=Path(args.uploads_dir),
        )
    )


if __name__ == "__main__":
    main()
