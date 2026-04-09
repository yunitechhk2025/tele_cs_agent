from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MessageSchema(BaseModel):
    id: int
    conversation_id: int
    role: str
    content: str
    language: Optional[str] = None
    attachment_file_id: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationSchema(BaseModel):
    id: int
    bot_id: Optional[int] = None
    telegram_chat_id: str
    telegram_user_id: str
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    language: str
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ConversationDetailSchema(ConversationSchema):
    messages: list[MessageSchema] = []


class ReplyRequest(BaseModel):
    content: str


class KnowledgeEntrySchema(BaseModel):
    id: int
    title: str
    content: str
    source: Optional[str] = None
    category: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class KnowledgeCreateRequest(BaseModel):
    title: str
    content: str
    source: Optional[str] = None
    category: Optional[str] = None


class ContractSchema(BaseModel):
    id: int
    conversation_id: int
    title: str
    content: str
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ContractUpdateRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    status: Optional[str] = None


class ContractGenerateRequest(BaseModel):
    conversation_id: int
    template_id: Optional[int] = None
    language: Optional[str] = None


class SendContractRequest(BaseModel):
    contract_id: int


class ContractTemplateSchema(BaseModel):
    id: int
    name: str
    description: str
    original_name: str
    file_size: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DashboardStats(BaseModel):
    total_conversations: int
    active_conversations: int
    pending_human: int
    total_messages: int
    total_knowledge_entries: int
    total_contracts: int
    total_files: int
    total_bots: int
    active_bots: int
    recent_conversations: list[ConversationSchema]


# ─── LLM Settings ────────────────────────────────────────────────────────────

class LLMSettingsSchema(BaseModel):
    provider: str = "openai"
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o"
    embedding_model: str = "text-embedding-3-small"
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_api_key: str = ""
    image_model: str = "gpt-image-1"
    image_base_url: str = "https://api.openai.com/v1"
    image_api_key: str = ""
    image_size: str = "1536x1024"
    image_quality: str = "high"
    image_style: str = "natural"
    temperature: float = 0.7
    max_tokens: int = 1000


class LLMSettingsUpdateRequest(BaseModel):
    provider: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    embedding_model: Optional[str] = None
    embedding_base_url: Optional[str] = None
    embedding_api_key: Optional[str] = None
    image_model: Optional[str] = None
    image_base_url: Optional[str] = None
    image_api_key: Optional[str] = None
    image_size: Optional[str] = None
    image_quality: Optional[str] = None
    image_style: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


# ─── File Library ─────────────────────────────────────────────────────────────

class FileEntrySchema(BaseModel):
    id: int
    filename: str
    original_name: str
    file_size: int
    mime_type: Optional[str] = None
    description: str
    tags: str
    category: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class FileEntryUpdateRequest(BaseModel):
    description: Optional[str] = None
    tags: Optional[str] = None
    category: Optional[str] = None


# ─── Telegram Bot Management ─────────────────────────────────────────────────

class TelegramBotSchema(BaseModel):
    id: int
    name: str
    token_masked: str
    admin_chat_id: str
    welcome_message: str
    is_active: bool
    bot_username: Optional[str] = None
    description: str
    is_running: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TelegramBotCreateRequest(BaseModel):
    name: str
    token: str
    admin_chat_id: str = ""
    welcome_message: str = ""
    is_active: bool = True
    description: str = ""


class TelegramBotUpdateRequest(BaseModel):
    name: Optional[str] = None
    token: Optional[str] = None
    admin_chat_id: Optional[str] = None
    welcome_message: Optional[str] = None
    is_active: Optional[bool] = None
    description: Optional[str] = None


class ProductImageSchema(BaseModel):
    id: int
    product_entry_id: int
    local_path: str
    display_order: int
    created_at: datetime

    class Config:
        from_attributes = True


class ProductEntrySchema(BaseModel):
    id: int
    brand: str
    product_id_ext: str
    product_name: str
    series_name: str
    space: str
    style: str
    color: str
    material: str
    size: str
    price_display: str
    original_price: str
    serial_number: str
    description_text: str
    detail_content_text: str
    buy_url: str
    detail_url: str
    created_at: datetime
    updated_at: datetime
    images: list[ProductImageSchema] = []

    class Config:
        from_attributes = True


class ProductEntryListSchema(BaseModel):
    id: int
    brand: str
    product_id_ext: str
    product_name: str
    series_name: str
    space: str
    style: str
    color: str
    material: str
    size: str
    price_display: str
    serial_number: str
    description_text: str
    buy_url: str
    first_image_path: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProductLinkSchema(BaseModel):
    id: int
    product_name: str
    brand: str = ""
    buy_url: str
    detail_url: str


class SceneGenerationRequest(BaseModel):
    scene_name: Optional[str] = None
    style_hint: Optional[str] = None
    user_request: Optional[str] = None
    related_product_ids: list[int] = []
    conversation_id: Optional[int] = None


class SceneGenerationRecordSchema(BaseModel):
    id: int
    conversation_id: Optional[int] = None
    primary_product_id: int
    primary_product_name: str
    scene_name: str
    style_hint: str
    request_text: str
    prompt_text: str
    related_products: list[ProductLinkSchema] = []
    image_urls: list[str] = []
    duration_ms: int
    status: str
    in_library: bool = False
    error_message: str
    created_at: datetime
    updated_at: datetime


class ProductImageRef(BaseModel):
    product_id: int
    image_order: int = 0


class SceneGeneratorRequest(BaseModel):
    product_image_refs: list[ProductImageRef]
    scene_name: Optional[str] = None
    style_hint: Optional[str] = None
    user_request: Optional[str] = None


class SceneLibraryItemSchema(BaseModel):
    id: int
    conversation_id: Optional[int] = None
    primary_product_id: int
    primary_product_name: str
    primary_product_brand: str = ""
    primary_product_space: str = ""
    primary_product_style: str = ""
    scene_name: str
    style_hint: str
    request_text: str = ""
    related_products: list[ProductLinkSchema] = []
    image_urls: list[str] = []
    cover_url: str = ""
    duration_ms: int
    status: str = ""
    in_library: bool = False
    error_message: str = ""
    created_at: datetime
    updated_at: datetime
