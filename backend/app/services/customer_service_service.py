import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Conversation, ConversationStatus, Message, MessageRole, PendingAIReply, SystemSetting
from app.services import bot_manager

logger = logging.getLogger(__name__)

CUSTOMER_SERVICE_MODE_KEY = "customer_service_mode"
CUSTOMER_SERVICE_AUTO_SEND_SECONDS_KEY = "customer_service_auto_send_seconds"

CUSTOMER_SERVICE_MODES = {
    "ai_auto",
    "ai_assist",
    "human_only",
}

DEFAULT_CUSTOMER_SERVICE_MODE = "ai_auto"
DEFAULT_AUTO_SEND_SECONDS = 10

ACTIVE_PENDING_AI_REPLY_TASKS: dict[int, asyncio.Task[Any]] = {}


async def get_customer_service_settings() -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(SystemSetting).where(
                SystemSetting.key.in_([
                    CUSTOMER_SERVICE_MODE_KEY,
                    CUSTOMER_SERVICE_AUTO_SEND_SECONDS_KEY,
                ])
            )
        )
        raw = {row.key: row.value for row in rows.scalars().all()}

    mode = raw.get(CUSTOMER_SERVICE_MODE_KEY, DEFAULT_CUSTOMER_SERVICE_MODE) or DEFAULT_CUSTOMER_SERVICE_MODE
    if mode not in CUSTOMER_SERVICE_MODES:
        mode = DEFAULT_CUSTOMER_SERVICE_MODE
    try:
        auto_send_seconds = int(raw.get(CUSTOMER_SERVICE_AUTO_SEND_SECONDS_KEY, str(DEFAULT_AUTO_SEND_SECONDS)))
    except Exception:
        auto_send_seconds = DEFAULT_AUTO_SEND_SECONDS
    auto_send_seconds = max(1, min(auto_send_seconds, 600))
    return {
        "mode": mode,
        "auto_send_seconds": auto_send_seconds,
    }


async def save_customer_service_settings(mode: str, auto_send_seconds: int) -> dict[str, Any]:
    if mode not in CUSTOMER_SERVICE_MODES:
        raise ValueError(f"Unsupported customer service mode: {mode}")
    auto_send_seconds = max(1, min(int(auto_send_seconds), 600))
    async with AsyncSessionLocal() as db:
        for key, value in {
            CUSTOMER_SERVICE_MODE_KEY: mode,
            CUSTOMER_SERVICE_AUTO_SEND_SECONDS_KEY: str(auto_send_seconds),
        }.items():
            existing = await db.get(SystemSetting, key)
            if existing:
                existing.value = value
            else:
                db.add(SystemSetting(key=key, value=value))
        await db.commit()
    return {
        "mode": mode,
        "auto_send_seconds": auto_send_seconds,
    }


async def get_pending_ai_reply(conversation_id: int) -> PendingAIReply | None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(PendingAIReply).where(
                PendingAIReply.conversation_id == conversation_id,
                PendingAIReply.status == "pending",
            )
        )
        return result.scalar_one_or_none()


async def pause_pending_ai_reply(conversation_id: int) -> PendingAIReply | None:
    existing = await get_pending_ai_reply(conversation_id)
    if not existing:
        return None
    task = ACTIVE_PENDING_AI_REPLY_TASKS.pop(existing.id, None)
    if task:
        task.cancel()
    async with AsyncSessionLocal() as db:
        current = await db.get(PendingAIReply, existing.id)
        if not current or current.status != "pending":
            return current
        current.auto_send_paused = True
        current.error_message = ""
        await db.commit()
        await db.refresh(current)
        return current


async def cancel_pending_ai_reply(conversation_id: int) -> PendingAIReply | None:
    existing = await get_pending_ai_reply(conversation_id)
    if not existing:
        return None
    task = ACTIVE_PENDING_AI_REPLY_TASKS.pop(existing.id, None)
    if task:
        task.cancel()
    async with AsyncSessionLocal() as db:
        current = await db.get(PendingAIReply, existing.id)
        if not current or current.status != "pending":
            return current
        current.status = "cancelled"
        current.auto_send_paused = False
        current.error_message = ""
        conversation = await db.get(Conversation, current.conversation_id)
        if conversation and conversation.status == ConversationStatus.HUMAN_HANDLING:
            conversation.status = ConversationStatus.PENDING_HUMAN
        await db.commit()
        await db.refresh(current)
        return current


