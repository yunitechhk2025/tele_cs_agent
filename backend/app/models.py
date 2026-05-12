import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, BigInteger, Boolean, ForeignKey, Enum as SQLEnum, LargeBinary, Float, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from app.database import Base


class ConversationStatus(str, enum.Enum):
    ACTIVE = "active"
    PENDING_HUMAN = "pending_human"
    HUMAN_HANDLING = "human_handling"
    CLOSED = "closed"


class MessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"
    HUMAN_AGENT = "human_agent"


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key = Column(String(255), primary_key=True)
    value = Column(Text, default="")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TelegramBot(Base):
    __tablename__ = "telegram_bots"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    token = Column(String(500), nullable=False, unique=True)
    admin_chat_id = Column(String(64), default="")
    welcome_message = Column(Text, default="")
    is_active = Column(Boolean, default=True)
    bot_username = Column(String(255), nullable=True)
    description = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    conversations = relationship("Conversation", back_populates="bot")


class FileEntry(Base):
    __tablename__ = "file_entries"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(500))
    original_name = Column(String(500))
    file_path = Column(String(1000))
    file_size = Column(BigInteger, default=0)
    mime_type = Column(String(200), nullable=True)
    description = Column(Text, default="")
    tags = Column(String(1000), default="")
    category = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    bot_id = Column(Integer, ForeignKey("telegram_bots.id"), nullable=True, index=True)
    telegram_chat_id = Column(String(64), index=True)
    telegram_user_id = Column(String(64), index=True)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    language = Column(String(10), default="en")
    quote_language = Column(String(10), nullable=True)
    status = Column(SQLEnum(ConversationStatus), default=ConversationStatus.ACTIVE)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    bot = relationship("TelegramBot", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", order_by="Message.created_at")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), index=True)
    role = Column(SQLEnum(MessageRole))
    content = Column(Text)
    language = Column(String(10), nullable=True)
    attachment_file_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="messages")


class KnowledgeEntry(Base):
    __tablename__ = "knowledge_entries"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(500))
    content = Column(Text)
    source = Column(String(500), nullable=True)
    category = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Contract(Base):
    __tablename__ = "contracts"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"))
    title = Column(String(500))
    content = Column(Text)
    status = Column(String(50), default="draft")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    conversation = relationship("Conversation")


class ContractTemplate(Base):
    __tablename__ = "contract_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(500), nullable=False)
    description = Column(Text, default="")
    filename = Column(String(500))
    original_name = Column(String(500))
    file_path = Column(String(1000))
    file_size = Column(BigInteger, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ProductEntry(Base):
    __tablename__ = "product_entries"

    id = Column(Integer, primary_key=True, index=True)
    brand = Column(String(100), nullable=False, index=True)
    product_id_ext = Column(String(64), nullable=False, index=True)
    product_name = Column(String(500), default="")
    series_name = Column(String(500), default="")
    space = Column(String(200), default="")
    style = Column(String(200), default="")
    color = Column(String(200), default="")
    material = Column(String(500), default="")
    size = Column(String(500), default="")
    price_display = Column(String(200), default="")
    original_price = Column(String(200), default="")
    serial_number = Column(String(200), default="")
    description_text = Column(Text, default="")
    detail_content_text = Column(Text, default="")
    buy_url = Column(String(1000), default="")
    detail_url = Column(String(1000), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    images = relationship("ProductImage", back_populates="product", order_by="ProductImage.display_order")


class ProductImage(Base):
    __tablename__ = "product_images"

    id = Column(Integer, primary_key=True, index=True)
    product_entry_id = Column(Integer, ForeignKey("product_entries.id"), index=True, nullable=False)
    local_path = Column(String(1000), nullable=False)
    source_url = Column(String(2000), default="")
    display_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("ProductEntry", back_populates="images")


class ConversationSceneState(Base):
    __tablename__ = "conversation_scene_states"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), unique=True, index=True, nullable=False)
    primary_product_id = Column(Integer, ForeignKey("product_entries.id"), nullable=True)
    recommended_product_ids_json = Column(Text, default="[]")
    suggested_scene = Column(String(200), default="")
    suggested_style = Column(String(200), default="")
    pending_confirmation = Column(Boolean, default=False)
    last_customer_request = Column(Text, default="")
    reply_language = Column(String(10), default="en")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    conversation = relationship("Conversation")
    primary_product = relationship("ProductEntry")


class ConversationProcessingState(Base):
    __tablename__ = "conversation_processing_states"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), unique=True, index=True, nullable=False)
    stage_key = Column(String(100), default="idle")
    stage_label = Column(String(200), default="空闲")
    stage_detail = Column(Text, default="")
    is_processing = Column(Boolean, default=False)
    started_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    conversation = relationship("Conversation")


