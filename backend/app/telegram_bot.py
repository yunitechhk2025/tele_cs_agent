import asyncio
import logging
from io import BytesIO
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, constants
from telegram.ext import ContextTypes
from sqlalchemy import select
from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import Conversation, Message, FileEntry, TelegramBot, ConversationStatus, MessageRole
from app.services.llm_service import (
    detect_language, check_is_quote_related, check_file_request, generate_response,
    might_want_product_image, match_product_image_files,
)
from app.services.rag_service import search_knowledge_for_bot

logger = logging.getLogger(__name__)
settings = get_settings()

WELCOME_MESSAGES = {
    "zh": "您好！👋 我是智能客服助手。有什么可以帮助您的吗？",
    "en": "Hello! 👋 I'm your customer service assistant. How can I help you?",
    "ja": "こんにちは！👋 カスタマーサービスアシスタントです。何かお手伝いできますか？",
    "ko": "안녕하세요! 👋 고객 서비스 어시스턴트입니다. 무엇을 도와드릴까요?",
    "es": "¡Hola! 👋 Soy su asistente de servicio al cliente. ¿En qué puedo ayudarle?",
    "fr": "Bonjour ! 👋 Je suis votre assistant de service client. Comment puis-je vous aider ?",
    "de": "Hallo! 👋 Ich bin Ihr Kundenservice-Assistent. Wie kann ich Ihnen helfen?",
    "ru": "Здравствуйте! 👋 Я ваш ассистент службы поддержки. Чем могу помочь?",
    "ar": "مرحبا! 👋 أنا مساعد خدمة العملاء. كيف يمكنني مساعدتك؟",
    "pt": "Olá! 👋 Sou seu assistente de atendimento ao cliente. Como posso ajudá-lo?",
}

HANDOFF_MESSAGES = {
    "zh": "您的咨询涉及报价，我已为您转接人工客服，请稍候。",
    "en": "Your inquiry involves pricing. I've connected you to a human agent. Please wait.",
    "ja": "お見積もりに関するお問い合わせですので、担当者にお繋ぎします。少々お待ちください。",
    "ko": "견적 관련 문의이므로 담당자에게 연결해 드리겠습니다. 잠시만 기다려 주세요.",
    "es": "Su consulta involucra cotización. Le he conectado con un agente humano. Por favor espere.",
    "fr": "Votre demande concerne un devis. Je vous ai mis en relation avec un agent. Veuillez patienter.",
}

PRODUCT_IMAGE_ACK = {
    "zh": "好的，已为您发送商品图片。",
    "en": "Here's the product image.",
    "ja": "商品画像をお送りします。",
    "ko": "상품 이미지를 보내드립니다.",
    "es": "Aquí tiene la imagen del producto.",
    "fr": "Voici l'image du produit.",
}


async def keep_typing(chat_id: int, bot, stop_event: asyncio.Event):
    """Continuously send 'typing...' action until stop_event is set."""
    while not stop_event.is_set():
        try:
            await bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
        except Exception:
            break
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=4.0)
            break
        except asyncio.TimeoutError:
            pass


async def get_bot_config(bot_id: int) -> TelegramBot | None:
    async with AsyncSessionLocal() as db:
        return await db.get(TelegramBot, bot_id)


async def get_or_create_conversation(
    bot_id: int, chat_id: str, user_id: str, username: str | None,
    first_name: str | None, last_name: str | None,
    language: str = "en",
) -> Conversation:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Conversation)
            .where(
                Conversation.bot_id == bot_id,
                Conversation.telegram_chat_id == chat_id,
                Conversation.status.in_([
                    ConversationStatus.ACTIVE,
                    ConversationStatus.PENDING_HUMAN,
                    ConversationStatus.HUMAN_HANDLING,
                ]),
            )
            .order_by(Conversation.created_at.desc())
        )
        conversation = result.scalar_one_or_none()
        if not conversation:
            conversation = Conversation(
                bot_id=bot_id,
                telegram_chat_id=chat_id, telegram_user_id=user_id,
                username=username, first_name=first_name, last_name=last_name,
                language=language,
            )
            db.add(conversation)
            await db.commit()
            await db.refresh(conversation)
        return conversation


