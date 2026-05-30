from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import uuid
from typing import Any

from sqlalchemy import select

from app.database import AsyncSessionLocal, init_db
from app.models import BackgroundJob, Conversation, ProductEntry, SceneGenerationRecord
from app.services.background_job_service import (
    DEFAULT_CLAIM_LIMIT,
    DEFAULT_STALE_AFTER_SECONDS,
    DEFAULT_WORKER_POLL_SECONDS,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_FAILED,
    claim_due_jobs,
    job_payload,
    mark_failed_or_retry,
    mark_succeeded,
    requeue_stale_jobs,
)
from app.services.customer_service_service import (
    _send_pending_ai_reply_record,
    create_pending_ai_delivery,
    get_customer_service_settings,
    send_pending_ai_reply,
)
from app.services.scene_service import (
    BACKEND_SCENE_TIMEOUT_SECONDS,
    _get_selected_reference_items,
    _run_scene_generation_for_record,
)

logger = logging.getLogger(__name__)


def _json_list(raw: str | None) -> list[Any]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except Exception:
        return []


async def _load_all_products_for_scene_generation() -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ProductEntry).order_by(ProductEntry.id))
        entries = result.scalars().all()
    return [
        {
            "id": entry.id,
            "name": entry.product_name,
            "space": entry.space,
            "style": entry.style,
            "color": entry.color,
            "material": entry.material,
            "buy_url": entry.buy_url,
            "detail_url": entry.detail_url,
            "primary_category": entry.primary_category,
            "normalized_space": entry.normalized_space,
            "normalized_style": entry.normalized_style,
            "normalized_color": entry.normalized_color,
            "normalized_materials_json": entry.normalized_materials_json,
        }
        for entry in entries
    ]


async def _deliver_scene_generation(record: SceneGenerationRecord, payload: dict[str, Any]) -> None:
    if not payload.get("deliver_to_customer") or not record.conversation_id:
        return

    async with AsyncSessionLocal() as db:
        conversation = await db.get(Conversation, record.conversation_id)
    if not conversation:
        return

    language = payload.get("reply_language") or conversation.language or "en"
    delivery_context = payload.get("delivery_context") if isinstance(payload.get("delivery_context"), dict) else {}
    from app.telegram_bot import build_scene_result_delivery

    scene_delivery = await build_scene_result_delivery(record, language)
    scene_delivery["record_id"] = record.id
    if delivery_context.get("scene_state_action"):
        scene_delivery["scene_state_action"] = delivery_context.get("scene_state_action")
    if delivery_context.get("scene_state_payload"):
        scene_delivery["scene_state_payload"] = delivery_context.get("scene_state_payload")
    preview_text = f"{scene_delivery.get('intro_text', '')}\n\n{scene_delivery.get('preview_line', '')}".strip()

    service_settings = await get_customer_service_settings()
    if service_settings["mode"] != "ai_auto":
        async with AsyncSessionLocal() as db:
            current = await db.get(SceneGenerationRecord, record.id)
            if current:
                current.deferred_delivery = True
                await db.commit()

    await create_pending_ai_delivery(
        conversation_id=conversation.id,
        draft_text=preview_text,
        language=language,
        content_kind="scene_result",
        payload=scene_delivery,
    )
    if service_settings["mode"] == "ai_auto":
        await send_pending_ai_reply(conversation.id)


async def _job_was_cancelled(job_id: int) -> bool:
    async with AsyncSessionLocal() as db:
        current = await db.get(BackgroundJob, job_id)
        return bool(current and current.status == JOB_STATUS_CANCELLED)


async def _mark_scene_record_failed(job: BackgroundJob, error_message: str) -> None:
    payload = job_payload(job)
    record_id = int(payload.get("record_id") or job.entity_id or 0)
    if not record_id:
        return
    async with AsyncSessionLocal() as db:
        record = await db.get(SceneGenerationRecord, record_id)
        if not record or record.status == "completed":
            return
        record.status = "failed"
        record.error_message = (error_message or "Scene generation failed")[:2000]
        await db.commit()


async def _process_scene_generation(job: BackgroundJob) -> None:
    payload = job_payload(job)
    record_id = int(payload.get("record_id") or job.entity_id or 0)
    if not record_id:
        raise RuntimeError("Scene generation job missing record_id")

    async with AsyncSessionLocal() as db:
        record = await db.get(SceneGenerationRecord, record_id)
        if not record:
            return
        if record.status == "completed":
            await _deliver_scene_generation(record, payload)
            return
        primary_product = await db.get(ProductEntry, record.primary_product_id)
        if not primary_product:
            raise RuntimeError(f"Primary product {record.primary_product_id} not found")

    all_products = await _load_all_products_for_scene_generation()
    related_product_ids = [int(x) for x in _json_list(record.related_product_ids_json) if str(x).isdigit()]
    reference_image_items = payload.get("reference_image_items") if isinstance(payload.get("reference_image_items"), list) else []
    reference_image_refs = payload.get("reference_image_refs") if isinstance(payload.get("reference_image_refs"), list) else []
    if reference_image_refs:
        reference_image_items = await _get_selected_reference_items(reference_image_refs)

    result = await _run_scene_generation_for_record(
        record_id=record.id,
        primary_product=primary_product,
        all_products=all_products,
        user_request=record.request_text or "",
        scene_name=record.scene_name or "",
        style_hint=record.style_hint or "",
        related_product_ids=related_product_ids or None,
        reference_image_items=reference_image_items or None,
        timeout_seconds=BACKEND_SCENE_TIMEOUT_SECONDS,
        conversation_id=record.conversation_id,
    )
    if result.status != "completed":
        raise RuntimeError(result.error_message or "Scene generation failed")
    if await _job_was_cancelled(job.id):
        return
    await _deliver_scene_generation(result, payload)


async def _process_pending_ai_autosend(job: BackgroundJob) -> None:
    payload = job_payload(job)
    record_id = int(payload.get("pending_ai_reply_id") or job.entity_id or 0)
    if not record_id:
        raise RuntimeError("Pending AI autosend job missing pending_ai_reply_id")
    await _send_pending_ai_reply_record(record_id)


async def process_background_job(job: BackgroundJob) -> None:
    try:
        if job.job_type == "scene_generation":
            await _process_scene_generation(job)
        elif job.job_type == "pending_ai_autosend":
            await _process_pending_ai_autosend(job)
        else:
            raise RuntimeError(f"Unsupported background job type: {job.job_type}")
    except Exception as exc:
        logger.exception("Background job %s failed: %s", job.id, exc)
        updated = await mark_failed_or_retry(job.id, str(exc))
        if job.job_type == "scene_generation" and updated.status == JOB_STATUS_FAILED:
            await _mark_scene_record_failed(job, str(exc))
        return
    await mark_succeeded(job.id)


async def run_worker() -> None:
    await init_db()
    worker_id = f"{os.uname().nodename}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    stop_event = asyncio.Event()

    def _stop(*_args):
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            pass

    logger.info("Background worker started worker_id=%s", worker_id)
    while not stop_event.is_set():
        await requeue_stale_jobs(stale_after_seconds=DEFAULT_STALE_AFTER_SECONDS)
        jobs = await claim_due_jobs(worker_id, limit=DEFAULT_CLAIM_LIMIT)
        if not jobs:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=DEFAULT_WORKER_POLL_SECONDS)
            except asyncio.TimeoutError:
                pass
            continue
        for job in jobs:
            await process_background_job(job)
    logger.info("Background worker stopped worker_id=%s", worker_id)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    asyncio.run(run_worker())
