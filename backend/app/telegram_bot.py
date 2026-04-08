import asyncio
import logging
import os
from io import BytesIO
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, constants
from telegram.ext import ContextTypes
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import (
    Conversation, Message, FileEntry, TelegramBot, ConversationStatus, MessageRole,
    ProductEntry, ConversationSceneState,
)
from app.services.llm_service import (
    detect_language, check_is_quote_related, check_file_request, generate_response,
    check_is_product_recommendation, ai_select_products, check_is_scene_image_confirmation,
    analyze_scene_image_request, resolve_recent_product_reference,
)
from app.services.rag_service import search_knowledge_for_bot
from app.services.scene_service import generate_scene_images

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

PRODUCT_REC_INTRO = {
    "zh": "为您推荐以下产品：",
    "en": "Here are some products that may interest you:",
    "ja": "以下の商品をおすすめします：",
    "ko": "다음 제품을 추천드립니다：",
    "es": "Le recomendamos los siguientes productos:",
    "fr": "Voici des produits qui pourraient vous intéresser :",
}

PRODUCT_REC_NONE = {
    "zh": "抱歉，暂时没有找到符合您需求的产品，请联系人工客服获取更多信息。",
    "en": "Sorry, I couldn't find matching products. Please contact a human agent for more information.",
    "ja": "申し訳ありませんが、条件に合う商品が見つかりませんでした。担当者にご連絡ください。",
    "ko": "죄송합니다. 조건에 맞는 제품을 찾지 못했습니다. 상담원에게 문의해 주세요.",
    "es": "Lo siento, no encontré productos que coincidan. Contacte a un agente.",
    "fr": "Désolé, aucun produit correspondant. Veuillez contacter un agent.",
}

SCENE_FOLLOWUP_MESSAGES = {
    "zh": "如果您愿意，我还可以继续为您生成其中某一款产品在{scene}中的 3 张搭配效果图，并附上相关商品链接。您可以回复商品编号（如 #3）或直接说商品名。",
    "en": "If you'd like, I can also generate 3 styled scene images for any one of these products in a {scene} setting with matching product links. You can reply with the product number (for example #3) or the product name.",
}

SCENE_GENERATING_MESSAGES = {
    "zh": "好的，我正在为您生成场景搭配图，通常需要一点时间，请稍候。",
    "en": "Sure, I'm generating the styled scene images for you now. This may take a little while.",
}

