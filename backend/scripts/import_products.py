"""
Import product data from Furniture-Crawler CSV into the product_entries / product_images tables.

Usage (run from inside the backend container or locally with correct env):
    python scripts/import_products.py

Or import a single brand CSV explicitly:
    python scripts/import_products.py \
        --csv /path/to/Furniture-Crawler/data/csv/redapple/redapple_furniture.csv \
        --images-root /path/to/Furniture-Crawler/data/images/redapple \
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
from typing import Any

# Allow running directly from /app inside container (sys.path resolution).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from app.database import AsyncSessionLocal, engine, Base
from app.models import ProductEntry, ProductImage

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CRAWLER_ROOT = Path("/app/Furniture-Crawler")
DEFAULT_CSV_ROOT = CRAWLER_ROOT / "data" / "csv"
DEFAULT_IMAGES_ROOT = CRAWLER_ROOT / "data" / "images"
DEFAULT_UPLOADS_DIR = Path("/app/uploads")
DEFAULT_SINGLE_CSV = DEFAULT_CSV_ROOT / "landbond" / "landbond_furniture.csv"

BRAND_UPLOAD_DIR = {
    "联邦家私": "landbond",
    "红苹果": "redapple",
    "左右家居": "zuoyou",
}


def _strip_bom(s: str) -> str:
    return s.lstrip("\ufeff")


def _parse_paths(raw: str) -> list[str]:
    """Split '|'-separated local paths, ignore empty strings."""
    return [p.strip() for p in raw.split("|") if p.strip()]


def _parse_urls(raw: str) -> list[str]:
    """Split '|'-separated URLs and strip thumbnail query params for full-size images."""
    urls = [u.strip() for u in raw.split("|") if u.strip()]
    cleaned = []
    for u in urls:
        if "?" in u:
            u = u.split("?")[0]
        cleaned.append(u)
    return cleaned


def _derive_redapple_product_id(row: dict[str, str]) -> str:
    detail_url = row.get("detail_url", "").strip()
    if detail_url:
        return detail_url.rstrip("/").split("/")[-1].split(".")[0].strip()
    model = row.get("model", "").strip()
    if model:
        return model
    return row.get("product_name", "").strip()


def _infer_zuoyou_space(row: dict[str, str]) -> str:
    inferred = row.get("category_inferred", "").strip()
    title = f"{row.get('product_title', '')} {row.get('product_name_inferred', '')}".strip()
    for text in [inferred, title]:
        if any(keyword in text for keyword in ["沙发", "电视柜", "茶几", "边几", "角几", "柜类"]):
            return "客厅"
        if any(keyword in text for keyword in ["床", "床垫", "床头柜", "衣柜"]):
            return "卧室"
        if any(keyword in text for keyword in ["餐桌", "餐椅", "餐边柜"]):
            return "餐厅"
        if any(keyword in text for keyword in ["书桌", "书柜"]):
            return "书房"
    return ""


def _normalize_row(row: dict[str, str], csv_path: Path) -> tuple[str, dict[str, Any]]:
    brand = row.get("brand", "").strip()

    if brand == "联邦家私":
        product_id_ext = _strip_bom(row.get("product_id", "")).strip()
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
        return product_id_ext, fields

    if brand == "红苹果":
        product_id_ext = _derive_redapple_product_id(row)
        material = row.get("material", "").strip()
        if row.get("color", "").strip():
            material = " / ".join(part for part in [material, row.get("color", "").strip()] if part)
        fields = dict(
            brand=brand,
            product_id_ext=product_id_ext,
            product_name=row.get("product_name", "").strip() or row.get("list_title", "").strip(),
            series_name=row.get("series_name", "").strip(),
            space=row.get("major_category", "").strip(),
            style=row.get("style", "").strip(),
            color=row.get("color", "").strip(),
            material=material,
            size=row.get("specification", "").strip(),
            price_display="",
            original_price="",
            serial_number=row.get("model", "").strip(),
            description_text=row.get("description_text", "").strip(),
            detail_content_text=row.get("series_summary", "").strip(),
            buy_url=row.get("detail_url", "").strip(),
            detail_url=row.get("detail_url", "").strip(),
        )
        return product_id_ext, fields

    if brand == "左右家居":
        product_id_ext = row.get("product_id", "").strip()
        material_parts = [
            row.get("specific_material", "").strip(),
            row.get("fabric", "").strip(),
            row.get("detailed_fabric", "").strip(),
        ]
        fields = dict(
            brand=brand,
            product_id_ext=product_id_ext,
            product_name=row.get("product_name_inferred", "").strip() or row.get("product_title", "").strip(),
            series_name=row.get("series_name", "").strip() or row.get("subbrand", "").strip(),
            space=_infer_zuoyou_space(row),
            style=row.get("style", "").strip(),
            color=row.get("color", "").strip(),
            material=" / ".join(part for part in material_parts if part),
            size=row.get("specifications", "").strip(),
            price_display="",
            original_price="",
            serial_number=row.get("product_code", "").strip(),
            description_text=row.get("description_text", "").strip(),
            detail_content_text=row.get("design_highlights", "").strip(),
            buy_url=row.get("detail_url", "").strip(),
            detail_url=row.get("detail_url", "").strip(),
        )
        return product_id_ext, fields

    raise ValueError(f"Unsupported brand in {csv_path}: {brand or '(empty)'}")


def _infer_brand_key(brand: str, csv_path: Path, images_root: Path) -> str:
    if brand in BRAND_UPLOAD_DIR:
        return BRAND_UPLOAD_DIR[brand]
    for part in [images_root.name, csv_path.parent.name]:
        if part in {"landbond", "redapple", "zuoyou"}:
            return part
    return "misc"


def _discover_csv_jobs(csv_path: Path | None, images_root: Path | None) -> list[tuple[Path, Path]]:
    if csv_path and images_root:
        return [(csv_path, images_root)]

    jobs: list[tuple[Path, Path]] = []
    for candidate in sorted(DEFAULT_CSV_ROOT.glob("*/*.csv")):
        brand_key = candidate.parent.name
        brand_images_root = DEFAULT_IMAGES_ROOT / brand_key
        if brand_images_root.exists():
            jobs.append((candidate, brand_images_root))
    return jobs


async def ensure_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def import_csv(csv_path: Path, images_root: Path, uploads_dir: Path):
    await ensure_tables()

    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    logger.info(f"Loaded {len(rows)} rows from {csv_path}")
    created = updated = skipped = 0

    async with AsyncSessionLocal() as db:
        for row in rows:
            try:
                product_id_ext, fields = _normalize_row(row, csv_path)
            except ValueError as exc:
                logger.warning(str(exc))
                skipped += 1
                continue
            brand = fields["brand"]
            brand_key = _infer_brand_key(brand, csv_path, images_root)
            products_dest = uploads_dir / "products" / brand_key
            products_dest.mkdir(parents=True, exist_ok=True)

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
            raw_urls = _parse_urls(row.get("display_image_urls", ""))
            for order, rel_path in enumerate(raw_paths):
                # CSV may use Windows backslashes; split on both / and \
                parts = [p for p in re.split(r'[/\\]', rel_path.strip()) if p]
                # Locate brand folder and take everything after it
                try:
                    idx = next(
                        i for i, p in enumerate(parts)
                        if p.lower() == brand_key
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
                stored_rel = f"uploads/products/{brand_key}/" + "/".join(sub_parts)

                if src.exists():
                    shutil.copy2(src, dst)
                else:
                    logger.debug(f"Image not found locally: {src}")

                img = ProductImage(
                    product_entry_id=entry.id,
                    local_path=stored_rel,
                    source_url=raw_urls[order] if order < len(raw_urls) else "",
                    display_order=order,
                )
                db.add(img)

        await db.commit()

    logger.info(
        f"Import done. created={created} updated={updated} skipped={skipped}"
    )


def main():
    parser = argparse.ArgumentParser(description="Import Furniture-Crawler data into product DB")
    parser.add_argument("--csv", default="", help="Optional explicit CSV path")
    parser.add_argument("--images-root", default="", help="Optional explicit images root path")
    parser.add_argument("--uploads-dir", default=str(DEFAULT_UPLOADS_DIR), help="Backend uploads directory")
    args = parser.parse_args()

    csv_path = Path(args.csv) if args.csv else None
    images_root = Path(args.images_root) if args.images_root else None
    jobs = _discover_csv_jobs(csv_path, images_root)
    if not jobs:
        raise SystemExit("No importable product CSVs found.")

    async def _run():
        for job_csv, job_images in jobs:
            await import_csv(
                csv_path=job_csv,
                images_root=job_images,
                uploads_dir=Path(args.uploads_dir),
            )

    asyncio.run(_run())


if __name__ == "__main__":
    main()