async def _send_pending_ai_reply_record(
    record_id: int,
    content_override: str | None = None,
    send_as_human_agent: bool = False,
) -> PendingAIReply | None:
    async with AsyncSessionLocal() as db:
        draft = await db.get(PendingAIReply, record_id)
        if not draft or draft.status != "pending":
            return draft

        conversation = await db.get(Conversation, draft.conversation_id)
        if not conversation:
            draft.status = "cancelled"
            await db.commit()
            return draft

        text = (content_override if content_override is not None else draft.draft_text).strip()
        if not text:
            draft.error_message = "Draft text is empty"
            await db.commit()
            return draft
        message_role = MessageRole.HUMAN_AGENT if send_as_human_agent else MessageRole.ASSISTANT

        if (conversation.telegram_chat_id or "").startswith("sim-"):
            db.add(Message(
                conversation_id=conversation.id,
                role=message_role,
                content=text,
                language=draft.language,
            ))
        else:
            bot_instance = None
            if conversation.bot_id:
                bot_instance = bot_manager.get_bot_instance(conversation.bot_id)
            if not bot_instance:
                bot_instance = bot_manager.get_any_bot_instance()
            if not bot_instance or not conversation.telegram_chat_id:
                draft.error_message = "Telegram bot not available"
                await db.commit()
                return draft
            try:
                await bot_instance.send_message(chat_id=int(conversation.telegram_chat_id), text=text)
            except Exception as exc:
                draft.error_message = str(exc)[:1000]
                await db.commit()
                logger.error("Failed to send pending AI reply %s: %s", record_id, exc, exc_info=True)
                return draft

            db.add(Message(
                conversation_id=conversation.id,
                role=message_role,
                content=text,
                language=draft.language,
            ))

        draft.final_text = text
        draft.sent_at = datetime.utcnow()
        draft.status = "sent"
        draft.auto_send_paused = False
        draft.error_message = ""
        conversation.status = ConversationStatus.ACTIVE
        await db.commit()
        await db.refresh(draft)
        return draft


async def send_pending_ai_reply(
    conversation_id: int,
    content_override: str | None = None,
    send_as_human_agent: bool = False,
) -> PendingAIReply | None:
    existing = await get_pending_ai_reply(conversation_id)
    if not existing:
        return None
    ACTIVE_PENDING_AI_REPLY_TASKS.pop(existing.id, None)
    return await _send_pending_ai_reply_record(
        existing.id,
        content_override=content_override,
        send_as_human_agent=send_as_human_agent,
    )


def _schedule_pending_ai_reply_task(record_id: int, auto_send_at: datetime) -> None:
    existing = ACTIVE_PENDING_AI_REPLY_TASKS.pop(record_id, None)
    if existing:
        existing.cancel()

    async def _job():
        try:
            delay = max(0.0, (auto_send_at - datetime.utcnow()).total_seconds())
            if delay > 0:
                await asyncio.sleep(delay)
            await _send_pending_ai_reply_record(record_id)
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Pending AI reply autosend failed for record %s", record_id)
        finally:
            ACTIVE_PENDING_AI_REPLY_TASKS.pop(record_id, None)

    ACTIVE_PENDING_AI_REPLY_TASKS[record_id] = asyncio.create_task(_job())


async def create_pending_ai_reply(
    conversation_id: int,
    draft_text: str,
    language: str,
) -> PendingAIReply:
    await cancel_pending_ai_reply(conversation_id)
    cfg = await get_customer_service_settings()
    auto_send_at = datetime.utcnow() + timedelta(seconds=cfg["auto_send_seconds"])

    async with AsyncSessionLocal() as db:
        conversation = await db.get(Conversation, conversation_id)
        if not conversation:
            raise RuntimeError(f"Conversation {conversation_id} not found")

        draft = PendingAIReply(
            conversation_id=conversation_id,
            draft_text=draft_text,
            language=language or "en",
            status="pending",
            auto_send_at=auto_send_at,
            auto_send_paused=False,
            error_message="",
        )
        db.add(draft)
        conversation.status = ConversationStatus.HUMAN_HANDLING
        await db.commit()
        await db.refresh(draft)

    _schedule_pending_ai_reply_task(draft.id, auto_send_at)
    return draft


async def dispatch_due_pending_ai_replies() -> int:
    now = datetime.utcnow()
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(PendingAIReply.id).where(
                PendingAIReply.status == "pending",
                PendingAIReply.auto_send_paused == False,
                PendingAIReply.auto_send_at <= now,
            )
        )
        due_ids = [row[0] for row in rows.all()]
    for record_id in due_ids:
        await _send_pending_ai_reply_record(record_id)
    return len(due_ids)


async def restore_pending_ai_reply_tasks() -> None:
    await dispatch_due_pending_ai_replies()
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(PendingAIReply).where(
                PendingAIReply.status == "pending",
                PendingAIReply.auto_send_paused == False,
            )
        )
        drafts = rows.scalars().all()
    for draft in drafts:
        _schedule_pending_ai_reply_task(draft.id, draft.auto_send_at)