class ConversationTurnMetric(Base):
    __tablename__ = "conversation_turn_metrics"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), index=True, nullable=False)
    user_message_id = Column(Integer, ForeignKey("messages.id"), nullable=True, index=True)
    request_text = Column(Text, default="")
    primary_intent = Column(String(100), default="")
    secondary_intents_json = Column(Text, default="[]")
    intent_confidence = Column(Float, nullable=True)
    intent_source = Column(String(50), default="")
    intent_reason = Column(Text, default="")
    response_kind = Column(String(100), default="")
    started_at = Column(DateTime, default=datetime.utcnow)
    first_response_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    first_response_ms = Column(Integer, nullable=True)
    total_ms = Column(Integer, nullable=True)
    success = Column(Boolean, default=True)
    error_message = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("Conversation")
    user_message = relationship("Message")


class ConversationTurnStepMetric(Base):
    __tablename__ = "conversation_turn_step_metrics"

    id = Column(Integer, primary_key=True, index=True)
    turn_metric_id = Column(Integer, ForeignKey("conversation_turn_metrics.id"), index=True, nullable=False)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), index=True, nullable=False)
    step_index = Column(Integer, default=0)
    stage_key = Column(String(100), default="")
    stage_label = Column(String(200), default="")
    stage_detail = Column(Text, default="")
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    success = Column(Boolean, default=True)
    error_message = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    turn_metric = relationship("ConversationTurnMetric")
    conversation = relationship("Conversation")


class PendingAIReply(Base):
    __tablename__ = "pending_ai_replies"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), unique=True, index=True, nullable=False)
    draft_text = Column(Text, default="")
    final_text = Column(Text, default="")
    language = Column(String(10), default="en")
    content_kind = Column(String(50), default="text")
    payload_json = Column(Text, default="{}")
    status = Column(String(50), default="pending")
    auto_send_at = Column(DateTime, nullable=False)
    auto_send_paused = Column(Boolean, default=False)
    sent_at = Column(DateTime, nullable=True)
    error_message = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    conversation = relationship("Conversation")


class SceneGenerationRecord(Base):
    __tablename__ = "scene_generation_records"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=True, index=True)
    primary_product_id = Column(Integer, ForeignKey("product_entries.id"), nullable=False, index=True)
    scene_name = Column(String(200), default="")
    style_hint = Column(String(200), default="")
    request_text = Column(Text, default="")
    prompt_text = Column(Text, default="")
    related_product_ids_json = Column(Text, default="[]")
    output_paths_json = Column(Text, default="[]")
    duration_ms = Column(Integer, default=0)
    status = Column(String(50), default="pending")
    deferred_delivery = Column(Boolean, default=False)
    in_library = Column(Boolean, default=False)
    error_message = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    conversation = relationship("Conversation")
    primary_product = relationship("ProductEntry")
    images = relationship("SceneGenerationImage", back_populates="record", order_by="SceneGenerationImage.image_index")


class SceneGenerationImage(Base):
    __tablename__ = "scene_generation_images"

    id = Column(Integer, primary_key=True, index=True)
    record_id = Column(Integer, ForeignKey("scene_generation_records.id"), nullable=False, index=True)
    image_index = Column(Integer, default=0, nullable=False)
    mime_type = Column(String(100), default="image/png")
    binary_data = Column(LargeBinary, nullable=False)
    file_size = Column(BigInteger, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    record = relationship("SceneGenerationRecord", back_populates="images")


class MessageTranslation(Base):
    """缓存对话时间线条目的翻译结果。

    source_kind: "msg" 表示 Message 表里的消息，"evt" 表示 ConversationOutboundEvent。
    source_id:   对应表的主键 id。
    target_lang: 译入语言（如 "zh"、"zh-TW"、"en"）。
    text:        翻译后的文本。

    通过 (source_kind, source_id, target_lang) 唯一索引，避免重复落库。
    新消息只翻一次，之后切换会话/刷新页面直接命中缓存。"""

    __tablename__ = "message_translations"
    __table_args__ = (
        UniqueConstraint(
            "source_kind", "source_id", "target_lang",
            name="uq_message_translations_src_lang",
        ),
        Index(
            "ix_message_translations_src",
            "source_kind", "source_id",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    source_kind = Column(String(8), nullable=False)
    source_id = Column(Integer, nullable=False)
    target_lang = Column(String(16), nullable=False)
    text = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ConversationOutboundEvent(Base):
    __tablename__ = "conversation_outbound_events"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), index=True, nullable=False)
    role = Column(String(50), default="assistant")
    event_type = Column(String(50), default="text")
    text = Column(Text, default="")
    caption = Column(Text, default="")
    url = Column(String(2000), default="")
    filename = Column(String(500), default="")
    parse_mode = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("Conversation")
