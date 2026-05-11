import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import (
    Conversation,
    ConversationOutboundEvent,
    ConversationStatus,
    Message,
    MessageRole,
    PendingAIReply,
    SceneGenerationRecord,
    SystemSetting,
)
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


def _load_payload(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


async def _append_outbound_event(
    db,
    conversation_id: int,
    role: str,
    event_type: str,
    *,
    text: str = "",
    caption: str = "",
    url: str = "",
    filename: str = "",
    parse_mode: str | None = None,
) -> None:
    db.add(ConversationOutboundEvent(
        conversation_id=conversation_id,
        role=role,
        event_type=event_type,
        text=text,
        caption=caption,
        url=url,
        filename=filename,
        parse_mode=parse_mode,
    ))


async def _send_product_recommendation_payload(
    db,
    conversation: Conversation,
    draft: PendingAIReply,
    payload: dict[str, Any],
    message_role: MessageRole,
) -> str | None:
    intro_text = (payload.get("intro_text") or "").strip()
    followup_text = (payload.get("followup_text") or "").strip()
    cards = payload.get("cards") or []
    role_value = message_role.value
    is_simulator = (conversation.telegram_chat_id or "").startswith("sim-")

    bot_instance = None
    if not is_simulator:
        if conversation.bot_id:
            bot_instance = bot_manager.get_bot_instance(conversation.bot_id)
        if not bot_instance:
            bot_instance = bot_manager.get_any_bot_instance()
        if not bot_instance or not conversation.telegram_chat_id:
            draft.error_message = "Telegram bot not available"
            await db.commit()
            return None

    if intro_text:
        if is_simulator:
            db.add(Message(conversation_id=conversation.id, role=message_role, content=intro_text, language=draft.language))
        else:
            await bot_instance.send_message(chat_id=int(conversation.telegram_chat_id), text=intro_text)
            db.add(Message(conversation_id=conversation.id, role=message_role, content=intro_text, language=draft.language))

    for card in cards:
        caption = (card.get("caption") or "").strip()
        image_path = (card.get("image_path") or "").strip()
        image_url = (card.get("image_url") or "").strip()
        parse_mode = card.get("parse_mode") or "Markdown"
        if is_simulator:
            if image_url:
                await _append_outbound_event(
                    db,
                    conversation.id,
                    role_value,
                    "photo",
                    caption=caption,
                    url=image_url,
                    parse_mode=parse_mode,
                )
            elif caption:
                db.add(Message(conversation_id=conversation.id, role=message_role, content=caption, language=draft.language))
        else:
            if image_path:
                full = os.path.join("/app", image_path)
                if os.path.exists(full):
                    with open(full, "rb") as fh:
                        await bot_instance.send_photo(
                            chat_id=int(conversation.telegram_chat_id),
                            photo=fh,
                            caption=caption or None,
                            parse_mode=parse_mode,
                        )
                    await _append_outbound_event(
                        db,
                        conversation.id,
                        role_value,
                        "photo",
                        caption=caption,
                        url=image_url,
                        parse_mode=parse_mode,
                    )
                    continue
            if caption:
                await bot_instance.send_message(
                    chat_id=int(conversation.telegram_chat_id),
                    text=caption,
                    parse_mode=parse_mode,
                )

    if followup_text:
        if is_simulator:
            db.add(Message(conversation_id=conversation.id, role=message_role, content=followup_text, language=draft.language))
        else:
            await bot_instance.send_message(chat_id=int(conversation.telegram_chat_id), text=followup_text)
            db.add(Message(conversation_id=conversation.id, role=message_role, content=followup_text, language=draft.language))

    scene_state = payload.get("scene_state") or {}
    if scene_state:
        from app.telegram_bot import save_scene_state

        await save_scene_state(
            conversation_id=conversation.id,
            primary_product_id=scene_state.get("primary_product_id"),
            recommended_product_ids=[int(x) for x in (scene_state.get("recommended_product_ids") or [])],
            suggested_scene=scene_state.get("suggested_scene") or "",
            suggested_style=scene_state.get("suggested_style") or "",
            pending_confirmation=bool(scene_state.get("pending_confirmation")),
            reply_language=scene_state.get("reply_language") or draft.language,
            last_customer_request=scene_state.get("last_customer_request") or "",
            active_topic=scene_state.get("active_topic") or "",
            active_product_id=scene_state.get("active_product_id"),
            preferences=scene_state.get("preferences") or None,
        )
    return draft.draft_text


async def _send_scene_result_payload(
    db,
    conversation: Conversation,
    draft: PendingAIReply,
    payload: dict[str, Any],
    message_role: MessageRole,
) -> str | None:
    intro_text = (payload.get("intro_text") or "").strip()
    links_text = (payload.get("links_text") or "").strip()
    image_urls = payload.get("image_urls") or []
    output_paths = payload.get("output_paths") or []
    parse_mode = payload.get("links_parse_mode") or "Markdown"
    role_value = message_role.value
    is_simulator = (conversation.telegram_chat_id or "").startswith("sim-")

    bot_instance = None
    if not is_simulator:
        if conversation.bot_id:
            bot_instance = bot_manager.get_bot_instance(conversation.bot_id)
        if not bot_instance:
            bot_instance = bot_manager.get_any_bot_instance()
        if not bot_instance or not conversation.telegram_chat_id:
            draft.error_message = "Telegram bot not available"
            await db.commit()
            return None

    if intro_text:
        if is_simulator:
            db.add(Message(conversation_id=conversation.id, role=message_role, content=intro_text, language=draft.language))
        else:
            await bot_instance.send_message(chat_id=int(conversation.telegram_chat_id), text=intro_text)
            db.add(Message(conversation_id=conversation.id, role=message_role, content=intro_text, language=draft.language))

    for index, image_url in enumerate(image_urls):
        if is_simulator:
            await _append_outbound_event(
                db,
                conversation.id,
                role_value,
                "photo",
                url=image_url,
            )
            continue
        rel_path = output_paths[index] if index < len(output_paths) else ""
        if not rel_path:
            continue
        full = os.path.join("/app", rel_path)
        if not os.path.exists(full):
            continue
        with open(full, "rb") as fh:
            await bot_instance.send_photo(chat_id=int(conversation.telegram_chat_id), photo=fh)
        await _append_outbound_event(
            db,
            conversation.id,
            role_value,
            "photo",
            url=image_url,
        )

    if links_text:
        if is_simulator:
            db.add(Message(conversation_id=conversation.id, role=message_role, content=links_text, language=draft.language))
        else:
            await bot_instance.send_message(
                chat_id=int(conversation.telegram_chat_id),
                text=links_text,
                parse_mode=parse_mode,
                disable_web_page_preview=True,
            )
            db.add(Message(conversation_id=conversation.id, role=message_role, content=links_text, language=draft.language))

    record_id = payload.get("record_id")
    if record_id:
        record = await db.get(SceneGenerationRecord, int(record_id))
        if record:
            record.deferred_delivery = False

    state_action = (payload.get("scene_state_action") or "").strip()
    state_payload = payload.get("scene_state_payload") or {}
    if state_action == "clear":
        from app.telegram_bot import clear_scene_state
        await clear_scene_state(conversation.id)
    elif state_action == "save":
        from app.telegram_bot import save_scene_state
        await save_scene_state(
            conversation_id=conversation.id,
            primary_product_id=state_payload.get("primary_product_id"),
            recommended_product_ids=[int(x) for x in (state_payload.get("recommended_product_ids") or [])],
            suggested_scene=state_payload.get("suggested_scene") or "",
            suggested_style=state_payload.get("suggested_style") or "",
            pending_confirmation=bool(state_payload.get("pending_confirmation")),
            reply_language=state_payload.get("reply_language") or draft.language,
            last_customer_request=state_payload.get("last_customer_request") or "",
            active_topic=state_payload.get("active_topic") or "",
            active_product_id=state_payload.get("active_product_id"),
            preferences=state_payload.get("preferences") or None,
        )
    return draft.draft_text


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
        payload = _load_payload(draft.payload_json)
        if draft.content_kind == "text" and not text:
            draft.error_message = "Draft text is empty"
            await db.commit()
            return draft
        message_role = MessageRole.HUMAN_AGENT if send_as_human_agent else MessageRole.ASSISTANT
        try:
            if draft.content_kind == "product_recommendation":
                text = await _send_product_recommendation_payload(db, conversation, draft, payload, message_role) or text
            elif draft.content_kind == "scene_result":
                text = await _send_scene_result_payload(db, conversation, draft, payload, message_role) or text
            else:
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
                    await bot_instance.send_message(chat_id=int(conversation.telegram_chat_id), text=text)
                    db.add(Message(
                        conversation_id=conversation.id,
                        role=message_role,
                        content=text,
                        language=draft.language,
                    ))
        except Exception as exc:
            draft.error_message = str(exc)[:1000]
            await db.commit()
            logger.error("Failed to send pending AI reply %s: %s", record_id, exc, exc_info=True)
            return draft

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
    return await create_pending_ai_delivery(
        conversation_id=conversation_id,
        draft_text=draft_text,
        language=language,
        content_kind="text",
        payload=None,
    )


async def create_pending_ai_delivery(
    conversation_id: int,
    draft_text: str,
    language: str,
    *,
    content_kind: str = "text",
    payload: dict[str, Any] | None = None,
) -> PendingAIReply:
    cfg = await get_customer_service_settings()
    auto_send_at = datetime.utcnow() + timedelta(seconds=cfg["auto_send_seconds"])

    async with AsyncSessionLocal() as db:
        conversation = await db.get(Conversation, conversation_id)
        if not conversation:
            raise RuntimeError(f"Conversation {conversation_id} not found")
        result = await db.execute(
            select(PendingAIReply).where(PendingAIReply.conversation_id == conversation_id)
        )
        draft = result.scalar_one_or_none()
        if not draft:
            draft = PendingAIReply(conversation_id=conversation_id)
            db.add(draft)
        draft.draft_text = draft_text
        draft.final_text = ""
        draft.language = language or "en"
        draft.content_kind = content_kind or "text"
        draft.payload_json = json.dumps(payload or {}, ensure_ascii=False)
        draft.status = "pending"
        draft.auto_send_at = auto_send_at
        draft.auto_send_paused = False
        draft.sent_at = None
        draft.error_message = ""
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
