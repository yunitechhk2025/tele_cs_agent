import asyncio
import base64
import json
import logging
import os
import shutil
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import delete, select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import ProductEntry, ProductImage, SceneGenerationImage, SceneGenerationRecord
from app.services.llm_service import (
    build_image_client,
    get_llm_settings,
    select_scene_bundle_products,
)

logger = logging.getLogger(__name__)
settings = get_settings()
SCENE_OUTPUT_COUNT = 1
CUSTOMER_SCENE_TIMEOUT_SECONDS = 300
BACKEND_SCENE_TIMEOUT_SECONDS = 600
ACTIVE_SCENE_TASKS: dict[int, asyncio.Task[Any]] = {}


def _scene_upload_root() -> Path:
    root = Path(settings.FILE_STORAGE_DIR) / "generated_scenes"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _clean_json_list(raw: str | None) -> list[Any]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _normalize_reuse_text(value: str | None) -> str:
    return " ".join((value or "").strip().lower().split())


def _scene_defaults(primary_product: ProductEntry) -> tuple[str, str]:
    scene = primary_product.space.strip() or "客厅"
    style = primary_product.style.strip() or ""
    return scene, style


def _compatible_root(base_url: str) -> str:
    if not base_url:
        return ""
    parsed = urlparse(base_url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return base_url.rstrip("/")


def _aspect_ratio_from_size(size: str) -> str:
    try:
        w_str, h_str = size.lower().split("x", 1)
        w = int(w_str)
        h = int(h_str)
    except Exception:
        return "16:9"
    if abs(w - h) < 50:
        return "1:1"
    return "16:9" if w > h else "9:16"


def _resolution_from_size(size: str) -> str:
    try:
        w_str, h_str = size.lower().split("x", 1)
        max_side = max(int(w_str), int(h_str))
    except Exception:
        return "1k"
    return "2k" if max_side > 1200 else "1k"


def _mime_type_from_filename(name: str) -> str:
    ext = Path(name).suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(ext, "image/png")


def _product_image_reference_value(image: ProductImage | None) -> str:
    if not image:
        return ""
    if image.source_url:
        return image.source_url

    path = image.local_path or ""
    if not path:
        return ""
    full_path = path if os.path.isabs(path) else os.path.join("/app", path)
    if not os.path.exists(full_path):
        return ""

    mime_type = _mime_type_from_filename(full_path)
    with open(full_path, "rb") as fh:
        encoded = base64.b64encode(fh.read()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


async def _download_remote_binary(
    client: httpx.AsyncClient,
    url: str,
    attempts: int = 4,
) -> bytes:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()
            return response.content
        except Exception as exc:
            last_error = exc
            if attempt >= attempts:
                break
            await asyncio.sleep(min(2 * attempt, 5))
    if last_error:
        raise last_error
    raise RuntimeError(f"Failed to download remote binary: {url}")


def _build_scene_prompt(
    primary_product: ProductEntry,
    related_products: list[ProductEntry],
    scene_name: str,
    style_hint: str,
    user_request: str,
    reference_items: list[dict[str, Any]] | None = None,
) -> str:
    primary_lines = [
        f"Main product brand: {primary_product.brand}",
        f"Main product name: {primary_product.product_name}",
        f"Main product space: {primary_product.space}",
        f"Main product style: {primary_product.style}",
        f"Main product color: {primary_product.color}",
        f"Main product material: {primary_product.material}",
        f"Main product size: {primary_product.size}",
        f"Main product serial/model: {primary_product.serial_number}",
        f"Main product description: {primary_product.description_text}",
    ]
    related_lines = [
        (
            f"- {p.product_name} | 空间:{p.space} | 风格:{p.style} | 颜色:{p.color} "
            f"| 材质:{p.material} | 尺寸:{p.size}"
        )
        for p in related_products
    ]
    related_text = "\n".join(related_lines) or "- No extra products"
    reference_lines = []
    for idx, item in enumerate(reference_items or [], start=1):
        role = "MAIN PRODUCT" if item.get("role") == "main" else "COMPLEMENTARY PRODUCT"
        reference_lines.append(
            f"- Reference image #{idx}: {role} | Brand:{item.get('brand', '')} | "
            f"Name:{item.get('product_name', '')} | Product ID:{item.get('product_id', '')}"
        )
    reference_text = "\n".join(reference_lines) or "- No reference images attached"
    return (
        "Create a photorealistic furniture showroom / home-interior scene image.\n"
        f"Requested scene: {scene_name}\n"
        f"Style hint: {style_hint or primary_product.style or '真实家居'}\n"
        f"Customer request: {user_request or primary_product.product_name}\n\n"
        "IMPORTANT: Every attached reference image corresponds to a real catalog product. "
        "You MUST reproduce each referenced product faithfully — keep its exact shape, material, color, texture, "
        "proportions, silhouette, and visible design details. Do NOT redesign, simplify, or replace any referenced product with generic furniture.\n"
        "Place the exact main product as the visual focus in the requested scene setting.\n"
        "Complementary products may appear as supporting items in the same room, but if they have reference images attached they must also remain faithful to those references.\n"
        "No people, no text overlay, no watermark, no logo, no fantasy styling.\n\n"
        "Attached reference image mapping:\n"
        + reference_text
        + "\n\n"
        "Main product facts:\n"
        + "\n".join(primary_lines)
        + "\n\nComplementary products:\n"
        + related_text
        + "\n\nOutput requirements:\n"
        "- realistic interior lighting\n"
        "- commercially usable composition\n"
        "- the main product must look identical to its reference image\n"
        "- every referenced complementary product must also match its own reference image\n"
        "- do not invent unrelated side furniture when a referenced complementary product is provided\n"
        "- make the room look complete and believable\n"
    )


async def _generate_image_binary(prompt: str, cfg: dict[str, str]) -> bytes:
    client = build_image_client(cfg)
    model = cfg.get("image_model") or cfg.get("llm_model", "gpt-image-1")
    size = cfg.get("image_size") or "1024x1024"
    quality = cfg.get("image_quality") or "high"
    style = cfg.get("image_style") or "natural"

    try:
        response = await client.images.generate(
            model=model,
            prompt=prompt,
            size=size,
            quality=quality,
            style=style,
            response_format="b64_json",
        )
        data = response.data[0]
        if getattr(data, "b64_json", None):
            return base64.b64decode(data.b64_json)
    except Exception as first_error:
        logger.warning("Image generation with b64_json failed, retrying with URL fallback: %s", first_error)
        response = await client.images.generate(
            model=model,
            prompt=prompt,
            size=size,
            quality=quality,
            style=style,
        )
        data = response.data[0]
        if getattr(data, "b64_json", None):
            return base64.b64decode(data.b64_json)
        image_url = getattr(data, "url", None)
        if not image_url:
            raise
        async with httpx.AsyncClient(timeout=180) as http_client:
            image_resp = await http_client.get(image_url)
            image_resp.raise_for_status()
            return image_resp.content

    raise RuntimeError("Image generation returned no image data")


async def _generate_dashscope_kling_images(
    prompt: str,
    cfg: dict[str, str],
    count: int,
    reference_image_urls: list[str] | None = None,
) -> list[bytes]:
    api_key = cfg.get("image_api_key") or cfg.get("llm_api_key", "")
    base_url = _compatible_root(cfg.get("image_base_url") or cfg.get("llm_base_url", ""))
    if not api_key:
        raise RuntimeError("Image API key is empty")
    if not base_url:
        raise RuntimeError("Image base URL is empty")

    model = cfg.get("image_model", "kling/kling-v3-image-generation")
    create_url = f"{base_url}/api/v1/services/aigc/image-generation/generation"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }

    content: list[dict[str, str]] = [{"text": prompt}]
    if reference_image_urls:
        for url in reference_image_urls[:5]:
            content.append({"image": url})
        if "omni" not in model:
            model = model.replace("kling-v3-image-generation", "kling-v3-omni-image-generation")
            logger.info("Switched to omni model for multi-image reference: %s", model)

    payload = {
        "model": model,
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": content,
                }
            ]
        },
        "parameters": {
            "n": count,
            "aspect_ratio": _aspect_ratio_from_size(cfg.get("image_size", "1024x1024")),
            "resolution": _resolution_from_size(cfg.get("image_size", "1024x1024")),
            "watermark": False,
        },
    }
    async with httpx.AsyncClient(timeout=180) as client:
        last_error_message = "DashScope image generation timed out"
        for task_attempt in range(1, 3):
            create_resp = await client.post(create_url, headers=headers, json=payload)
            create_resp.raise_for_status()
            created = create_resp.json()
            task_id = (((created or {}).get("output") or {}).get("task_id"))
            if not task_id:
                raise RuntimeError(created.get("message") or created.get("code") or "DashScope image task creation failed")

            query_url = f"{base_url}/api/v1/tasks/{task_id}"
            last_payload: dict[str, Any] = created
            for _ in range(36):
                poll_resp = await client.get(query_url, headers={"Authorization": f"Bearer {api_key}"})
                poll_resp.raise_for_status()
                last_payload = poll_resp.json()
                output = (last_payload or {}).get("output") or {}
                status = output.get("task_status")
                if status == "SUCCEEDED":
                    contents = (((output.get("choices") or [{}])[0].get("message") or {}).get("content") or [])
                    urls = [item.get("image") for item in contents if item.get("image")]
                    binaries: list[bytes] = []
                    for url in urls:
                        binaries.append(await _download_remote_binary(client, url))
                    if not binaries:
                        raise RuntimeError("DashScope task succeeded but returned no image URLs")
                    return binaries
                if status == "FAILED":
                    last_error_message = json.dumps(last_payload, ensure_ascii=False)[:4000]
                    logger.warning(
                        "DashScope image task failed on attempt %s/%s: %s",
                        task_attempt,
                        2,
                        last_error_message,
                    )
                    break
                await asyncio.sleep(5)
            else:
                last_error_message = f"DashScope image generation timed out after polling task {task_id}"

            if task_attempt < 2:
                await asyncio.sleep(2)
                continue

        raise RuntimeError(last_error_message)


