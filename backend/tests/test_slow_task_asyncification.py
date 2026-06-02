import asyncio
import time
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from sqlalchemy import delete, select, update

from app.database import AsyncSessionLocal, engine
from app.models import (
    BackgroundJob,
    Conversation,
    ConversationOutboundEvent,
    Message,
    PendingAIReply,
    ProductEntry,
    SceneGenerationRecord,
)
from app.services.background_job_service import claim_due_jobs
from app.services.customer_service_service import (
    cancel_pending_ai_reply,
    create_pending_ai_reply,
    pause_pending_ai_reply,
    send_pending_ai_reply,
)
from app.services.scene_service import cancel_scene_generation_task, start_scene_generation
from app.worker import process_background_job


class SlowTaskAsyncificationTests(unittest.TestCase):
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
        self.prefix = f"slow-task-{uuid.uuid4()}"
        self.created_conversation_ids: list[int] = []
        self.created_product_ids: list[int] = []
        self.created_scene_ids: list[int] = []
        self.created_pending_ids: list[int] = []

    def tearDown(self):
        self.run_async(self._cleanup())

    async def _cleanup(self):
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(BackgroundJob).where(BackgroundJob.dedupe_key.like(f"{self.prefix}%"))
            )
            if self.created_scene_ids:
                await db.execute(
                    delete(SceneGenerationRecord).where(
                        SceneGenerationRecord.id.in_(self.created_scene_ids)
                    )
                )
            if self.created_pending_ids:
                await db.execute(
                    delete(PendingAIReply).where(PendingAIReply.id.in_(self.created_pending_ids))
                )
            if self.created_conversation_ids:
                await db.execute(
                    delete(ConversationOutboundEvent).where(
                        ConversationOutboundEvent.conversation_id.in_(self.created_conversation_ids)
                    )
                )
                await db.execute(
                    delete(Message).where(
                        Message.conversation_id.in_(self.created_conversation_ids)
                    )
                )
                await db.execute(
                    delete(Conversation).where(Conversation.id.in_(self.created_conversation_ids))
                )
            if self.created_product_ids:
                await db.execute(
                    delete(ProductEntry).where(ProductEntry.id.in_(self.created_product_ids))
                )
            await db.commit()

    async def _create_product(self) -> ProductEntry:
        async with AsyncSessionLocal() as db:
            product = ProductEntry(
                brand="test",
                product_id_ext=f"{self.prefix}-product",
                product_name="测试沙发",
                space="客厅",
                style="现代",
            )
            db.add(product)
            await db.commit()
            await db.refresh(product)
            self.created_product_ids.append(product.id)
            return product

    async def _create_conversation(self) -> Conversation:
        async with AsyncSessionLocal() as db:
            conversation = Conversation(
                telegram_chat_id=f"sim-{self.prefix}",
                telegram_user_id=f"user-{self.prefix}",
                language="zh-Hans",
            )
            db.add(conversation)
            await db.commit()
            await db.refresh(conversation)
            self.created_conversation_ids.append(conversation.id)
            return conversation

    def test_start_scene_generation_returns_pending_record_and_enqueues_job_without_running_model(
        self,
    ):
        self.run_async(
            self._test_start_scene_generation_returns_pending_record_and_enqueues_job_without_running_model()
        )

    async def _test_start_scene_generation_returns_pending_record_and_enqueues_job_without_running_model(
        self,
    ):
        product = await self._create_product()

        async def slow_model(**_kwargs):
            await asyncio.sleep(60)

        with patch(
            "app.services.scene_service._run_scene_generation_for_record", side_effect=slow_model
        ) as run_scene:
            started_at = time.monotonic()
            record = await start_scene_generation(
                primary_product=product,
                all_products=[{"id": product.id, "name": product.product_name}],
                user_request="生成客厅效果图",
                scene_name="客厅",
                style_hint="现代",
                allow_reuse=False,
                dedupe_prefix=self.prefix,
            )
            elapsed = time.monotonic() - started_at
            await asyncio.sleep(0.05)

        self.created_scene_ids.append(record.id)
        self.assertEqual(record.status, "pending")
        self.assertLess(elapsed, 2)
        self.assertEqual(run_scene.await_count, 0)

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(BackgroundJob).where(
                    BackgroundJob.job_type == "scene_generation",
                    BackgroundJob.entity_type == "scene_generation_record",
                    BackgroundJob.entity_id == record.id,
                )
            )
            job = result.scalar_one()
        self.assertEqual(job.status, "queued")
        self.assertEqual(job.max_attempts, 2)

    def test_scene_generation_job_is_claimed_once_across_workers(self):
        self.run_async(self._test_scene_generation_job_is_claimed_once_across_workers())

    async def _test_scene_generation_job_is_claimed_once_across_workers(self):
        product = await self._create_product()
        record = await start_scene_generation(
            primary_product=product,
            all_products=[{"id": product.id, "name": product.product_name}],
            user_request="生成客厅效果图",
            scene_name="客厅",
            style_hint="现代",
            allow_reuse=False,
            dedupe_prefix=self.prefix,
        )
        self.created_scene_ids.append(record.id)

        first_claim = await claim_due_jobs("worker-a", limit=5)
        second_claim = await claim_due_jobs("worker-b", limit=5)

        first_ids = [job.entity_id for job in first_claim if job.job_type == "scene_generation"]
        second_ids = [job.entity_id for job in second_claim if job.job_type == "scene_generation"]
        self.assertIn(record.id, first_ids)
        self.assertNotIn(record.id, second_ids)

    def test_worker_processes_scene_generation_job_with_retry_then_success(self):
        self.run_async(self._test_worker_processes_scene_generation_job_with_retry_then_success())

    async def _test_worker_processes_scene_generation_job_with_retry_then_success(self):
        product = await self._create_product()
        record = await start_scene_generation(
            primary_product=product,
            all_products=[{"id": product.id, "name": product.product_name}],
            user_request="生成客厅效果图",
            scene_name="客厅",
            style_hint="现代",
            allow_reuse=False,
            dedupe_prefix=self.prefix,
        )
        self.created_scene_ids.append(record.id)
        job = [
            item
            for item in await claim_due_jobs("worker-a", limit=5)
            if item.entity_id == record.id
        ][0]

        async def fail_once(**_kwargs):
            raise RuntimeError("temporary image failure")

        with patch("app.worker._run_scene_generation_for_record", side_effect=fail_once):
            await process_background_job(job)

        async with AsyncSessionLocal() as db:
            retried = await db.get(BackgroundJob, job.id)
        self.assertEqual(retried.status, "queued")
        self.assertEqual(retried.attempts, 1)
        self.assertIn("temporary image failure", retried.last_error)

        async with AsyncSessionLocal() as db:
            await db.execute(
                update(BackgroundJob)
                .where(BackgroundJob.id == job.id)
                .values(run_after=datetime.utcnow())
            )
            await db.commit()

        retry_job = [
            item
            for item in await claim_due_jobs("worker-a", limit=5)
            if item.entity_id == record.id
        ][0]

        async def succeed(**kwargs):
            async with AsyncSessionLocal() as db:
                current = await db.get(SceneGenerationRecord, kwargs["record_id"])
                current.status = "completed"
                current.output_paths_json = '["uploads/scene/test.png"]'
                current.result_json = '{"image_urls":["http://example.test/test.png"]}'
                await db.commit()
                await db.refresh(current)
                return current

        with patch("app.worker._run_scene_generation_for_record", side_effect=succeed):
            await process_background_job(retry_job)

        async with AsyncSessionLocal() as db:
            succeeded = await db.get(BackgroundJob, job.id)
            completed_record = await db.get(SceneGenerationRecord, record.id)
        self.assertEqual(succeeded.status, "succeeded")
        self.assertEqual(completed_record.status, "completed")

    def test_scene_generation_job_marks_record_failed_after_max_attempts(self):
        self.run_async(self._test_scene_generation_job_marks_record_failed_after_max_attempts())

    async def _test_scene_generation_job_marks_record_failed_after_max_attempts(self):
        product = await self._create_product()
        record = await start_scene_generation(
            primary_product=product,
            all_products=[{"id": product.id, "name": product.product_name}],
            user_request="生成客厅效果图",
            scene_name="客厅",
            style_hint="现代",
            allow_reuse=False,
            dedupe_prefix=self.prefix,
        )
        self.created_scene_ids.append(record.id)

        for _ in range(2):
            job = [
                item
                for item in await claim_due_jobs("worker-a", limit=5)
                if item.entity_id == record.id
            ][0]
            with patch(
                "app.worker._run_scene_generation_for_record",
                side_effect=RuntimeError("permanent image failure"),
            ):
                await process_background_job(job)
            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(BackgroundJob)
                    .where(BackgroundJob.id == job.id)
                    .values(run_after=datetime.utcnow())
                )
                await db.commit()

        async with AsyncSessionLocal() as db:
            failed_job = await db.get(BackgroundJob, job.id)
            failed_record = await db.get(SceneGenerationRecord, record.id)
        self.assertEqual(failed_job.status, "failed")
        self.assertEqual(failed_job.attempts, 2)
        self.assertEqual(failed_record.status, "failed")
        self.assertIn("permanent image failure", failed_record.error_message)

    def test_cancel_pending_scene_generation_cancels_background_job(self):
        self.run_async(self._test_cancel_pending_scene_generation_cancels_background_job())

    async def _test_cancel_pending_scene_generation_cancels_background_job(self):
        product = await self._create_product()
        record = await start_scene_generation(
            primary_product=product,
            all_products=[{"id": product.id, "name": product.product_name}],
            user_request="生成客厅效果图",
            scene_name="客厅",
            style_hint="现代",
            allow_reuse=False,
            dedupe_prefix=self.prefix,
        )
        self.created_scene_ids.append(record.id)

        cancelled = await cancel_scene_generation_task(record.id)
        self.assertTrue(cancelled)

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(BackgroundJob).where(
                    BackgroundJob.job_type == "scene_generation",
                    BackgroundJob.entity_id == record.id,
                )
            )
            job = result.scalar_one()
        self.assertEqual(job.status, "cancelled")

        claimed = await claim_due_jobs("worker-a", limit=5)
        self.assertNotIn(job.id, [item.id for item in claimed])

    def test_pending_ai_reply_autosend_uses_persistent_job_and_honors_pause_cancel_and_manual_send(
        self,
    ):
        self.run_async(
            self._test_pending_ai_reply_autosend_uses_persistent_job_and_honors_pause_cancel_and_manual_send()
        )

    async def _test_pending_ai_reply_autosend_uses_persistent_job_and_honors_pause_cancel_and_manual_send(
        self,
    ):
        conversation = await self._create_conversation()

        draft = await create_pending_ai_reply(
            conversation.id, "自动发送草稿", "zh-Hans", dedupe_prefix=self.prefix
        )
        self.created_pending_ids.append(draft.id)

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(BackgroundJob).where(
                    BackgroundJob.job_type == "pending_ai_autosend",
                    BackgroundJob.entity_type == "pending_ai_reply",
                    BackgroundJob.entity_id == draft.id,
                )
            )
            job = result.scalar_one()
        self.assertEqual(job.status, "queued")
        self.assertGreaterEqual(job.run_after, datetime.utcnow() - timedelta(seconds=1))

        paused = await pause_pending_ai_reply(conversation.id)
        self.assertTrue(paused.auto_send_paused)
        async with AsyncSessionLocal() as db:
            paused_job = await db.get(BackgroundJob, job.id)
        self.assertEqual(paused_job.status, "cancelled")

        draft = await create_pending_ai_reply(
            conversation.id, "取消草稿", "zh-Hans", dedupe_prefix=self.prefix
        )
        self.created_pending_ids.append(draft.id)
        cancelled = await cancel_pending_ai_reply(conversation.id)
        self.assertEqual(cancelled.status, "cancelled")

        draft = await create_pending_ai_reply(
            conversation.id, "人工提前发送", "zh-Hans", dedupe_prefix=self.prefix
        )
        self.created_pending_ids.append(draft.id)
        with patch("app.services.bot_manager.get_any_bot_instance", return_value=None):
            sent = await send_pending_ai_reply(conversation.id)
        self.assertIn(sent.status, {"pending", "sent"})


if __name__ == "__main__":
    unittest.main()
