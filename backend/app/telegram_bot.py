import asyncio
import base64
import json
import logging
import mimetypes
import os
import re
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol
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
    detect_language, check_file_request, generate_response,
    classify_customer_intent, classify_customer_intent_fast, ai_select_products,
    resolve_recent_product_reference,
)
from app.services.rag_service import search_knowledge_for_bot
from app.services.scene_service import CUSTOMER_SCENE_TIMEOUT_SECONDS, build_scene_record_response, generate_scene_images
from app.services.customer_service_service import (
    create_pending_ai_delivery,
    get_customer_service_settings,
    create_pending_ai_reply,
)
from app.services.conversation_monitoring import (
    complete_turn_metric,
    mark_conversation_completed,
    mark_conversation_failed,
    mark_turn_first_response,
    mark_turn_intent,
    set_conversation_stage,
    start_turn_metric,
)

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

MANUAL_ONLY_WAIT_MESSAGES = {
    "zh": "已为您转接人工客服，请稍候回复。",
    "en": "I've routed your message to a human agent. Please wait for a reply.",
    "ja": "担当者にお繋ぎしました。返信まで少々お待ちください。",
    "ko": "상담원에게 연결했습니다. 답변을 잠시 기다려 주세요.",
    "es": "He transferido su mensaje a un agente humano. Por favor espere la respuesta.",
    "fr": "J'ai transmis votre message à un agent. Veuillez patienter pour la réponse.",
}

COMPLAINT_HANDOFF_MESSAGES = {
    "zh": "抱歉给您带来了不好的体验。我已为您转接人工客服，请稍候，我们会优先处理您的问题。",
    "en": "Sorry for the poor experience. I've connected you to a human agent so we can handle this with priority.",
    "ja": "ご不便をおかけして申し訳ありません。担当者にお繋ぎしますので、少々お待ちください。",
    "ko": "불편을 드려 죄송합니다. 상담원에게 연결해 우선적으로 도와드리겠습니다.",
    "es": "Lamento la mala experiencia. Le he conectado con un agente para atenderlo con prioridad.",
    "fr": "Désolé pour cette mauvaise expérience. Je vous mets en relation avec un agent pour traiter cela en priorité.",
}

OUT_OF_SCOPE_MESSAGES = {
    "zh": "抱歉，这个问题超出了当前家具客服的支持范围。您可以继续咨询产品、材质、搭配、资料或售后相关问题。",
    "en": "Sorry, that is outside the current furniture support scope. I can help with products, materials, styling, documents, or after-sales questions.",
    "ja": "申し訳ありませんが、その内容は現在の家具カスタマーサポートの対応範囲外です。商品、素材、コーディネート、資料、アフターサービスについては引き続きお手伝いできます。",
    "ko": "죄송하지만 해당 내용은 현재 가구 고객지원 범위를 벗어납니다. 제품, 소재, 스타일링, 자료 또는 사후 지원 관련 문의는 계속 도와드릴 수 있습니다.",
    "es": "Lo siento, eso está fuera del alcance actual del soporte de muebles. Puedo ayudarle con productos, materiales, combinaciones, documentos o servicio posventa.",
    "fr": "Désolé, cette demande dépasse le périmètre actuel du support mobilier. Je peux vous aider pour les produits, matériaux, mises en scène, documents ou questions après-vente.",
}

CLARIFICATION_MESSAGES = {
    "zh": "我还需要一点更具体的信息，才能准确处理。您可以补充一下想了解的产品、空间、风格或具体问题吗？",
    "en": "I need a bit more detail to handle this accurately. Could you share the product, room, style, or specific question?",
    "ja": "正確に対応するため、もう少し詳しい情報が必要です。商品、空間、スタイル、または具体的なご質問を教えていただけますか？",
    "ko": "정확히 처리하려면 조금 더 구체적인 정보가 필요합니다. 제품, 공간, 스타일 또는 구체적인 질문을 알려주시겠어요?",
    "es": "Necesito un poco más de detalle para atenderlo con precisión. ¿Podría indicar el producto, espacio, estilo o pregunta específica?",
    "fr": "J'ai besoin d'un peu plus de précisions pour traiter votre demande correctement. Pouvez-vous indiquer le produit, l'espace, le style ou la question précise ?",
}

TOPIC_SWITCH_PREFIX = {
    "zh": "好的，我们先处理您新的问题。\n\n",
    "en": "Sure, let's handle your new question first.\n\n",
    "ja": "承知しました。まず新しいご質問に対応します。\n\n",
    "ko": "좋습니다. 먼저 새 문의를 처리하겠습니다.\n\n",
    "es": "De acuerdo, primero atendamos su nueva consulta.\n\n",
    "fr": "D'accord, traitons d'abord votre nouvelle question.\n\n",
}

REPEATED_QUESTION_PREFIX = {
    "zh": "我换一种方式说明：\n\n",
    "en": "Let me explain this another way:\n\n",
    "ja": "別の言い方でご説明します：\n\n",
    "ko": "다른 방식으로 설명드리겠습니다:\n\n",
    "es": "Permítame explicarlo de otra manera:\n\n",
    "fr": "Permettez-moi de l'expliquer autrement :\n\n",
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
    "zh": "如果您愿意，我还可以继续为您生成其中某一款产品在{scene}中的搭配效果图，并附上相关商品链接。您可以回复商品编号（如 #3）或直接说商品名。",
    "en": "If you'd like, I can also generate a styled scene image for any one of these products in a {scene} setting with matching product links. You can reply with the product number (for example #3) or the product name.",
}

SCENE_GENERATING_MESSAGES = {
    "zh": "好的，我正在为您生成场景搭配图，通常需要一点时间，请稍候。",
    "en": "Sure, I'm generating the styled scene images for you now. This may take a little while.",
}

SCENE_FAILED_MESSAGES = {
    "zh": "抱歉，这次场景图生成失败了。您可以稍后再试，或告诉我更具体的场景和风格要求。",
    "en": "Sorry, the scene image generation failed this time. Please try again later or share a more specific scene/style request.",
}

SCENE_TIMEOUT_MESSAGES = {
    "zh": "抱歉，这次场景图生成超时了。请稍后再试，或减少搭配要求后重新生成。",
    "en": "Sorry, the scene image generation timed out. Please try again later or simplify the styling request.",
}

SCENE_KEYWORDS = {
    "客厅": ["sofa", "couch", "coffee table", "tv cabinet", "tv stand", "sectional", "recliner", "沙发", "茶几", "电视柜", "边几"],
    "餐厅": ["dining table", "dining chair", "sideboard", "buffet", "bar table", "bar stool", "餐桌", "餐椅", "餐边柜", "吧台", "吧椅"],
    "卧室": ["bed", "nightstand", "wardrobe", "dresser", "mattress", "床", "床头柜", "衣柜", "斗柜", "床垫"],
    "书房": ["desk", "bookcase", "bookshelf", "study", "office chair", "书桌", "书柜", "书架", "办公椅", "茶台"],
}