async def save_message(
    conversation_id: int,
    role: MessageRole,
    content: str,
    language: str | None = None,
    attachment_file_id: int | None = None,
):
    async with AsyncSessionLocal() as db:
        msg = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            language=language,
            attachment_file_id=attachment_file_id,
        )
        db.add(msg)
        await db.commit()


async def get_chat_history(conversation_id: int) -> list[dict]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Message).where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc()).limit(20)
        )
        messages = result.scalars().all()
        return [
            {"role": "user" if m.role == MessageRole.USER else "assistant", "content": m.content}
            for m in reversed(messages)
        ]


async def get_all_file_entries() -> list[dict]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(FileEntry).order_by(FileEntry.created_at.desc()))
        files = result.scalars().all()
        return [
            {
                "id": f.id,
                "name": f.original_name,
                "description": f.description,
                "tags": f.tags,
                "mime_type": f.mime_type or "",
                "category": f.category or "",
            }
            for f in files
        ]


async def get_file_entry_by_id(file_id: int) -> FileEntry | None:
    async with AsyncSessionLocal() as db:
        return await db.get(FileEntry, file_id)


async def send_files_to_user(chat_id: str, file_ids: list[int], bot):
    for fid in file_ids:
        entry = await get_file_entry_by_id(fid)
        if not entry:
            continue
        try:
            with open(entry.file_path, "rb") as f:
                await bot.send_document(
                    chat_id=int(chat_id),
                    document=f,
                    filename=entry.original_name,
                    caption=entry.description[:200] if entry.description else None,
                )
        except Exception as e:
            logger.error(f"Failed to send file {entry.original_name}: {e}")


async def send_one_product_image_file(chat_id: str, file_id: int, bot):
    """Send a single file as photo if image/*, else as document."""
    entry = await get_file_entry_by_id(file_id)
    if not entry:
        return
    mt = (entry.mime_type or "").lower()
    try:
        with open(entry.file_path, "rb") as f:
            data = f.read()
        bio = BytesIO(data)
        bio.name = entry.original_name
        cap = (entry.description[:1024] if entry.description else None)
        if mt.startswith("image/"):
            bio.seek(0)
            await bot.send_photo(
                chat_id=int(chat_id),
                photo=bio,
                caption=cap,
            )
        else:
            bio.seek(0)
            await bot.send_document(
                chat_id=int(chat_id),
                document=bio,
                filename=entry.original_name,
                caption=entry.description[:200] if entry.description else None,
            )
        logger.info(f"Sent product file {entry.original_name} to chat {chat_id}")
    except Exception as e:
        logger.error(f"Failed to send product image file {entry.original_name}: {e}", exc_info=True)


