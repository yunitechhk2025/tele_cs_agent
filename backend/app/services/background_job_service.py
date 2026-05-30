from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update

from app.database import AsyncSessionLocal
from app.models import BackgroundJob


JOB_STATUS_QUEUED = "queued"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_SUCCEEDED = "succeeded"
JOB_STATUS_FAILED = "failed"
JOB_STATUS_CANCELLED = "cancelled"

DEFAULT_WORKER_POLL_SECONDS = 1
DEFAULT_CLAIM_LIMIT = 5
DEFAULT_STALE_AFTER_SECONDS = 900
SCENE_GENERATION_MAX_ATTEMPTS = 2
PENDING_AI_AUTOSEND_MAX_ATTEMPTS = 5


def _payload_json(payload: dict[str, Any] | None) -> str:
    return json.dumps(payload or {}, ensure_ascii=False)


def job_payload(job: BackgroundJob) -> dict[str, Any]:
    try:
        data = json.loads(job.payload_json or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


async def enqueue_job(
    *,
    job_type: str,
    entity_type: str = "",
    entity_id: int | None = None,
    dedupe_key: str,
    payload: dict[str, Any] | None = None,
    run_after: datetime | None = None,
    max_attempts: int = 1,
) -> BackgroundJob:
    now = datetime.utcnow()
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(BackgroundJob).where(BackgroundJob.dedupe_key == dedupe_key))
        existing = result.scalar_one_or_none()
        if existing:
            if existing.status == JOB_STATUS_RUNNING:
                return existing
            existing.job_type = job_type
            existing.entity_type = entity_type or ""
            existing.entity_id = entity_id
            existing.payload_json = _payload_json(payload)
            existing.status = JOB_STATUS_QUEUED
            existing.run_after = run_after or now
            existing.attempts = 0
            existing.max_attempts = max(1, int(max_attempts or 1))
            existing.locked_by = ""
            existing.locked_at = None
            existing.last_error = ""
            existing.finished_at = None
            existing.updated_at = now
            await db.commit()
            await db.refresh(existing)
            return existing

        job = BackgroundJob(
            job_type=job_type,
            entity_type=entity_type or "",
            entity_id=entity_id,
            dedupe_key=dedupe_key,
            payload_json=_payload_json(payload),
            status=JOB_STATUS_QUEUED,
            run_after=run_after or now,
            attempts=0,
            max_attempts=max(1, int(max_attempts or 1)),
            locked_by="",
            locked_at=None,
            last_error="",
            finished_at=None,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job


async def claim_due_jobs(worker_id: str, *, limit: int = DEFAULT_CLAIM_LIMIT) -> list[BackgroundJob]:
    now = datetime.utcnow()
    async with AsyncSessionLocal() as db:
        stmt = (
            select(BackgroundJob)
            .where(
                BackgroundJob.status == JOB_STATUS_QUEUED,
                BackgroundJob.run_after <= now,
            )
            .order_by(BackgroundJob.run_after, BackgroundJob.id)
            .limit(max(1, int(limit or 1)))
            .with_for_update(skip_locked=True)
        )
        result = await db.execute(stmt)
        jobs = list(result.scalars().all())
        for job in jobs:
            job.status = JOB_STATUS_RUNNING
            job.locked_by = worker_id
            job.locked_at = now
            job.attempts = int(job.attempts or 0) + 1
            job.updated_at = now
        await db.commit()
        for job in jobs:
            await db.refresh(job)
        return jobs


async def mark_succeeded(job_id: int) -> BackgroundJob:
    now = datetime.utcnow()
    async with AsyncSessionLocal() as db:
        job = await db.get(BackgroundJob, job_id)
        if not job:
            raise RuntimeError(f"Background job {job_id} not found")
        if job.status == JOB_STATUS_CANCELLED:
            return job
        job.status = JOB_STATUS_SUCCEEDED
        job.locked_by = ""
        job.locked_at = None
        job.last_error = ""
        job.finished_at = now
        job.updated_at = now
        await db.commit()
        await db.refresh(job)
        return job


async def mark_failed_or_retry(
    job_id: int,
    error_message: str,
    *,
    retry_delay_seconds: int = 30,
) -> BackgroundJob:
    now = datetime.utcnow()
    async with AsyncSessionLocal() as db:
        job = await db.get(BackgroundJob, job_id)
        if not job:
            raise RuntimeError(f"Background job {job_id} not found")
        if job.status == JOB_STATUS_CANCELLED:
            return job
        job.last_error = (error_message or "")[:4000]
        job.locked_by = ""
        job.locked_at = None
        job.updated_at = now
        if int(job.attempts or 0) >= int(job.max_attempts or 1):
            job.status = JOB_STATUS_FAILED
            job.finished_at = now
        else:
            job.status = JOB_STATUS_QUEUED
            job.run_after = now + timedelta(seconds=max(0, int(retry_delay_seconds or 0)))
            job.finished_at = None
        await db.commit()
        await db.refresh(job)
        return job


async def cancel_jobs_for_entity(entity_type: str, entity_id: int) -> int:
    now = datetime.utcnow()
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(BackgroundJob)
            .where(
                BackgroundJob.entity_type == entity_type,
                BackgroundJob.entity_id == entity_id,
                BackgroundJob.status.in_([JOB_STATUS_QUEUED, JOB_STATUS_RUNNING]),
            )
            .values(
                status=JOB_STATUS_CANCELLED,
                locked_by="",
                locked_at=None,
                finished_at=now,
                updated_at=now,
            )
        )
        await db.commit()
        return int(result.rowcount or 0)


async def requeue_stale_jobs(*, stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS) -> int:
    now = datetime.utcnow()
    cutoff = now - timedelta(seconds=max(1, int(stale_after_seconds or 1)))
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(BackgroundJob)
            .where(
                BackgroundJob.status == JOB_STATUS_RUNNING,
                BackgroundJob.locked_at < cutoff,
                BackgroundJob.attempts < BackgroundJob.max_attempts,
            )
            .values(
                status=JOB_STATUS_QUEUED,
                locked_by="",
                locked_at=None,
                run_after=now,
                updated_at=now,
            )
        )
        await db.commit()
        return int(result.rowcount or 0)
