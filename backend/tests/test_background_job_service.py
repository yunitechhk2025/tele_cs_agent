import asyncio
import unittest
import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, select, update

from app.database import AsyncSessionLocal, engine
from app.models import BackgroundJob
from app.services.background_job_service import (
    cancel_jobs_for_entity,
    claim_due_jobs,
    enqueue_job,
    mark_failed_or_retry,
    mark_succeeded,
    requeue_stale_jobs,
)


class BackgroundJobServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loop = asyncio.new_event_loop()

    @classmethod
    def tearDownClass(cls):
        cls.loop.run_until_complete(engine.dispose())
        cls.loop.close()

    def run_async(self, coro):
        return self.loop.run_until_complete(coro)

    def setUp(self):
        self.prefix = f"test-job-{uuid.uuid4()}"

    def tearDown(self):
        self.run_async(self._cleanup())

    async def _cleanup(self):
        async with AsyncSessionLocal() as db:
            await db.execute(delete(BackgroundJob).where(BackgroundJob.dedupe_key.like(f"{self.prefix}%")))
            await db.commit()

    def test_enqueue_claim_and_dedupe_prevent_duplicate_execution(self):
        self.run_async(self._test_enqueue_claim_and_dedupe_prevent_duplicate_execution())

    async def _test_enqueue_claim_and_dedupe_prevent_duplicate_execution(self):
        dedupe_key = f"{self.prefix}:scene:101"

        first = await enqueue_job(
            job_type="scene_generation",
            entity_type="scene_generation_record",
            entity_id=101,
            dedupe_key=dedupe_key,
            payload={"record_id": 101},
            max_attempts=2,
        )
        second = await enqueue_job(
            job_type="scene_generation",
            entity_type="scene_generation_record",
            entity_id=101,
            dedupe_key=dedupe_key,
            payload={"record_id": 101},
            max_attempts=2,
        )

        self.assertEqual(first.id, second.id)

        claimed = await claim_due_jobs("worker-a", limit=5)
        claimed_ids = [job.id for job in claimed if job.dedupe_key == dedupe_key]
        self.assertEqual(claimed_ids, [first.id])
        claimed_job = next(job for job in claimed if job.id == first.id)
        self.assertEqual(claimed_job.status, "running")
        self.assertEqual(claimed_job.locked_by, "worker-a")
        self.assertEqual(claimed_job.attempts, 1)

        claimed_again = await claim_due_jobs("worker-b", limit=5)
        self.assertNotIn(first.id, [job.id for job in claimed_again])

        done = await mark_succeeded(first.id)
        self.assertEqual(done.status, "succeeded")
        self.assertIsNotNone(done.finished_at)

    def test_failed_jobs_retry_then_fail_after_max_attempts(self):
        self.run_async(self._test_failed_jobs_retry_then_fail_after_max_attempts())

    async def _test_failed_jobs_retry_then_fail_after_max_attempts(self):
        dedupe_key = f"{self.prefix}:retry:202"
        job = await enqueue_job(
            job_type="scene_generation",
            entity_type="scene_generation_record",
            entity_id=202,
            dedupe_key=dedupe_key,
            payload={"record_id": 202},
            max_attempts=2,
        )

        first_claim = [item for item in await claim_due_jobs("worker-a", limit=5) if item.id == job.id][0]
        retry = await mark_failed_or_retry(first_claim.id, "temporary network error", retry_delay_seconds=0)
        self.assertEqual(retry.status, "queued")
        self.assertEqual(retry.attempts, 1)
        self.assertIn("temporary network error", retry.last_error)

        second_claim = [item for item in await claim_due_jobs("worker-a", limit=5) if item.id == job.id][0]
        failed = await mark_failed_or_retry(second_claim.id, "image model rejected request", retry_delay_seconds=0)
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.attempts, 2)
        self.assertIsNotNone(failed.finished_at)
        self.assertIn("image model rejected request", failed.last_error)

    def test_stale_running_jobs_are_requeued(self):
        self.run_async(self._test_stale_running_jobs_are_requeued())

    async def _test_stale_running_jobs_are_requeued(self):
        dedupe_key = f"{self.prefix}:stale:303"
        job = await enqueue_job(
            job_type="scene_generation",
            entity_type="scene_generation_record",
            entity_id=303,
            dedupe_key=dedupe_key,
            payload={"record_id": 303},
            max_attempts=2,
        )
        claimed = [item for item in await claim_due_jobs("worker-a", limit=5) if item.id == job.id][0]

        async with AsyncSessionLocal() as db:
            await db.execute(
                update(BackgroundJob)
                .where(BackgroundJob.id == claimed.id)
                .values(locked_at=datetime.utcnow() - timedelta(minutes=20))
            )
            await db.commit()

        count = await requeue_stale_jobs(stale_after_seconds=900)
        self.assertGreaterEqual(count, 1)

        async with AsyncSessionLocal() as db:
            refreshed = await db.get(BackgroundJob, job.id)
        self.assertEqual(refreshed.status, "queued")
        self.assertEqual(refreshed.locked_by, "")
        self.assertIsNone(refreshed.locked_at)

    def test_cancel_jobs_for_entity_prevents_future_claim(self):
        self.run_async(self._test_cancel_jobs_for_entity_prevents_future_claim())

    async def _test_cancel_jobs_for_entity_prevents_future_claim(self):
        dedupe_key = f"{self.prefix}:cancel:404"
        job = await enqueue_job(
            job_type="pending_ai_autosend",
            entity_type="pending_ai_reply",
            entity_id=404,
            dedupe_key=dedupe_key,
            payload={"pending_ai_reply_id": 404},
            run_after=datetime.utcnow() + timedelta(seconds=60),
            max_attempts=5,
        )

        cancelled = await cancel_jobs_for_entity("pending_ai_reply", 404)
        self.assertEqual(cancelled, 1)

        claimed = await claim_due_jobs("worker-a", limit=5)
        self.assertNotIn(job.id, [item.id for item in claimed])


if __name__ == "__main__":
    unittest.main()
