import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, BigInteger, Boolean, ForeignKey, Enum as SQLEnum
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
    display_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("ProductEntry", back_populates="images")