async def notify_admin(bot_id: int, conversation: Conversation, user_message: str, bot, is_followup: bool = False):
    bot_config = await get_bot_config(bot_id)
    admin_chat_id = bot_config.admin_chat_id if bot_config else settings.ADMIN_CHAT_ID
    if not admin_chat_id:
        logger.warning(f"[Bot {bot_id}] admin_chat_id not configured, cannot notify admin")
        return

    customer_name = " ".join(
        filter(None, [conversation.first_name, conversation.last_name])
    ) or conversation.username or "Unknown"
    username_display = f"@{conversation.username}" if conversation.username else "无"

    dashboard_url = f"{settings.FRONTEND_URL}/conversations/{conversation.id}"

    if is_followup:
        title = "📩 客户追加消息"
        action_line = "⚡ <b>客户仍在等待人工回复，请尽快处理！</b>"
    else:
        title = "🚨🚨🚨 客户询价提醒 🚨🚨🚨"
        action_line = "⚡ <b>该客户正在咨询报价/定价相关内容，请尽快处理！</b>"

    text = (
        f"<b>{title}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 <b>客户姓名:</b> {customer_name}\n"
        f"📱 <b>用户名:</b> {username_display}\n"
        f"🆔 <b>Chat ID:</b> <code>{conversation.telegram_chat_id}</code>\n"
        f"🤖 <b>来源 Bot:</b> {bot_config.name if bot_config else 'Unknown'}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💬 <b>客户消息:</b>\n"
        f"<blockquote>{user_message[:500]}</blockquote>\n\n"
        f"{action_line}\n\n"
        f"📋 后台地址: {dashboard_url}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )

    buttons = []
    if dashboard_url.startswith("https://"):
        buttons.append([InlineKeyboardButton("📋 进入后台处理", url=dashboard_url)])
    buttons.append([InlineKeyboardButton("💬 直接联系客户", url=f"tg://user?id={conversation.telegram_user_id}")])
    keyboard = InlineKeyboardMarkup(buttons)

    try:
        await bot.send_message(
            chat_id=admin_chat_id,
            text=text,
            parse_mode="HTML",
            reply_markup=keyboard,
            disable_notification=False,
        )
        logger.info(f"[Bot {bot_id}] Admin notified at chat_id={admin_chat_id} for conversation {conversation.id}")
    except Exception as e:
        logger.error(f"[Bot {bot_id}] Failed to notify admin at chat_id={admin_chat_id}: {e}", exc_info=True)


def make_start_handler(bot_id: int):
    async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        chat_id = str(update.effective_chat.id)
        user_lang = user.language_code[:2] if user.language_code else "en"
        await get_or_create_conversation(
            bot_id=bot_id, chat_id=chat_id, user_id=str(user.id),
            username=user.username, first_name=user.first_name, last_name=user.last_name,
            language=user_lang,
        )

        bot_config = await get_bot_config(bot_id)
        if bot_config and bot_config.welcome_message:
            await update.message.reply_text(bot_config.welcome_message)
        else:
            welcome = WELCOME_MESSAGES.get(user_lang, WELCOME_MESSAGES["en"])
            await update.message.reply_text(welcome)

    return handle_start


def make_message_handler(bot_id: int):
    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        chat_id = str(update.effective_chat.id)
        user_message = update.message.text
        logger.info(f"[Bot {bot_id}] Received message from chat {chat_id}: {user_message[:80]}")

        user_lang = user.language_code[:2] if user.language_code else "en"
        try:
            conversation = await get_or_create_conversation(
                bot_id=bot_id, chat_id=chat_id, user_id=str(user.id),
                username=user.username, first_name=user.first_name, last_name=user.last_name,
                language=user_lang,
            )
            logger.info(f"[Bot {bot_id}] Conversation {conversation.id}, status={conversation.status}")
        except Exception as e:
            logger.error(f"[Bot {bot_id}] Failed to get/create conversation: {e}", exc_info=True)
            await update.message.reply_text("系统错误，请稍后再试。")
            return

        try:
            language = await detect_language(user_message)
            logger.info(f"[Bot {bot_id}] Detected language: {language}")
        except Exception as e:
            logger.error(f"[Bot {bot_id}] Language detection failed: {e}", exc_info=True)
            language = "en"

        try:
            async with AsyncSessionLocal() as db:
                conv = await db.get(Conversation, conversation.id)
                if conv:
                    conv.language = language
                    await db.commit()
        except Exception as e:
            logger.error(f"[Bot {bot_id}] Failed to update language: {e}", exc_info=True)

        await save_message(conversation.id, MessageRole.USER, user_message, language)

        async with AsyncSessionLocal() as db:
            fresh_conv = await db.get(Conversation, conversation.id)
            current_status = fresh_conv.status if fresh_conv else conversation.status

        stop_typing = asyncio.Event()
        typing_task = asyncio.create_task(
            keep_typing(int(chat_id), context.bot, stop_typing)
        )

        try:
            is_quote = await check_is_quote_related(user_message)
            logger.info(f"[Bot {bot_id}] Quote related: {is_quote}")
            if is_quote:
                async with AsyncSessionLocal() as db:
                    conv = await db.get(Conversation, conversation.id)
                    if conv:
                        conv.status = ConversationStatus.PENDING_HUMAN
                        conv.quote_language = language
                        await db.commit()

                handoff_msg = HANDOFF_MESSAGES.get(language, HANDOFF_MESSAGES["en"])
                await save_message(conversation.id, MessageRole.ASSISTANT, handoff_msg, language)
                stop_typing.set()
                await typing_task
                await update.message.reply_text(handoff_msg)
                await notify_admin(
                    bot_id,
                    conversation,
                    user_message,
                    context.bot,
                    is_followup=(current_status == ConversationStatus.PENDING_HUMAN),
                )
                return

            if current_status == ConversationStatus.PENDING_HUMAN:
                await notify_admin(bot_id, conversation, user_message, context.bot, is_followup=True)

            if might_want_product_image(user_message):
                all_files_for_img = await get_all_file_entries()
                img_ids = (
                    await match_product_image_files(user_message, all_files_for_img)
                    if all_files_for_img
                    else []
                )
                if img_ids:
                    ack = PRODUCT_IMAGE_ACK.get(language, PRODUCT_IMAGE_ACK["en"])
                    await save_message(
                        conversation.id,
                        MessageRole.ASSISTANT,
                        ack,
                        language,
                        attachment_file_id=img_ids[0],
                    )
                    stop_typing.set()
                    await typing_task
                    await update.message.reply_text(ack)
                    await send_one_product_image_file(chat_id, img_ids[0], context.bot)
                    logger.info(f"[Bot {bot_id}] Auto-sent product image id={img_ids[0]}")
                    return

            kb_context = await search_knowledge_for_bot(user_message)

            all_files = await get_all_file_entries()
            matched_file_ids = await check_file_request(user_message, all_files) if all_files else []

            file_info = ""
            if matched_file_ids:
                matched_entries = [f for f in all_files if f["id"] in matched_file_ids]
                file_info = "\n".join(f"- {f['name']}: {f['description']}" for f in matched_entries)

            chat_history = await get_chat_history(conversation.id)

            logger.info(f"[Bot {bot_id}] Generating AI response...")
            response_text = await generate_response(
                user_message=user_message,
                context=kb_context,
                language=language,
                chat_history=chat_history,
                file_info=file_info,
            )
            logger.info(f"[Bot {bot_id}] AI response generated ({len(response_text)} chars)")

            await save_message(conversation.id, MessageRole.ASSISTANT, response_text, language)
            stop_typing.set()
            await typing_task

            await update.message.reply_text(response_text)
            logger.info(f"[Bot {bot_id}] Reply sent to chat {chat_id}")

            if matched_file_ids:
                await send_files_to_user(chat_id, matched_file_ids, context.bot)
        except Exception as e:
            stop_typing.set()
            await typing_task
            logger.error(f"[Bot {bot_id}] Error processing message: {e}", exc_info=True)
            fallback = {
                "zh": "抱歉，系统暂时出现问题，请稍后再试或联系人工客服。",
                "en": "Sorry, the system is temporarily unavailable. Please try again later.",
            }
            try:
                await update.message.reply_text(fallback.get(language, fallback["en"]))
            except Exception:
                logger.error(f"[Bot {bot_id}] Failed to send fallback message", exc_info=True)

    return handle_message


def make_close_handler(bot_id: int):
    async def handle_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = str(update.effective_chat.id)
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Conversation).where(
                    Conversation.bot_id == bot_id,
                    Conversation.telegram_chat_id == chat_id,
                    Conversation.status != ConversationStatus.CLOSED,
                )
            )
            conversation = result.scalar_one_or_none()
            if conversation:
                conversation.status = ConversationStatus.CLOSED
                await db.commit()
                await update.message.reply_text("对话已关闭。发送 /start 开始新对话。")
            else:
                await update.message.reply_text("没有找到进行中的对话。")

    return handle_close