SCENE_FAILED_MESSAGES = {
    "zh": "抱歉，这次场景图生成失败了。您可以稍后再试，或告诉我更具体的场景和风格要求。",
    "en": "Sorry, the scene image generation failed this time. Please try again later or share a more specific scene/style request.",
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


async def get_products_for_bot() -> list[dict]:
    """Load all products from DB for AI recommendation."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ProductEntry)
            .options(selectinload(ProductEntry.images))
            .order_by(ProductEntry.id)
        )
        entries = result.scalars().all()
        return [
            {
                "id": e.id,
                "brand": e.brand,
                "name": e.product_name,
                "series": e.series_name,
                "space": e.space,
                "style": e.style,
                "color": e.color,
                "material": e.material,
                "size": e.size,
                "description": e.description_text,
                "buy_url": e.buy_url,
                "detail_url": e.detail_url,
                "image_paths": [img.local_path for img in e.images],
            }
            for e in entries
        ]


async def get_scene_state(conversation_id: int) -> ConversationSceneState | None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ConversationSceneState).where(ConversationSceneState.conversation_id == conversation_id)
        )
        return result.scalar_one_or_none()


async def save_scene_state(
    conversation_id: int,
    primary_product_id: int | None,
    recommended_product_ids: list[int],
    suggested_scene: str,
    suggested_style: str,
    pending_confirmation: bool,
    reply_language: str,
    last_customer_request: str = "",
):
    import json

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ConversationSceneState).where(ConversationSceneState.conversation_id == conversation_id)
        )
        state = result.scalar_one_or_none()
        if not state:
            state = ConversationSceneState(conversation_id=conversation_id)
            db.add(state)
        state.primary_product_id = primary_product_id
        state.recommended_product_ids_json = json.dumps(recommended_product_ids, ensure_ascii=False)
        state.suggested_scene = suggested_scene or ""
        state.suggested_style = suggested_style or ""
        state.pending_confirmation = pending_confirmation
        state.reply_language = reply_language or "en"
        state.last_customer_request = last_customer_request or ""
        await db.commit()


async def clear_scene_state(conversation_id: int):
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ConversationSceneState).where(ConversationSceneState.conversation_id == conversation_id)
        )
        state = result.scalar_one_or_none()
        if state:
            state.pending_confirmation = False
            state.last_customer_request = ""
            await db.commit()


def build_scene_followup_message(language: str, product: dict) -> str:
    scene = product.get("space") or ("客厅" if language == "zh" else "living room")
    template = SCENE_FOLLOWUP_MESSAGES.get(language, SCENE_FOLLOWUP_MESSAGES["en"])
    return template.format(scene=scene)


async def send_scene_generation_result(chat_id: str, language: str, record, bot):
    import json

    if record.status != "completed":
        text = SCENE_FAILED_MESSAGES.get(language, SCENE_FAILED_MESSAGES["en"])
        await bot.send_message(chat_id=int(chat_id), text=text)
        return

    output_paths = json.loads(record.output_paths_json or "[]")
    intro = {
        "zh": f"这是为您生成的 {record.scene_name or '场景'} 搭配效果图，共 {len(output_paths)} 张：",
        "en": f"Here are {len(output_paths)} styled scene images for this product in {record.scene_name or 'the requested setting'}:",
    }.get(language, f"Here are {len(output_paths)} styled scene images for this product:")
    await bot.send_message(chat_id=int(chat_id), text=intro)

    for rel in output_paths:
        full = os.path.join("/app", rel)
        if not os.path.exists(full):
            continue
        try:
            with open(full, "rb") as f:
                bio = BytesIO(f.read())
            bio.name = os.path.basename(full)
            bio.seek(0)
            await bot.send_photo(chat_id=int(chat_id), photo=bio)
        except Exception as e:
            logger.error("Failed to send generated scene image %s: %s", full, e)

    async with AsyncSessionLocal() as db:
        primary = await db.get(ProductEntry, record.primary_product_id)
        related_ids = json.loads(record.related_product_ids_json or "[]")
        related = []
        if related_ids:
            result = await db.execute(select(ProductEntry).where(ProductEntry.id.in_(related_ids)).order_by(ProductEntry.id))
            related = result.scalars().all()

    lines = []
    if primary:
        link = primary.buy_url or primary.detail_url
        if link:
            lines.append(f"主商品: [{primary.product_name}]({link})")
    for p in related:
        link = p.buy_url or p.detail_url
        if link:
            lines.append(f"搭配商品: [{p.product_name}]({link})")
    if lines:
        await bot.send_message(
            chat_id=int(chat_id),
            text="\n".join(lines),
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )


async def send_product_recommendations(chat_id: str, products: list[dict], language: str, bot):
    """Send 1-3 recommended products as Telegram photo cards."""
    for idx, p in enumerate(products, start=1):
        lines = [f"[#{idx}] *{p['name']}*"]
        if p.get("series"):
            lines.append(f"系列: {p['series']}")
        if p.get("space"):
            lines.append(f"空间: {p['space']}")
        if p.get("style"):
            lines.append(f"风格: {p['style']}")
        if p.get("color"):
            lines.append(f"颜色: {p['color']}")
        if p.get("material"):
            lines.append(f"材质: {p['material']}")
        if p.get("buy_url"):
            lines.append(f"[查看详情]({p['buy_url']})")
        caption = "\n".join(lines)[:1024]

        sent = False
        for img_path in p.get("image_paths", []):
            full = os.path.join("/app", img_path)
            if not os.path.exists(full):
                continue
            try:
                with open(full, "rb") as f:
                    bio = BytesIO(f.read())
                bio.name = os.path.basename(full)
                bio.seek(0)
                await bot.send_photo(
                    chat_id=int(chat_id),
                    photo=bio,
                    caption=caption,
                    parse_mode="Markdown",
                )
                sent = True
                break
            except Exception as e:
                logger.error(f"Failed to send product photo {full}: {e}")

        if not sent:
            try:
                await bot.send_message(
                    chat_id=int(chat_id),
                    text=caption,
                    parse_mode="Markdown",
                )
            except Exception as e:
                logger.error(f"Failed to send product text card: {e}")


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
        import json

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

            scene_state = await get_scene_state(conversation.id)
            recent_scene_product_ids = []
            if scene_state:
                try:
                    recent_scene_product_ids = [
                        int(x) for x in json.loads(scene_state.recommended_product_ids_json or "[]")
                    ]
                except Exception:
                    recent_scene_product_ids = []

            all_products = await get_products_for_bot()
            scene_req = await analyze_scene_image_request(
                user_message,
                all_products,
                recent_product_ids=recent_scene_product_ids,
            )

            if scene_state and scene_state.pending_confirmation:
                resolved_ref = await resolve_recent_product_reference(
                    user_message,
                    all_products,
                    recent_scene_product_ids,
                )
                referenced_id = resolved_ref.get("target_product_id")
                wants_scene = (
                    scene_req.get("is_scene_request")
                    or referenced_id is not None
                    or await check_is_scene_image_confirmation(user_message)
                )
                if wants_scene:
                    primary_id = (
                        scene_req.get("target_product_id")
                        or referenced_id
                        or scene_state.primary_product_id
                        or (recent_scene_product_ids[0] if recent_scene_product_ids else None)
                    )
                    primary_product = None
                    if primary_id:
                        async with AsyncSessionLocal() as db:
                            primary_product = await db.get(ProductEntry, primary_id)
                    if primary_product:
                        requested_scene = (scene_req.get("scene_name") or "").strip()
                        requested_style = (scene_req.get("style_hint") or "").strip()
                        default_scene = requested_scene or (
                            scene_state.suggested_scene
                            if not referenced_id or referenced_id == scene_state.primary_product_id
                            else primary_product.space
                        )
                        default_style = requested_style or (
                            scene_state.suggested_style
                            if not referenced_id or referenced_id == scene_state.primary_product_id
                            else primary_product.style
                        )
                        generating = SCENE_GENERATING_MESSAGES.get(language, SCENE_GENERATING_MESSAGES["en"])
                        stop_typing.set()
                        await typing_task
                        await update.message.reply_text(generating)
                        await save_message(conversation.id, MessageRole.ASSISTANT, generating, language)
                        record = await generate_scene_images(
                            primary_product=primary_product,
                            all_products=all_products,
                            user_request=user_message if (referenced_id or scene_req.get("is_scene_request")) else (scene_state.last_customer_request or user_message),
                            scene_name=default_scene or primary_product.space,
                            style_hint=default_style or primary_product.style,
                            conversation_id=conversation.id,
                        )
                        await send_scene_generation_result(chat_id, language, record, context.bot)
                        await clear_scene_state(conversation.id)
                        return

            if scene_req.get("is_scene_request"):
                resolved_ref = await resolve_recent_product_reference(
                    user_message,
                    all_products,
                    recent_scene_product_ids,
                )
                referenced_id = resolved_ref.get("target_product_id")
                target_id = scene_req.get("target_product_id") or referenced_id or (scene_state.primary_product_id if scene_state else None)
                if target_id:
                    async with AsyncSessionLocal() as db:
                        primary_product = await db.get(ProductEntry, int(target_id))
                    if primary_product:
                        generating = SCENE_GENERATING_MESSAGES.get(language, SCENE_GENERATING_MESSAGES["en"])
                        stop_typing.set()
                        await typing_task
                        await update.message.reply_text(generating)
                        await save_message(conversation.id, MessageRole.ASSISTANT, generating, language)
                        record = await generate_scene_images(
                            primary_product=primary_product,
                            all_products=all_products,
                            user_request=user_message,
                            scene_name=scene_req.get("scene_name") or primary_product.space,
                            style_hint=scene_req.get("style_hint") or primary_product.style,
                            conversation_id=conversation.id,
                        )
                        await send_scene_generation_result(chat_id, language, record, context.bot)
                        await save_scene_state(
                            conversation_id=conversation.id,
                            primary_product_id=primary_product.id,
                            recommended_product_ids=[primary_product.id],
                            suggested_scene=scene_req.get("scene_name") or primary_product.space,
                            suggested_style=scene_req.get("style_hint") or primary_product.style,
                            pending_confirmation=False,
                            reply_language=language,
                            last_customer_request=user_message,
                        )
                        return

            is_product_rec = await check_is_product_recommendation(user_message)
            logger.info(f"[Bot {bot_id}] Product recommendation: {is_product_rec}")
            if is_product_rec:
                selected_ids = await ai_select_products(user_message, all_products) if all_products else []
                products_by_id = {p["id"]: p for p in all_products}
                selected_products = [products_by_id[pid] for pid in selected_ids if pid in products_by_id]
                intro = PRODUCT_REC_INTRO.get(language, PRODUCT_REC_INTRO["en"])
                none_msg = PRODUCT_REC_NONE.get(language, PRODUCT_REC_NONE["en"])
                stop_typing.set()
                await typing_task
                if selected_products:
                    await update.message.reply_text(intro)
                    await save_message(conversation.id, MessageRole.ASSISTANT, intro, language)
                    await send_product_recommendations(chat_id, selected_products, language, context.bot)
                    primary_product = selected_products[0]
                    followup = build_scene_followup_message(language, primary_product)
                    await update.message.reply_text(followup)
                    await save_message(conversation.id, MessageRole.ASSISTANT, followup, language)
                    await save_scene_state(
                        conversation_id=conversation.id,
                        primary_product_id=primary_product["id"],
                        recommended_product_ids=selected_ids,
                        suggested_scene=primary_product.get("space", ""),
                        suggested_style=primary_product.get("style", ""),
                        pending_confirmation=True,
                        reply_language=language,
                        last_customer_request=user_message,
                    )
                    logger.info(f"[Bot {bot_id}] Sent {len(selected_products)} product recommendations")
                else:
                    await update.message.reply_text(none_msg)
                    await save_message(conversation.id, MessageRole.ASSISTANT, none_msg, language)
                    await clear_scene_state(conversation.id)
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