# UI copy in the recommendation + scene-image path is intentionally complete only
# for these languages. Any other language falls back to English to avoid mixed output.
SCENE_UI_SUPPORTED_LANGUAGES = {"zh", "en", "ja", "ko", "es", "fr"}

SCENE_NAME_TRANSLATIONS = {
    "客厅": {"zh": "客厅", "en": "living room", "ja": "リビング", "ko": "거실", "es": "sala de estar", "fr": "salon"},
    "餐厅": {"zh": "餐厅", "en": "dining room", "ja": "ダイニング", "ko": "식당", "es": "comedor", "fr": "salle a manger"},
    "卧室": {"zh": "卧室", "en": "bedroom", "ja": "寝室", "ko": "침실", "es": "dormitorio", "fr": "chambre"},
    "书房": {"zh": "书房", "en": "study", "ja": "書斎", "ko": "서재", "es": "estudio", "fr": "bureau"},
    "儿童房": {"zh": "儿童房", "en": "children's room", "ja": "子供部屋", "ko": "어린이 방", "es": "habitación infantil", "fr": "chambre d'enfant"},
    "玄关": {"zh": "玄关", "en": "entryway", "ja": "玄関", "ko": "현관", "es": "recibidor", "fr": "entrée"},
}

PRODUCT_CARD_LABELS = {
    "zh": {"series": "系列", "space": "空间", "style": "风格", "color": "颜色", "material": "材质", "view": "查看详情"},
    "en": {"series": "Series", "space": "Space", "style": "Style", "color": "Color", "material": "Material", "view": "View details"},
    "ja": {"series": "シリーズ", "space": "空間", "style": "スタイル", "color": "色", "material": "素材", "view": "詳細を見る"},
    "ko": {"series": "시리즈", "space": "공간", "style": "스타일", "color": "색상", "material": "소재", "view": "자세히 보기"},
    "es": {"series": "Serie", "space": "Espacio", "style": "Estilo", "color": "Color", "material": "Material", "view": "Ver detalles"},
    "fr": {"series": "Série", "space": "Espace", "style": "Style", "color": "Couleur", "material": "Matériau", "view": "Voir les détails"},
}

SCENE_RESULT_MESSAGES = {
    "zh": "这是为您生成的这款产品在{scene}中的搭配效果图：",
    "en": "Here is the styled scene image for this product in the {scene}:",
    "ja": "こちらがこの商品を{scene}に配置したイメージです：",
    "ko": "다음은 이 제품을 {scene}에 배치한 연출 이미지입니다:",
    "es": "Aqui tiene la imagen ambientada de este producto en el/la {scene}:",
    "fr": "Voici l'image mise en scène de ce produit dans le/la {scene} :",
}

SCENE_RESULT_LINK_LABELS = {
    "zh": {"main": "主商品", "related": "搭配商品"},
    "en": {"main": "Main product", "related": "Matching product"},
    "ja": {"main": "主商品", "related": "組み合わせ商品"},
    "ko": {"main": "주요 상품", "related": "매칭 상품"},
    "es": {"main": "Producto principal", "related": "Producto combinado"},
    "fr": {"main": "Produit principal", "related": "Produit assorti"},
}


class CustomerOutbound(Protocol):
    async def reply_text(
        self,
        text: str,
        parse_mode: str | None = None,
        disable_web_page_preview: bool = False,
    ) -> None:
        ...

    async def send_local_photo(
        self,
        full_path: str,
        caption: str | None = None,
        parse_mode: str | None = None,
    ) -> None:
        ...

    async def send_document_file(
        self,
        file_path: str,
        filename: str,
        caption: str | None = None,
    ) -> None:
        ...


def _data_url_from_file(path: str) -> str:
    mime_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    encoded = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


class TelegramOutbound:
    def __init__(self, chat_id: int, bot) -> None:
        self.chat_id = chat_id
        self.bot = bot

    async def reply_text(
        self,
        text: str,
        parse_mode: str | None = None,
        disable_web_page_preview: bool = False,
    ) -> None:
        await self.bot.send_message(
            chat_id=self.chat_id,
            text=text,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
        )

    async def send_local_photo(
        self,
        full_path: str,
        caption: str | None = None,
        parse_mode: str | None = None,
    ) -> None:
        with open(full_path, "rb") as fh:
            bio = BytesIO(fh.read())
        bio.name = os.path.basename(full_path)
        bio.seek(0)
        await self.bot.send_photo(
            chat_id=self.chat_id,
            photo=bio,
            caption=caption,
            parse_mode=parse_mode,
        )

    async def send_document_file(
        self,
        file_path: str,
        filename: str,
        caption: str | None = None,
    ) -> None:
        with open(file_path, "rb") as fh:
            await self.bot.send_document(
                chat_id=self.chat_id,
                document=fh,
                filename=filename,
                caption=caption,
            )


class SimulatorOutbound:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def _append(self, payload: dict[str, Any]) -> None:
        self.events.append(
            {
                "id": f"evt-{len(self.events) + 1}-{int(asyncio.get_running_loop().time() * 1000)}",
                "role": "assistant",
                "created_at": datetime.utcnow().isoformat(),
                **payload,
            }
        )

    async def reply_text(
        self,
        text: str,
        parse_mode: str | None = None,
        disable_web_page_preview: bool = False,
    ) -> None:
        self._append(
            {
                "type": "text",
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": disable_web_page_preview,
            }
        )

    async def send_local_photo(
        self,
        full_path: str,
        caption: str | None = None,
        parse_mode: str | None = None,
    ) -> None:
        self._append(
            {
                "type": "photo",
                "url": _data_url_from_file(full_path),
                "caption": caption or "",
                "parse_mode": parse_mode,
            }
        )

    async def send_document_file(
        self,
        file_path: str,
        filename: str,
        caption: str | None = None,
    ) -> None:
        self._append(
            {
                "type": "document",
                "url": _data_url_from_file(file_path),
                "filename": filename,
                "caption": caption or "",
            }
        )

    async def send_photo_url(
        self,
        url: str,
        caption: str | None = None,
        parse_mode: str | None = None,
    ) -> None:
        self._append(
            {
                "type": "photo",
                "url": url,
                "caption": caption or "",
                "parse_mode": parse_mode,
            }
        )


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
        await db.refresh(msg)
        return msg.id


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


def _normalize_repeat_text(text: str) -> str:
    normalized = (text or "").strip().lower()
    normalized = re.sub(r"[\s\W_]+", "", normalized, flags=re.UNICODE)
    return normalized