async def _get_product_image_urls(product_id: int, limit: int = 3) -> list[str]:
    """Fetch original source URLs for a product's images (for use as reference in image generation)."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ProductImage)
            .where(ProductImage.product_entry_id == product_id)
            .order_by(ProductImage.display_order)
            .limit(limit)
        )
        images = result.scalars().all()
    return [img.source_url for img in images if img.source_url]


async def _get_selected_reference_items(
    refs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not refs:
        return []
    product_ids = [int(ref["product_id"]) for ref in refs]
    image_orders = [int(ref["image_order"]) for ref in refs]

    async with AsyncSessionLocal() as db:
        product_result = await db.execute(
            select(ProductEntry).where(ProductEntry.id.in_(product_ids))
        )
        products_map = {p.id: p for p in product_result.scalars().all()}
        image_result = await db.execute(
            select(ProductImage).where(
                ProductImage.product_entry_id.in_(product_ids),
                ProductImage.display_order.in_(image_orders),
            )
        )
        images_map = {
            (img.product_entry_id, img.display_order): img
            for img in image_result.scalars().all()
        }

    items: list[dict[str, Any]] = []
    for idx, ref in enumerate(refs):
        product_id = int(ref["product_id"])
        image_order = int(ref["image_order"])
        product = products_map.get(product_id)
        image = images_map.get((product_id, image_order))
        ref_value = _product_image_reference_value(image)
        if not product or not image or not ref_value:
            continue
        items.append(
            {
                "product_id": product.id,
                "product_name": product.product_name,
                "brand": product.brand or "",
                "role": "main" if idx == 0 else "related",
                "image_order": image_order,
                "url": ref_value,
            }
        )
    return items


async def _build_default_reference_items(
    primary_product: ProductEntry,
    related_products: list[ProductEntry],
) -> list[dict[str, Any]]:
    product_order = [primary_product] + related_products[:3]
    items: list[dict[str, Any]] = []
    product_ids = [product.id for product in product_order]
    async with AsyncSessionLocal() as db:
        image_result = await db.execute(
            select(ProductImage)
            .where(ProductImage.product_entry_id.in_(product_ids))
            .order_by(ProductImage.product_entry_id, ProductImage.display_order)
        )
        images = image_result.scalars().all()

    first_images: dict[int, ProductImage] = {}
    for image in images:
        first_images.setdefault(image.product_entry_id, image)

    for idx, product in enumerate(product_order):
        image = first_images.get(product.id)
        ref_value = _product_image_reference_value(image)
        if not ref_value:
            continue
        items.append(
            {
                "product_id": product.id,
                "product_name": product.product_name,
                "brand": product.brand or "",
                "role": "main" if idx == 0 else "related",
                "image_order": image.display_order if image else 0,
                "url": ref_value,
            }
        )
    return items


async def _load_products(ids: list[int]) -> list[ProductEntry]:
    if not ids:
        return []
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ProductEntry).where(ProductEntry.id.in_(ids))
        )
        products = result.scalars().all()
    product_map = {p.id: p for p in products}
    return [product_map[i] for i in ids if i in product_map]


async def _save_record_images(
    db,
    record_id: int,
    binaries: list[bytes],
    mime_types: list[str] | None = None,
):
    await db.execute(delete(SceneGenerationImage).where(SceneGenerationImage.record_id == record_id))
    mime_types = mime_types or []
    for idx, binary in enumerate(binaries):
        db.add(
            SceneGenerationImage(
                record_id=record_id,
                image_index=idx,
                mime_type=mime_types[idx] if idx < len(mime_types) else "image/png",
                binary_data=binary,
                file_size=len(binary),
            )
        )


async def _backfill_record_images_from_disk(record: SceneGenerationRecord):
    async with AsyncSessionLocal() as db:
        existing = await db.execute(
            select(SceneGenerationImage.id).where(SceneGenerationImage.record_id == record.id).limit(1)
        )
        if existing.first():
            return

        current = await db.get(SceneGenerationRecord, record.id)
        if not current:
            return

        binaries: list[bytes] = []
        mime_types: list[str] = []
        for rel_path in _clean_json_list(current.output_paths_json):
            full_path = os.path.join("/app", rel_path)
            if not os.path.exists(full_path):
                continue
            with open(full_path, "rb") as fh:
                binaries.append(fh.read())
            mime_types.append(_mime_type_from_filename(full_path))

        if not binaries:
            return

        await _save_record_images(db, current.id, binaries, mime_types)
        await db.commit()


async def _find_reusable_record(
    primary_product_id: int,
    scene_name: str,
    style_hint: str,
    related_product_ids: list[int] | None = None,
) -> SceneGenerationRecord | None:
    scene_key = _normalize_reuse_text(scene_name)
    style_key = _normalize_reuse_text(style_hint)
    requested_related = sorted(int(x) for x in (related_product_ids or []))

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(SceneGenerationRecord)
            .where(
                SceneGenerationRecord.primary_product_id == primary_product_id,
                SceneGenerationRecord.status == "completed",
            )
            .order_by(SceneGenerationRecord.updated_at.desc())
            .limit(20)
        )
        candidates = result.scalars().all()

    for candidate in candidates:
        if _normalize_reuse_text(candidate.scene_name) != scene_key:
            continue
        if _normalize_reuse_text(candidate.style_hint) != style_key:
            continue
        if requested_related:
            candidate_related = sorted(
                int(x) for x in _clean_json_list(candidate.related_product_ids_json) if str(x).isdigit()
            )
            if candidate_related != requested_related:
                continue
        await _backfill_record_images_from_disk(candidate)
        async with AsyncSessionLocal() as db:
            refreshed = await db.get(SceneGenerationRecord, candidate.id)
            if refreshed:
                return refreshed
    return None


async def build_scene_record_response(record: SceneGenerationRecord) -> dict[str, Any]:
    if record.status == "completed":
        await _backfill_record_images_from_disk(record)

    async with AsyncSessionLocal() as db:
        primary = await db.get(ProductEntry, record.primary_product_id)
        related_ids = [int(x) for x in _clean_json_list(record.related_product_ids_json) if str(x).isdigit()]
        related_products = []
        if related_ids:
            result = await db.execute(select(ProductEntry).where(ProductEntry.id.in_(related_ids)).order_by(ProductEntry.id))
            related_products = result.scalars().all()
        image_result = await db.execute(
            select(SceneGenerationImage)
            .where(SceneGenerationImage.record_id == record.id)
            .order_by(SceneGenerationImage.image_index)
        )
        scene_images = image_result.scalars().all()

    if scene_images:
        image_urls = [
            f"/api/scene-generations/{record.id}/images/{img.image_index}"
            for img in scene_images
        ]
    else:
        image_urls = [
            f"/api/scene-generations/{record.id}/images/{idx}"
            for idx, _ in enumerate(_clean_json_list(record.output_paths_json))
        ]
    return {
        "id": record.id,
        "conversation_id": record.conversation_id,
        "primary_product_id": record.primary_product_id,
        "primary_product_name": primary.product_name if primary else "",
        "scene_name": record.scene_name or "",
        "style_hint": record.style_hint or "",
        "request_text": record.request_text or "",
        "prompt_text": record.prompt_text or "",
        "related_products": [
            {
                "id": p.id,
                "product_name": p.product_name,
                "brand": p.brand or "",
                "buy_url": p.buy_url or "",
                "detail_url": p.detail_url or "",
            }
            for p in related_products
        ],
        "image_urls": image_urls,
        "duration_ms": record.duration_ms or 0,
        "status": record.status or "",
        "in_library": bool(getattr(record, "in_library", False)),
        "error_message": record.error_message or "",
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


async def _create_scene_generation_record(
    primary_product: ProductEntry,
    user_request: str = "",
    scene_name: str = "",
    style_hint: str = "",
    related_product_ids: list[int] | None = None,
    conversation_id: int | None = None,
    allow_reuse: bool = True,
) -> SceneGenerationRecord:
    default_scene, default_style = _scene_defaults(primary_product)
    scene_name = scene_name.strip() or default_scene
    style_hint = style_hint.strip() or default_style

    if allow_reuse:
        reusable = await _find_reusable_record(
            primary_product_id=primary_product.id,
            scene_name=scene_name,
            style_hint=style_hint,
            related_product_ids=related_product_ids,
        )
        if reusable:
            return reusable

    record = SceneGenerationRecord(
        conversation_id=conversation_id,
        primary_product_id=primary_product.id,
        scene_name=scene_name,
        style_hint=style_hint,
        request_text=user_request or "",
        prompt_text="",
        related_product_ids_json=json.dumps(related_product_ids or [], ensure_ascii=False),
        output_paths_json="[]",
        status="pending",
        duration_ms=0,
        error_message="",
    )

    async with AsyncSessionLocal() as db:
        db.add(record)
        await db.commit()
        await db.refresh(record)
        return record


async def cleanup_stale_pending_scene_generations(max_age_seconds: int = BACKEND_SCENE_TIMEOUT_SECONDS) -> int:
    cutoff = datetime.utcnow() - timedelta(seconds=max_age_seconds)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(SceneGenerationRecord).where(
                SceneGenerationRecord.status == "pending",
                SceneGenerationRecord.updated_at < cutoff,
            )
        )
        stale_records = result.scalars().all()
        if not stale_records:
            return 0

        timeout_message = f"Scene generation timed out after {max_age_seconds} seconds"
        for record in stale_records:
            record.status = "failed"
            if not record.duration_ms:
                elapsed = max_age_seconds
                if record.created_at:
                    elapsed = max(
                        max_age_seconds,
                        int((datetime.utcnow() - record.created_at).total_seconds()),
                    )
                record.duration_ms = elapsed * 1000
            record.error_message = timeout_message
        await db.commit()
        return len(stale_records)


async def cancel_scene_generation_task(record_id: int) -> bool:
    task = ACTIVE_SCENE_TASKS.get(record_id)
    if not task:
        return False
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("Scene generation task %s failed during cancellation", record_id)
    return True


async def _generate_scene_outputs(
    record_id: int,
    cfg: dict[str, str],
    prompt: str,
    primary_product: ProductEntry,
    selected_related_ids: list[int],
    reference_items: list[dict[str, Any]],
) -> tuple[list[str], list[bytes]]:
    output_paths: list[str] = []
    upload_dir = _scene_upload_root() / str(record_id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    if (cfg.get("image_model") or "").startswith("kling/"):
        ref_urls = [item["url"] for item in reference_items if item.get("url")]
        if ref_urls:
            logger.info(
                "Using %d reference image(s) for scene generation record %s (primary=%s related=%s)",
                len(ref_urls),
                record_id,
                primary_product.id,
                selected_related_ids,
            )
        binaries = await _generate_dashscope_kling_images(
            prompt,
            cfg,
            SCENE_OUTPUT_COUNT,
            reference_image_urls=ref_urls,
        )
    else:
        binaries = []
        for _ in range(SCENE_OUTPUT_COUNT):
            binaries.append(await _generate_image_binary(prompt, cfg))

    for idx, binary in enumerate(binaries):
        filename = f"{uuid.uuid4().hex}_{idx + 1}.png"
        full = upload_dir / filename
        full.write_bytes(binary)
        rel = os.path.join("uploads", "generated_scenes", str(record_id), filename).replace("\\", "/")
        output_paths.append(rel)
    return output_paths, binaries


async def _mark_scene_generation_failed(
    record_id: int,
    duration_ms: int,
    error_message: str,
) -> SceneGenerationRecord | None:
    async with AsyncSessionLocal() as db:
        current = await db.get(SceneGenerationRecord, record_id)
        if not current:
            return None
        current.duration_ms = duration_ms
        current.status = "failed"
        current.error_message = error_message[:2000]
        await db.commit()
        await db.refresh(current)
        return current


async def _run_scene_generation_for_record(
    record_id: int,
    primary_product: ProductEntry,
    all_products: list[dict[str, Any]],
    user_request: str = "",
    scene_name: str = "",
    style_hint: str = "",
    related_product_ids: list[int] | None = None,
    reference_image_items: list[dict[str, Any]] | None = None,
    timeout_seconds: int = BACKEND_SCENE_TIMEOUT_SECONDS,
) -> SceneGenerationRecord:
    cfg = await get_llm_settings()
    default_scene, default_style = _scene_defaults(primary_product)
    scene_name = scene_name.strip() or default_scene
    style_hint = style_hint.strip() or default_style

    candidate_products = [
        p for p in all_products
        if int(p["id"]) != primary_product.id
    ]
    preferred_candidates = [
        p for p in candidate_products
        if (p.get("space") == primary_product.space or not primary_product.space or p.get("style") == primary_product.style)
    ]
    shortlist = preferred_candidates[:30] or candidate_products[:30]

    selected_related_ids = related_product_ids or await select_scene_bundle_products(
        user_message=user_request or primary_product.product_name,
        primary_product={
            "id": primary_product.id,
            "brand": primary_product.brand,
            "name": primary_product.product_name,
            "space": primary_product.space,
            "style": primary_product.style,
            "material": primary_product.material,
        },
        candidate_products=shortlist,
        scene_name=scene_name,
        style_hint=style_hint,
    )
    if not selected_related_ids:
        selected_related_ids = [int(p["id"]) for p in shortlist[:3]]
    selected_related_ids = [int(pid) for pid in selected_related_ids if int(pid) != primary_product.id][:3]

    related_products = await _load_products(selected_related_ids)
    reference_items = reference_image_items or await _build_default_reference_items(primary_product, related_products)
    prompt = _build_scene_prompt(
        primary_product,
        related_products,
        scene_name,
        style_hint,
        user_request,
        reference_items=reference_items,
    )

    async with AsyncSessionLocal() as db:
        current = await db.get(SceneGenerationRecord, record_id)
        if not current:
            raise RuntimeError(f"Scene generation record {record_id} not found")
        current.scene_name = scene_name
        current.style_hint = style_hint
        current.request_text = user_request or ""
        current.prompt_text = prompt
        current.related_product_ids_json = json.dumps(selected_related_ids, ensure_ascii=False)
        current.status = "pending"
        current.error_message = ""
        await db.commit()

    start = time.perf_counter()
    try:
        output_paths, binaries = await asyncio.wait_for(
            _generate_scene_outputs(
                record_id=record_id,
                cfg=cfg,
                prompt=prompt,
                primary_product=primary_product,
                selected_related_ids=selected_related_ids,
                reference_items=reference_items,
            ),
            timeout=timeout_seconds,
        )
        duration_ms = int((time.perf_counter() - start) * 1000)
        async with AsyncSessionLocal() as db:
            current = await db.get(SceneGenerationRecord, record_id)
            if not current:
                raise RuntimeError(f"Scene generation record {record_id} disappeared")
            await _save_record_images(db, current.id, binaries, ["image/png"] * len(binaries))
            current.output_paths_json = json.dumps(output_paths, ensure_ascii=False)
            current.duration_ms = duration_ms
            current.status = "completed"
            current.error_message = ""
            await db.commit()
            await db.refresh(current)
            return current
    except asyncio.TimeoutError:
        duration_ms = int((time.perf_counter() - start) * 1000)
        shutil.rmtree(_scene_upload_root() / str(record_id), ignore_errors=True)
        timeout_message = f"Scene generation timed out after {timeout_seconds} seconds"
        logger.warning(
            "Scene image generation timed out for product %s record %s after %s seconds",
            primary_product.id,
            record_id,
            timeout_seconds,
        )
        current = await _mark_scene_generation_failed(record_id, duration_ms, timeout_message)
        if current:
            return current
        raise RuntimeError(timeout_message)
    except asyncio.CancelledError:
        shutil.rmtree(_scene_upload_root() / str(record_id), ignore_errors=True)
        logger.info("Scene generation task %s was cancelled", record_id)
        raise
    except Exception as e:
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.error("Scene image generation failed for product %s: %s", primary_product.id, e, exc_info=True)
        current = await _mark_scene_generation_failed(record_id, duration_ms, str(e))
        if current:
            return current
        raise


async def start_scene_generation(
    primary_product: ProductEntry,
    all_products: list[dict[str, Any]],
    user_request: str = "",
    scene_name: str = "",
    style_hint: str = "",
    related_product_ids: list[int] | None = None,
    conversation_id: int | None = None,
    reference_image_items: list[dict[str, Any]] | None = None,
    allow_reuse: bool = True,
) -> SceneGenerationRecord:
    record = await _create_scene_generation_record(
        primary_product=primary_product,
        user_request=user_request,
        scene_name=scene_name,
        style_hint=style_hint,
        related_product_ids=related_product_ids,
        conversation_id=conversation_id,
        allow_reuse=allow_reuse,
    )
    if record.status == "completed":
        return record

    async def _job():
        try:
            await _run_scene_generation_for_record(
                record_id=record.id,
                primary_product=primary_product,
                all_products=all_products,
                user_request=user_request,
                scene_name=scene_name,
                style_hint=style_hint,
                related_product_ids=related_product_ids,
                reference_image_items=reference_image_items,
                timeout_seconds=BACKEND_SCENE_TIMEOUT_SECONDS,
            )
        except asyncio.CancelledError:
            logger.info("Scene generation background job %s cancelled", record.id)
        except Exception:
            logger.exception("Scene generation background job %s failed", record.id)
        finally:
            ACTIVE_SCENE_TASKS.pop(record.id, None)

    ACTIVE_SCENE_TASKS[record.id] = asyncio.create_task(_job())
    return record


async def generate_scene_images(
    primary_product: ProductEntry,
    all_products: list[dict[str, Any]],
    user_request: str = "",
    scene_name: str = "",
    style_hint: str = "",
    related_product_ids: list[int] | None = None,
    conversation_id: int | None = None,
    reference_image_items: list[dict[str, Any]] | None = None,
    allow_reuse: bool = True,
    timeout_seconds: int = BACKEND_SCENE_TIMEOUT_SECONDS,
) -> SceneGenerationRecord:
    record = await _create_scene_generation_record(
        primary_product=primary_product,
        user_request=user_request,
        scene_name=scene_name,
        style_hint=style_hint,
        related_product_ids=related_product_ids,
        conversation_id=conversation_id,
        allow_reuse=allow_reuse,
    )
    if record.status == "completed":
        logger.info(
            "Reusing cached scene images for product %s scene=%s style=%s record=%s",
            primary_product.id,
            record.scene_name,
            record.style_hint,
            record.id,
        )
        return record
    return await _run_scene_generation_for_record(
        record_id=record.id,
        primary_product=primary_product,
        all_products=all_products,
        user_request=user_request,
        scene_name=scene_name,
        style_hint=style_hint,
        related_product_ids=related_product_ids,
        reference_image_items=reference_image_items,
        timeout_seconds=timeout_seconds,
    )