def _is_repeated_user_question(chat_history: list[dict], user_message: str) -> bool:
    normalized = _normalize_repeat_text(user_message)
    if len(normalized) < 2:
        return False
    count = 0
    for msg in chat_history:
        if msg.get("role") != "user":
            continue
        if _normalize_repeat_text(msg.get("content") or "") == normalized:
            count += 1
    return count >= 2


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


async def send_files_to_user(file_ids: list[int], outbound: CustomerOutbound):
    for fid in file_ids:
        entry = await get_file_entry_by_id(fid)
        if not entry:
            continue
        try:
            await outbound.send_document_file(
                file_path=entry.file_path,
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


def ui_scene_language(language: str | None) -> str:
    lang = (language or "").strip().lower()
    return lang if lang in SCENE_UI_SUPPORTED_LANGUAGES else "en"


def localize_scene_name(scene: str, language: str) -> str:
    language = ui_scene_language(language)
    raw = (scene or "").strip()
    if not raw:
        return ""
    normalized = raw.lower()
    for canonical, translations in SCENE_NAME_TRANSLATIONS.items():
        values = {canonical.lower(), *(value.lower() for value in translations.values())}
        if raw == canonical or normalized in values:
            return translations.get(language, translations.get("en", canonical))
    return raw


def _is_context_language_reply(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return False
    if re.fullmatch(r"[#\d\s]+", stripped):
        return True
    if len(stripped) <= 24 and re.fullmatch(r"[A-Za-z]?\d[\w#-]*", stripped):
        return True
    if len(stripped) <= 24 and re.fullmatch(r"[#A-Za-z0-9_-]+", stripped) and not re.search(r"[A-Za-z]{3,}", stripped):
        return True
    return False


def resolve_turn_language(
    user_message: str,
    detected_language: str,
    conversation_language: str | None,
    scene_reply_language: str | None,
) -> str:
    if _is_context_language_reply(user_message):
        return scene_reply_language or conversation_language or detected_language or "en"
    return detected_language or scene_reply_language or conversation_language or "en"


def infer_product_scene(product: dict) -> str:
    explicit = (product.get("space") or "").strip()
    if explicit:
        return explicit
    haystack = " ".join(
        str(product.get(key) or "").lower()
        for key in ["name", "series", "description"]
    )
    for scene, keywords in SCENE_KEYWORDS.items():
        if any(keyword in haystack for keyword in keywords):
            return scene
    return ""


def select_default_scene(products: list[dict], language: str) -> str:
    counts: dict[str, int] = {}
    for product in products:
        scene = infer_product_scene(product)
        if not scene:
            continue
        counts[scene] = counts.get(scene, 0) + 1
    if counts:
        return max(counts.items(), key=lambda item: (item[1], item[0]))[0]
    return "客厅" if language == "zh" else "living room"


def resolve_recommended_product_reference_locally(
    user_message: str,
    recommended_product_ids: list[int],
) -> int | None:
    """Resolve common product-number replies without depending on the LLM."""
    if not recommended_product_ids:
        return None

    normalized = (user_message or "").strip().lower().translate(str.maketrans({
        "１": "1",
        "２": "2",
        "３": "3",
        "＃": "#",
        "﹟": "#",
    }))
    compact = re.sub(r"\s+", "", normalized)

    def pick(index: int | None) -> int | None:
        if index is None or index < 1 or index > len(recommended_product_ids):
            return None
        return recommended_product_ids[index - 1]

    if re.fullmatch(r"#?[1-3]", compact):
        return pick(int(compact.replace("#", "")))

    explicit_match = re.search(
        r"(?:#|编号|商品|产品|第|no\.?|number|num|nº)\s*([1-3])",
        normalized,
        flags=re.IGNORECASE,
    )
    if explicit_match:
        return pick(int(explicit_match.group(1)))

    ordinal_words = {
        "一": 1, "壹": 1, "第一": 1, "第一个": 1, "第一款": 1,
        "二": 2, "两": 2, "贰": 2, "第二": 2, "第二个": 2, "第二款": 2,
        "三": 3, "叁": 3, "第三": 3, "第三个": 3, "第三款": 3,
        "first": 1, "1st": 1,
        "second": 2, "2nd": 2,
        "third": 3, "3rd": 3,
        "primero": 1, "primera": 1,
        "segundo": 2, "segunda": 2,
        "tercero": 3, "tercera": 3,
    }
    for word, index in ordinal_words.items():
        if word in compact:
            return pick(index)
    return None


def build_scene_followup_message(language: str, products: list[dict]) -> str:
    ui_lang = ui_scene_language(language)
    scene = localize_scene_name(select_default_scene(products, ui_lang), ui_lang)
    template = SCENE_FOLLOWUP_MESSAGES.get(ui_lang, SCENE_FOLLOWUP_MESSAGES["en"])
    return template.format(scene=scene)


def build_product_recommendation_delivery(products: list[dict], language: str) -> dict[str, Any]:
    ui_lang = ui_scene_language(language)
    labels = PRODUCT_CARD_LABELS.get(ui_lang, PRODUCT_CARD_LABELS["en"])
    cards: list[dict[str, Any]] = []
    preview_lines: list[str] = []

    for idx, p in enumerate(products, start=1):
        lines = [f"[#{idx}] *{p['name']}*"]
        preview_lines.append(f"#{idx} {p['name']}")
        if p.get("series"):
            lines.append(f"{labels['series']}: {p['series']}")
        if p.get("space"):
            lines.append(f"{labels['space']}: {localize_scene_name(p['space'], ui_lang)}")
        if p.get("style"):
            lines.append(f"{labels['style']}: {p['style']}")
        if p.get("color"):
            lines.append(f"{labels['color']}: {p['color']}")
        if p.get("material"):
            lines.append(f"{labels['material']}: {p['material']}")
        if p.get("buy_url"):
            lines.append(f"[{labels['view']}]({p['buy_url']})")
        image_paths = p.get("image_paths", [])
        image_path = image_paths[0] if image_paths else ""
        cards.append({
            "product_id": p["id"],
            "caption": "\n".join(lines)[:1024],
            "image_path": image_path,
            "image_url": f"/api/products/{p['id']}/images/0" if image_path else "",
            "parse_mode": "Markdown",
        })

    return {
        "cards": cards,
        "preview_lines": preview_lines,
    }


async def build_scene_result_delivery(record, language: str) -> dict[str, Any]:
    ui_lang = ui_scene_language(language)
    localized_scene = localize_scene_name(record.scene_name or "", ui_lang) or {
        "zh": "该场景",
        "en": "requested setting",
        "ja": "ご希望の空間",
        "ko": "요청하신 공간",
        "es": "ambiente solicitado",
        "fr": "cadre demande",
    }.get(ui_lang, "requested setting")
    intro_template = SCENE_RESULT_MESSAGES.get(ui_lang, SCENE_RESULT_MESSAGES["en"])
    intro_text = intro_template.format(scene=localized_scene)
    resp = await build_scene_record_response(record)
    labels = SCENE_RESULT_LINK_LABELS.get(ui_lang, SCENE_RESULT_LINK_LABELS["en"])
    lines: list[str] = []
    if resp.get("primary_product_name") and resp.get("primary_product_id"):
        async with AsyncSessionLocal() as db:
            primary = await db.get(ProductEntry, record.primary_product_id)
        if primary:
            primary_link = primary.buy_url or primary.detail_url
            if primary_link:
                lines.append(f"{labels['main']}: [{primary.product_name}]({primary_link})")
    for rel in resp.get("related_products", []):
        link = rel.get("buy_url") or rel.get("detail_url")
        if link:
            lines.append(f"{labels['related']}: [{rel.get('product_name', '')}]({link})")
    return {
        "intro_text": intro_text,
        "links_text": "\n".join(lines),
        "links_parse_mode": "Markdown",
        "image_urls": resp.get("image_urls", []),
        "output_paths": json.loads(record.output_paths_json or "[]"),
        "preview_line": f"{localized_scene} 场景图 {len(resp.get('image_urls', []))} 张" if ui_lang == "zh" else f"{localized_scene} scene image x{len(resp.get('image_urls', []))}",
    }


async def send_scene_generation_result(language: str, record, outbound: CustomerOutbound):
    import json
    ui_lang = ui_scene_language(language)

    if record.status != "completed":
        text = SCENE_FAILED_MESSAGES.get(ui_lang, SCENE_FAILED_MESSAGES["en"])
        await outbound.reply_text(text)
        return

    output_paths = json.loads(record.output_paths_json or "[]")
    localized_scene = localize_scene_name(record.scene_name or "", ui_lang) or {
        "zh": "该场景",
        "en": "requested setting",
        "ja": "ご希望の空間",
        "ko": "요청하신 공간",
        "es": "ambiente solicitado",
        "fr": "cadre demande",
    }.get(ui_lang, "requested setting")
    intro_template = SCENE_RESULT_MESSAGES.get(ui_lang, SCENE_RESULT_MESSAGES["en"])
    intro = intro_template.format(scene=localized_scene)
    await outbound.reply_text(intro)

    for rel in output_paths:
        full = os.path.join("/app", rel)
        if not os.path.exists(full):
            continue
        try:
            await outbound.send_local_photo(full)
        except Exception as e:
            logger.error("Failed to send generated scene image %s: %s", full, e)

    async with AsyncSessionLocal() as db:
        primary = await db.get(ProductEntry, record.primary_product_id)
        related_ids = json.loads(record.related_product_ids_json or "[]")
        related = []
        if related_ids:
            result = await db.execute(select(ProductEntry).where(ProductEntry.id.in_(related_ids)).order_by(ProductEntry.id))
            related = result.scalars().all()

    labels = SCENE_RESULT_LINK_LABELS.get(ui_lang, SCENE_RESULT_LINK_LABELS["en"])
    lines = []
    if primary:
        link = primary.buy_url or primary.detail_url
        if link:
            lines.append(f"{labels['main']}: [{primary.product_name}]({link})")
    for p in related:
        link = p.buy_url or p.detail_url
        if link:
            lines.append(f"{labels['related']}: [{p.product_name}]({link})")
    if lines:
        await outbound.reply_text(
            "\n".join(lines),
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )


async def send_product_recommendations(products: list[dict], language: str, outbound: CustomerOutbound):
    """Send 1-3 recommended products as Telegram photo cards."""
    ui_lang = ui_scene_language(language)
    labels = PRODUCT_CARD_LABELS.get(ui_lang, PRODUCT_CARD_LABELS["en"])
    for idx, p in enumerate(products, start=1):
        lines = [f"[#{idx}] *{p['name']}*"]
        if p.get("series"):
            lines.append(f"{labels['series']}: {p['series']}")
        if p.get("space"):
            lines.append(f"{labels['space']}: {localize_scene_name(p['space'], ui_lang)}")
        if p.get("style"):
            lines.append(f"{labels['style']}: {p['style']}")
        if p.get("color"):
            lines.append(f"{labels['color']}: {p['color']}")
        if p.get("material"):
            lines.append(f"{labels['material']}: {p['material']}")
        if p.get("buy_url"):
            lines.append(f"[{labels['view']}]({p['buy_url']})")
        caption = "\n".join(lines)[:1024]

        sent = False
        for image_order, img_path in enumerate(p.get("image_paths", [])):
            full = os.path.join("/app", img_path)
            if not os.path.exists(full):
                continue
            try:
                if isinstance(outbound, SimulatorOutbound):
                    await outbound.send_photo_url(
                        f"/api/products/{p['id']}/images/{image_order}",
                        caption=caption,
                        parse_mode="Markdown",
                    )
                else:
                    await outbound.send_local_photo(
                        full,
                        caption=caption,
                        parse_mode="Markdown",
                    )
                sent = True
                break
            except Exception as e:
                logger.error(f"Failed to send product photo {full}: {e}")

        if not sent:
            try:
                await outbound.reply_text(
                    caption,
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


async def process_customer_text_message(
    bot_id: int,
    conversation_id: int,
    user_message: str,
    language: str,
    current_status: str,
    outbound: CustomerOutbound,
    run_notify_admin: bool,
    notify_bot,
    stop_typing: asyncio.Event,
    typing_task: asyncio.Task,
    metric_id: int | None = None,
):
    first_response_marked = False

    async def stage(stage_key: str, detail: str = "") -> None:
        await set_conversation_stage(conversation_id, stage_key, stage_detail=detail)

    async def first_response(response_kind: str) -> None:
        nonlocal first_response_marked
        if first_response_marked:
            return
        first_response_marked = True
        await mark_turn_first_response(metric_id, response_kind)

    async def finish(response_kind: str, detail: str = "") -> None:
        await complete_turn_metric(metric_id, response_kind=response_kind, success=True)
        await mark_conversation_completed(conversation_id, detail)

    try:
        await stage("checking_service_mode")
        conversation = None
        async with AsyncSessionLocal() as db:
            conversation = await db.get(Conversation, conversation_id)
        service_settings = await get_customer_service_settings()
        service_mode = service_settings["mode"]

        if service_mode == "human_only":
            await stage("waiting_human", "当前为完全人工模式")
            async with AsyncSessionLocal() as db:
                conv = await db.get(Conversation, conversation_id)
                if conv:
                    conv.status = ConversationStatus.PENDING_HUMAN
                    conv.quote_language = language
                    await db.commit()

            if current_status != ConversationStatus.PENDING_HUMAN:
                wait_msg = MANUAL_ONLY_WAIT_MESSAGES.get(language, MANUAL_ONLY_WAIT_MESSAGES["en"])
                await first_response("human_only_wait")
                await save_message(conversation_id, MessageRole.ASSISTANT, wait_msg, language)
                stop_typing.set()
                await typing_task
                await outbound.reply_text(wait_msg)
            else:
                stop_typing.set()
                await typing_task

            if run_notify_admin and notify_bot and conversation:
                await notify_admin(
                    bot_id,
                    conversation,
                    user_message,
                    notify_bot,
                    is_followup=(current_status == ConversationStatus.PENDING_HUMAN),
                )
            await finish("human_only_wait", "已转人工")
            return

        await stage("loading_scene_state")
        scene_state = await get_scene_state(conversation_id)
        recent_scene_product_ids: list[int] = []
        if scene_state:
            try:
                recent_scene_product_ids = [
                    int(x) for x in json.loads(scene_state.recommended_product_ids_json or "[]")
                ]
            except Exception:
                recent_scene_product_ids = []

        await stage("classifying_intent_fast")
        has_pending_scene_confirmation = bool(scene_state and scene_state.pending_confirmation)
        intent = classify_customer_intent_fast(
            user_message,
            has_pending_scene_confirmation=has_pending_scene_confirmation,
        )
        all_products: list[dict] | None = None
        if not intent:
            await stage("loading_products")
            all_products = await get_products_for_bot()
            await stage("classifying_intent")
            intent = await classify_customer_intent(
                user_message,
                products=all_products,
                recent_product_ids=recent_scene_product_ids,
                has_pending_scene_confirmation=has_pending_scene_confirmation,
            )
        intent_name = intent.get("primary_intent") or "general_question"
        intent_confidence = float(intent.get("confidence") or 0.0)
        intent_slots = intent.get("slots") if isinstance(intent.get("slots"), dict) else {}
        secondary_intents = intent.get("secondary_intents") if isinstance(intent.get("secondary_intents"), list) else []
        logger.info(
            "[Bot %s] Intent routed: intent=%s confidence=%.2f source=%s reason=%s",
            bot_id,
            intent_name,
            intent_confidence,
            intent.get("source"),
            intent.get("reason"),
        )

        all_intents = {intent_name, *secondary_intents}
        if "complaint" in all_intents and intent_name != "complaint":
            intent_name = "complaint"
        elif "quote_handoff" in all_intents and intent_name != "quote_handoff":
            intent_name = "quote_handoff"
        elif "human_handoff" in all_intents and intent_name != "human_handoff":
            intent_name = "human_handoff"

        await mark_turn_intent(
            metric_id,
            primary_intent=intent_name,
            confidence=intent_confidence,
            source=str(intent.get("source") or ""),
            secondary_intents=secondary_intents,
            reason=str(intent.get("reason") or ""),
        )

        if "complaint" in all_intents and intent_confidence >= 0.65:
            await stage("waiting_human", "客户情绪或投诉已转人工")
            async with AsyncSessionLocal() as db:
                conv = await db.get(Conversation, conversation_id)
                if conv:
                    conv.status = ConversationStatus.PENDING_HUMAN
                    conv.quote_language = language
                    await db.commit()

            complaint_msg = COMPLAINT_HANDOFF_MESSAGES.get(language, COMPLAINT_HANDOFF_MESSAGES["en"])
            await first_response("complaint_handoff")
            await save_message(conversation_id, MessageRole.ASSISTANT, complaint_msg, language)
            stop_typing.set()
            await typing_task
            await outbound.reply_text(complaint_msg)
            if run_notify_admin and notify_bot and conversation:
                await notify_admin(
                    bot_id,
                    conversation,
                    user_message,
                    notify_bot,
                    is_followup=(current_status == ConversationStatus.PENDING_HUMAN),
                )
            await finish("complaint_handoff", "客户情绪或投诉已转人工")
            return

        handoff_intent = intent_name in {"quote_handoff", "human_handoff"} and intent_confidence >= 0.7
        if not handoff_intent and intent.get("needs_human") and intent_confidence >= 0.85:
            handoff_intent = True
        if handoff_intent:
            detail = "报价相关咨询已转人工" if intent_name == "quote_handoff" else "客户要求转人工"
            await stage("waiting_human", detail)
            async with AsyncSessionLocal() as db:
                conv = await db.get(Conversation, conversation_id)
                if conv:
                    conv.status = ConversationStatus.PENDING_HUMAN
                    conv.quote_language = language
                    await db.commit()

            handoff_msg = (
                HANDOFF_MESSAGES.get(language, HANDOFF_MESSAGES["en"])
                if intent_name == "quote_handoff"
                else MANUAL_ONLY_WAIT_MESSAGES.get(language, MANUAL_ONLY_WAIT_MESSAGES["en"])
            )
            await first_response("handoff")
            await save_message(conversation_id, MessageRole.ASSISTANT, handoff_msg, language)
            stop_typing.set()
            await typing_task
            await outbound.reply_text(handoff_msg)
            if run_notify_admin and notify_bot and conversation:
                await notify_admin(
                    bot_id,
                    conversation,
                    user_message,
                    notify_bot,
                    is_followup=(current_status == ConversationStatus.PENDING_HUMAN),
                )
            await finish("handoff", detail)
            return

        if current_status == ConversationStatus.PENDING_HUMAN and run_notify_admin and notify_bot and conversation:
            await notify_admin(bot_id, conversation, user_message, notify_bot, is_followup=True)

        if intent_name == "out_of_scope" and intent_confidence >= 0.7:
            out_of_scope_msg = OUT_OF_SCOPE_MESSAGES.get(language, OUT_OF_SCOPE_MESSAGES["en"])
            await first_response("out_of_scope")
            await save_message(conversation_id, MessageRole.ASSISTANT, out_of_scope_msg, language)
            stop_typing.set()
            await typing_task
            await outbound.reply_text(out_of_scope_msg)
            await finish("out_of_scope", "超出支持范围")
            return

        clarification_question = str(intent.get("clarification_question") or "").strip()
        if intent_confidence < 0.45:
            clarification_msg = clarification_question or CLARIFICATION_MESSAGES.get(language, CLARIFICATION_MESSAGES["en"])
            await first_response("clarification")
            await save_message(conversation_id, MessageRole.ASSISTANT, clarification_msg, language)
            stop_typing.set()
            await typing_task
            await outbound.reply_text(clarification_msg)
            await finish("clarification", "低置信度追问澄清")
            return

        topic_switch = (
            bool(scene_state and scene_state.pending_confirmation)
            and intent_name not in {"scene_image_request", "scene_image_confirmation"}
            and "scene_image_request" not in secondary_intents
            and intent_confidence >= 0.55
        )
        if topic_switch:
            await clear_scene_state(conversation_id)
            if scene_state:
                scene_state.pending_confirmation = False
                scene_state.last_customer_request = ""

        needs_product_context = (
            bool(scene_state and scene_state.pending_confirmation)
            or intent_name in {"product_recommendation", "scene_image_request", "scene_image_confirmation"}
            or "product_recommendation" in secondary_intents
            or "scene_image_request" in secondary_intents
        )
        if all_products is None and needs_product_context:
            await stage("loading_products")
            all_products = await get_products_for_bot()
        if all_products is None:
            all_products = []

        scene_req = {
            "is_scene_request": (
                intent_name == "scene_image_request"
                or "scene_image_request" in secondary_intents
            ) and intent_confidence >= 0.55,
            "scene_name": str(intent_slots.get("scene_name") or ""),
            "style_hint": str(intent_slots.get("style_hint") or ""),
            "target_product_id": intent_slots.get("target_product_id"),
            "reason": str(intent.get("reason") or ""),
        }

        if scene_state and scene_state.pending_confirmation:
            local_referenced_id = resolve_recommended_product_reference_locally(
                user_message,
                recent_scene_product_ids,
            )
            resolved_ref = await resolve_recent_product_reference(
                user_message,
                all_products,
                recent_scene_product_ids,
            )
            referenced_id = local_referenced_id or resolved_ref.get("target_product_id")
            wants_scene = (
                scene_req.get("is_scene_request")
                or referenced_id is not None
                or (
                    intent_name == "scene_image_confirmation"
                    and intent_confidence >= 0.55
                )
            )
            if wants_scene:
                await stage("resolving_product_reference")
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
                    stop_typing.set()
                    await typing_task
                    if service_mode != "ai_assist":
                        generating = SCENE_GENERATING_MESSAGES.get(language, SCENE_GENERATING_MESSAGES["en"])
                        await first_response("scene_generating_notice")
                        await outbound.reply_text(generating)
                        await save_message(conversation_id, MessageRole.ASSISTANT, generating, language)
                    try:
                        await stage("scene_image_generation", default_scene or primary_product.space or "")
                        record = await generate_scene_images(
                            primary_product=primary_product,
                            all_products=all_products,
                            user_request=user_message if (referenced_id or scene_req.get("is_scene_request")) else (scene_state.last_customer_request or user_message),
                            scene_name=default_scene or primary_product.space,
                            style_hint=default_style or primary_product.style,
                            conversation_id=conversation_id,
                            timeout_seconds=CUSTOMER_SCENE_TIMEOUT_SECONDS,
                        )
                    except asyncio.TimeoutError:
                        timeout_text = SCENE_TIMEOUT_MESSAGES.get(language, SCENE_TIMEOUT_MESSAGES["en"])
                        await first_response("scene_timeout")
                        if service_mode == "ai_assist":
                            await create_pending_ai_reply(conversation_id, timeout_text, language)
                        else:
                            await outbound.reply_text(timeout_text)
                            await save_message(conversation_id, MessageRole.ASSISTANT, timeout_text, language)
                        await clear_scene_state(conversation_id)
                        await complete_turn_metric(metric_id, response_kind="scene_timeout", success=False, error_message="Scene generation timed out")
                        await mark_conversation_failed(conversation_id, "场景图生成超时")
                        return
                    if service_mode == "ai_assist":
                        if record.status != "completed":
                            failed_text = SCENE_FAILED_MESSAGES.get(language, SCENE_FAILED_MESSAGES["en"])
                            await first_response("scene_failed")
                            await create_pending_ai_reply(conversation_id, failed_text, language)
                            await clear_scene_state(conversation_id)
                            if run_notify_admin and notify_bot and conversation:
                                await notify_admin(
                                    bot_id,
                                    conversation,
                                    user_message,
                                    notify_bot,
                                    is_followup=(current_status in {ConversationStatus.PENDING_HUMAN, ConversationStatus.HUMAN_HANDLING}),
                                )
                            await complete_turn_metric(metric_id, response_kind="scene_failed", success=False, error_message=record.error_message or "Scene generation failed")
                            await mark_conversation_failed(conversation_id, "场景图生成失败")
                            return
                        async with AsyncSessionLocal() as db:
                            current_record = await db.get(type(record), record.id)
                            if current_record:
                                current_record.deferred_delivery = True
                                await db.commit()
                        scene_delivery = await build_scene_result_delivery(record, language)
                        scene_delivery["record_id"] = record.id
                        scene_delivery["scene_state_action"] = "clear"
                        preview_text = f"{scene_delivery.get('intro_text', '')}\n\n{scene_delivery.get('preview_line', '')}".strip()
                        await stage("creating_ai_draft", "场景图待确认")
                        await first_response("scene_result_draft")
                        await create_pending_ai_delivery(
                            conversation_id=conversation_id,
                            draft_text=preview_text,
                            language=language,
                            content_kind="scene_result",
                            payload=scene_delivery,
                        )
                        await clear_scene_state(conversation_id)
                        if run_notify_admin and notify_bot and conversation:
                            await notify_admin(
                                bot_id,
                                conversation,
                                user_message,
                                notify_bot,
                                is_followup=(current_status in {ConversationStatus.PENDING_HUMAN, ConversationStatus.HUMAN_HANDLING}),
                            )
                        await finish("scene_result_draft", "场景图已生成，等待人工确认")
                        return
                    await first_response("scene_result")
                    await stage("sending_response", "发送场景图")
                    await send_scene_generation_result(language, record, outbound)
                    await clear_scene_state(conversation_id)
                    await finish("scene_result", "场景图已发送")
                    return

        if scene_req.get("is_scene_request"):
            await stage("resolving_product_reference")
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
                    stop_typing.set()
                    await typing_task
                    if service_mode != "ai_assist":
                        generating = SCENE_GENERATING_MESSAGES.get(language, SCENE_GENERATING_MESSAGES["en"])
                        await first_response("scene_generating_notice")
                        await outbound.reply_text(generating)
                        await save_message(conversation_id, MessageRole.ASSISTANT, generating, language)
                    try:
                        await stage("scene_image_generation", scene_req.get("scene_name") or primary_product.space or "")
                        record = await generate_scene_images(
                            primary_product=primary_product,
                            all_products=all_products,
                            user_request=user_message,
                            scene_name=scene_req.get("scene_name") or primary_product.space,
                            style_hint=scene_req.get("style_hint") or primary_product.style,
                            conversation_id=conversation_id,
                            timeout_seconds=CUSTOMER_SCENE_TIMEOUT_SECONDS,
                        )
                    except asyncio.TimeoutError:
                        timeout_text = SCENE_TIMEOUT_MESSAGES.get(language, SCENE_TIMEOUT_MESSAGES["en"])
                        await first_response("scene_timeout")
                        if service_mode == "ai_assist":
                            await create_pending_ai_reply(conversation_id, timeout_text, language)
                        else:
                            await outbound.reply_text(timeout_text)
                            await save_message(conversation_id, MessageRole.ASSISTANT, timeout_text, language)
                        await complete_turn_metric(metric_id, response_kind="scene_timeout", success=False, error_message="Scene generation timed out")
                        await mark_conversation_failed(conversation_id, "场景图生成超时")
                        return
                    if service_mode == "ai_assist":
                        if record.status != "completed":
                            failed_text = SCENE_FAILED_MESSAGES.get(language, SCENE_FAILED_MESSAGES["en"])
                            await first_response("scene_failed")
                            await create_pending_ai_reply(conversation_id, failed_text, language)
                            if run_notify_admin and notify_bot and conversation:
                                await notify_admin(
                                    bot_id,
                                    conversation,
                                    user_message,
                                    notify_bot,
                                    is_followup=(current_status in {ConversationStatus.PENDING_HUMAN, ConversationStatus.HUMAN_HANDLING}),
                                )
                            await complete_turn_metric(metric_id, response_kind="scene_failed", success=False, error_message=record.error_message or "Scene generation failed")
                            await mark_conversation_failed(conversation_id, "场景图生成失败")
                            return
                        async with AsyncSessionLocal() as db:
                            current_record = await db.get(type(record), record.id)
                            if current_record:
                                current_record.deferred_delivery = True
                                await db.commit()
                        scene_delivery = await build_scene_result_delivery(record, language)
                        scene_delivery["record_id"] = record.id
                        scene_delivery["scene_state_action"] = "save"
                        scene_delivery["scene_state_payload"] = {
                            "primary_product_id": primary_product.id,
                            "recommended_product_ids": [primary_product.id],
                            "suggested_scene": scene_req.get("scene_name") or primary_product.space,
                            "suggested_style": scene_req.get("style_hint") or primary_product.style,
                            "pending_confirmation": False,
                            "reply_language": language,
                            "last_customer_request": user_message,
                        }
                        preview_text = f"{scene_delivery.get('intro_text', '')}\n\n{scene_delivery.get('preview_line', '')}".strip()
                        await stage("creating_ai_draft", "场景图待确认")
                        await first_response("scene_result_draft")
                        await create_pending_ai_delivery(
                            conversation_id=conversation_id,
                            draft_text=preview_text,
                            language=language,
                            content_kind="scene_result",
                            payload=scene_delivery,
                        )
                        if run_notify_admin and notify_bot and conversation:
                            await notify_admin(
                                bot_id,
                                conversation,
                                user_message,
                                notify_bot,
                                is_followup=(current_status in {ConversationStatus.PENDING_HUMAN, ConversationStatus.HUMAN_HANDLING}),
                            )
                        await finish("scene_result_draft", "场景图已生成，等待人工确认")
                        return
                    await first_response("scene_result")
                    await stage("sending_response", "发送场景图")
                    await send_scene_generation_result(language, record, outbound)
                    await save_scene_state(
                        conversation_id=conversation_id,
                        primary_product_id=primary_product.id,
                        recommended_product_ids=[primary_product.id],
                        suggested_scene=scene_req.get("scene_name") or primary_product.space,
                        suggested_style=scene_req.get("style_hint") or primary_product.style,
                        pending_confirmation=False,
                        reply_language=language,
                        last_customer_request=user_message,
                    )
                    await finish("scene_result", "场景图已发送")
                    return

        await stage("checking_product_recommendation")
        is_product_rec = (
            intent_name == "product_recommendation"
            or "product_recommendation" in secondary_intents
        ) and intent_confidence >= 0.55
        logger.info(f"[Bot {bot_id}] Product recommendation: {is_product_rec}")
        if is_product_rec:
            await stage("product_matching")
            selected_ids = await ai_select_products(user_message, all_products) if all_products else []
            products_by_id = {p["id"]: p for p in all_products}
            selected_products = [products_by_id[pid] for pid in selected_ids if pid in products_by_id]
            intro = PRODUCT_REC_INTRO.get(language, PRODUCT_REC_INTRO["en"])
            none_msg = PRODUCT_REC_NONE.get(language, PRODUCT_REC_NONE["en"])
            stop_typing.set()
            await typing_task
            if selected_products:
                if service_mode == "ai_assist":
                    primary_product = selected_products[0]
                    suggested_scene = select_default_scene(selected_products, language)
                    followup = build_scene_followup_message(language, selected_products)
                    delivery = build_product_recommendation_delivery(selected_products, language)
                    delivery["intro_text"] = intro
                    delivery["followup_text"] = followup
                    delivery["scene_state"] = {
                        "primary_product_id": primary_product["id"],
                        "recommended_product_ids": selected_ids,
                        "suggested_scene": suggested_scene,
                        "suggested_style": primary_product.get("style", ""),
                        "pending_confirmation": True,
                        "reply_language": language,
                        "last_customer_request": user_message,
                    }
                    preview_text = "\n".join([intro, *delivery.get("preview_lines", []), "", followup]).strip()
                    await stage("creating_ai_draft", "商品推荐待确认")
                    await first_response("product_recommendation_draft")
                    await create_pending_ai_delivery(
                        conversation_id=conversation_id,
                        draft_text=preview_text,
                        language=language,
                        content_kind="product_recommendation",
                        payload=delivery,
                    )
                    if run_notify_admin and notify_bot and conversation:
                        await notify_admin(
                            bot_id,
                            conversation,
                            user_message,
                            notify_bot,
                            is_followup=(current_status in {ConversationStatus.PENDING_HUMAN, ConversationStatus.HUMAN_HANDLING}),
                        )
                    logger.info(f"[Bot {bot_id}] Queued {len(selected_products)} product recommendations for human confirmation")
                    await finish("product_recommendation_draft", "商品推荐已生成，等待人工确认")
                    return
                await first_response("product_recommendation")
                await stage("sending_response", "发送商品推荐")
                await outbound.reply_text(intro)
                await save_message(conversation_id, MessageRole.ASSISTANT, intro, language)
                await send_product_recommendations(selected_products, language, outbound)
                primary_product = selected_products[0]
                suggested_scene = select_default_scene(selected_products, language)
                followup = build_scene_followup_message(language, selected_products)
                await outbound.reply_text(followup)
                await save_message(conversation_id, MessageRole.ASSISTANT, followup, language)
                await save_scene_state(
                    conversation_id=conversation_id,
                    primary_product_id=primary_product["id"],
                    recommended_product_ids=selected_ids,
                    suggested_scene=suggested_scene,
                    suggested_style=primary_product.get("style", ""),
                    pending_confirmation=True,
                    reply_language=language,
                    last_customer_request=user_message,
                )
                logger.info(f"[Bot {bot_id}] Sent {len(selected_products)} product recommendations")
                await finish("product_recommendation", "商品推荐已发送")
            else:
                await first_response("product_not_found")
                if service_mode == "ai_assist":
                    await create_pending_ai_reply(conversation_id, none_msg, language)
                    if run_notify_admin and notify_bot and conversation:
                        await notify_admin(
                            bot_id,
                            conversation,
                            user_message,
                            notify_bot,
                            is_followup=(current_status in {ConversationStatus.PENDING_HUMAN, ConversationStatus.HUMAN_HANDLING}),
                        )
                else:
                    await outbound.reply_text(none_msg)
                    await save_message(conversation_id, MessageRole.ASSISTANT, none_msg, language)
                await clear_scene_state(conversation_id)
                await finish("product_not_found", "未找到匹配商品")
            return

        await stage("knowledge_retrieval")
        kb_context = await search_knowledge_for_bot(user_message)

        await stage("file_matching")
        all_files = await get_all_file_entries()
        is_file_request = (
            intent_name == "file_request"
            or "file_request" in secondary_intents
        ) and intent_confidence >= 0.6
        router_file_ids = intent_slots.get("file_ids")
        matched_file_ids = [
            int(x) for x in router_file_ids
            if isinstance(x, (int, float, str)) and str(x).strip().isdigit()
        ] if isinstance(router_file_ids, list) else []
        if matched_file_ids:
            valid_file_ids = {int(f["id"]) for f in all_files if f.get("id") is not None}
            matched_file_ids = [fid for fid in matched_file_ids if fid in valid_file_ids]
        if is_file_request and all_files and not matched_file_ids:
            matched_file_ids = await check_file_request(user_message, all_files)

        file_info = ""
        if matched_file_ids:
            matched_entries = [f for f in all_files if f["id"] in matched_file_ids]
            file_info = "\n".join(f"- {f['name']}: {f['description']}" for f in matched_entries)

        await stage("loading_chat_history")
        chat_history = await get_chat_history(conversation_id)
        repeated_question = _is_repeated_user_question(chat_history, user_message)

        edge_notes: list[str] = []
        if repeated_question:
            edge_notes.append("The customer has repeated the same question. Explain it in a different way, be more concrete, and offer another path or human support if needed.")
        if topic_switch:
            edge_notes.append("The customer switched topics from a pending scene-image confirmation. Acknowledge the new topic briefly before answering it.")
        if secondary_intents:
            edge_notes.append("The customer may have asked multiple things. Address the primary intent first and briefly say what can be handled next.")
        if edge_notes:
            notes = "\n".join(f"- {note}" for note in edge_notes)
            file_info = f"{file_info}\n\nConversation handling notes:\n{notes}".strip()

        logger.info(f"[Bot {bot_id}] Generating AI response...")
        await stage("llm_generating_answer")
        response_text = await generate_response(
            user_message=user_message,
            context=kb_context,
            language=language,
            chat_history=chat_history,
            file_info=file_info,
        )
        prefix = ""
        if topic_switch:
            prefix += TOPIC_SWITCH_PREFIX.get(language, TOPIC_SWITCH_PREFIX["en"])
        if repeated_question:
            prefix += REPEATED_QUESTION_PREFIX.get(language, REPEATED_QUESTION_PREFIX["en"])
        if prefix:
            response_text = f"{prefix}{response_text}"
        logger.info(f"[Bot {bot_id}] AI response generated ({len(response_text)} chars)")

        stop_typing.set()
        await typing_task
        if service_mode == "ai_assist":
            await stage("creating_ai_draft", "普通文本待确认")
            await first_response("text_draft")
            await create_pending_ai_reply(conversation_id, response_text, language)
            if run_notify_admin and notify_bot and conversation:
                await notify_admin(
                    bot_id,
                    conversation,
                    user_message,
                    notify_bot,
                    is_followup=(current_status in {ConversationStatus.PENDING_HUMAN, ConversationStatus.HUMAN_HANDLING}),
                )
            await finish("text_draft", "AI 回复已生成，等待人工确认")
            return

        await first_response("text")
        await stage("sending_response", "发送文本回复")
        await save_message(conversation_id, MessageRole.ASSISTANT, response_text, language)
        await outbound.reply_text(response_text)

        if matched_file_ids:
            await send_files_to_user(matched_file_ids, outbound)
        await finish("text", "回复已发送")
    except Exception as e:
        stop_typing.set()
        await typing_task
        logger.error(f"[Bot {bot_id}] Error processing message: {e}", exc_info=True)
        await complete_turn_metric(metric_id, response_kind="error", success=False, error_message=str(e))
        await mark_conversation_failed(conversation_id, str(e))
        fallback = {
            "zh": "抱歉，系统暂时出现问题，请稍后再试或联系人工客服。",
            "en": "Sorry, the system is temporarily unavailable. Please try again later.",
        }
        try:
            await outbound.reply_text(fallback.get(language, fallback["en"]))
        except Exception:
            logger.error(f"[Bot {bot_id}] Failed to send fallback message", exc_info=True)


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

        await set_conversation_stage(conversation.id, "detecting_language")
        try:
            detected_language = await detect_language(user_message)
            logger.info(f"[Bot {bot_id}] Detected language: {detected_language}")
        except Exception as e:
            logger.error(f"[Bot {bot_id}] Language detection failed: {e}", exc_info=True)
            detected_language = conversation.language or "en"

        scene_state = await get_scene_state(conversation.id)
        language = resolve_turn_language(
            user_message=user_message,
            detected_language=detected_language,
            conversation_language=conversation.language,
            scene_reply_language=scene_state.reply_language if scene_state else None,
        )
        logger.info(f"[Bot {bot_id}] Effective reply language: {language}")

        try:
            async with AsyncSessionLocal() as db:
                conv = await db.get(Conversation, conversation.id)
                if conv:
                    conv.language = language
                    await db.commit()
        except Exception as e:
            logger.error(f"[Bot {bot_id}] Failed to update language: {e}", exc_info=True)

        user_message_id = await save_message(conversation.id, MessageRole.USER, user_message, language)
        metric_id = await start_turn_metric(
            conversation.id,
            user_message_id=user_message_id,
            request_text=user_message,
        )

        async with AsyncSessionLocal() as db:
            fresh_conv = await db.get(Conversation, conversation.id)
            current_status = fresh_conv.status if fresh_conv else conversation.status

        stop_typing = asyncio.Event()
        typing_task = asyncio.create_task(
            keep_typing(int(chat_id), context.bot, stop_typing)
        )
        outbound = TelegramOutbound(int(chat_id), context.bot)
        await process_customer_text_message(
            bot_id=bot_id,
            conversation_id=conversation.id,
            user_message=user_message,
            language=language,
            current_status=current_status,
            outbound=outbound,
            run_notify_admin=True,
            notify_bot=context.bot,
            stop_typing=stop_typing,
            typing_task=typing_task,
            metric_id=metric_id,
        )

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
