from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


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
    language: str | None = None
    attachment_file_id: int | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationSchema(BaseModel):
    id: int
    bot_id: int | None = None
    telegram_chat_id: str
    telegram_user_id: str
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    language: str
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ConversationProcessingStateSchema(BaseModel):
    stage_key: str = "idle"
    stage_label: str = "空闲"
    stage_detail: str = ""
    is_processing: bool = False
    started_at: datetime | None = None
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class ConversationTurnMetricSchema(BaseModel):
    id: int
    conversation_id: int
    user_message_id: int | None = None
    request_text: str = ""
    primary_intent: str = ""
    secondary_intents_json: str = "[]"
    intent_confidence: float | None = None
    intent_source: str = ""
    intent_reason: str = ""
    response_kind: str = ""
    started_at: datetime
    first_response_at: datetime | None = None
    completed_at: datetime | None = None
    first_response_ms: int | None = None
    total_ms: int | None = None
    success: bool = True
    error_message: str = ""
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationTurnStepMetricSchema(BaseModel):
    id: int
    turn_metric_id: int
    conversation_id: int
    step_index: int = 0
    stage_key: str = ""
    stage_label: str = ""
    stage_detail: str = ""
    metadata_json: str = "{}"
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = None
    success: bool = True
    error_message: str = ""
    created_at: datetime

    class Config:
        from_attributes = True


class ObservabilityKpisSchema(BaseModel):
    total_turns: int = 0
    success_count: int = 0
    failed_count: int = 0
    success_rate: float = 0.0
    failure_rate: float = 0.0
    first_response_p50_ms: int | None = None
    first_response_p95_ms: int | None = None
    first_response_p99_ms: int | None = None
    total_p50_ms: int | None = None
    total_p95_ms: int | None = None
    total_p99_ms: int | None = None
    text_first_response_p95_ms: int | None = None
    product_recommendation_first_response_p95_ms: int | None = None
    handoff_count: int = 0
    handoff_rate: float = 0.0
    profile_handoff_count: int = 0
    profile_handoff_rate: float = 0.0
    rag_lookup_count: int = 0
    rag_empty_count: int = 0
    rag_empty_rate: float = 0.0
    llm_call_count: int = 0
    llm_failure_count: int = 0
    llm_failure_rate: float = 0.0
    scene_generation_count: int = 0
    scene_failure_count: int = 0
    scene_failure_rate: float = 0.0


class ObservabilityStageMetricSchema(BaseModel):
    stage_key: str
    stage_label: str
    count: int
    avg_ms: int
    p50_ms: int | None = None
    p95_ms: int | None = None
    p99_ms: int | None = None
    failed_count: int = 0


class ObservabilityStageTrendPointSchema(BaseModel):
    bucket_start: datetime
    bucket_label: str
    count: int
    avg_ms: int
    p50_ms: int | None = None
    p95_ms: int | None = None
    p99_ms: int | None = None


class ObservabilityStageTrendSeriesSchema(BaseModel):
    stage_key: str
    stage_label: str
    count: int
    avg_ms: int
    p50_ms: int | None = None
    p95_ms: int | None = None
    p99_ms: int | None = None
    points: list[ObservabilityStageTrendPointSchema] = []


class ObservabilityIntentStageTrendSchema(BaseModel):
    intent: str
    intent_label: str
    stages: list[ObservabilityStageTrendSeriesSchema] = []


class ObservabilityStageTrendResponseSchema(BaseModel):
    granularity: str
    window_start: datetime | None = None
    window_end: datetime | None = None
    intents: list[ObservabilityIntentStageTrendSchema] = []


class ObservabilityLLMMetricSchema(BaseModel):
    operation: str
    model: str
    count: int
    failed_count: int
    failure_rate: float
    avg_ms: int
    p50_ms: int | None = None
    p95_ms: int | None = None
    p99_ms: int | None = None
    last_error: str = ""


class ObservabilityFailureSampleSchema(BaseModel):
    source: str = "turn"
    conversation_id: int | None = None
    turn_metric_id: int | None = None
    language: str = ""
    primary_intent: str = ""
    response_kind: str = ""
    error_message: str = ""
    created_at: datetime | None = None


class ObservabilitySummarySchema(BaseModel):
    kpis: ObservabilityKpisSchema
    stage_metrics: list[ObservabilityStageMetricSchema] = []
    slowest_stages: list[ObservabilityStageMetricSchema] = []
    llm_metrics: list[ObservabilityLLMMetricSchema] = []
    recent_failures: list[ObservabilityFailureSampleSchema] = []


class ObservabilityAlertSchema(BaseModel):
    id: int
    severity: str
    metric_key: str
    title: str
    message: str
    observed_value: float
    threshold_value: float
    window_start: datetime
    window_end: datetime
    status: str
    dedupe_key: str
    sample_conversation_ids_json: str = "[]"
    sample_count: int = 0
    sent_at: datetime | None = None
    acknowledged_at: datetime | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class ObservabilityAlertSettingsSchema(BaseModel):
    text_first_response_p95_ms: int = 8000
    product_recommendation_first_response_p95_ms: int = 12000
    scene_failure_rate: float = 0.2
    llm_failure_rate: float = 0.1
    turn_failure_rate: float = 0.05
    rag_empty_rate: float = 0.4
    profile_handoff_rate: float = 0.15


class ConversationDetailSchema(ConversationSchema):
    messages: list[MessageSchema] = []
    outbound_events: list["TelegramSimulatorEventSchema"] = []
    processing_state: ConversationProcessingStateSchema | None = None
    latest_turn_metric: ConversationTurnMetricSchema | None = None
    turn_metrics: list[ConversationTurnMetricSchema] = []
    latest_turn_steps: list[ConversationTurnStepMetricSchema] = []
    ai_draft: Optional["PendingAIReplySchema"] = None


class ReplyRequest(BaseModel):
    content: str


class PendingAIReplySchema(BaseModel):
    id: int
    conversation_id: int
    draft_text: str
    final_text: str = ""
    language: str
    content_kind: str = "text"
    payload_json: dict[str, Any] = Field(default_factory=dict)
    status: str
    auto_send_at: datetime
    auto_send_paused: bool = False
    sent_at: datetime | None = None
    error_message: str = ""
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SendPendingAIReplyRequest(BaseModel):
    content: str | None = None
    send_as_human_agent: bool = False


class CustomerServiceSettingsSchema(BaseModel):
    feature_name: str = "客服应答模式"
    mode: str = "ai_auto"
    auto_send_seconds: int = 10


class CustomerServiceSettingsUpdateRequest(BaseModel):
    mode: str
    auto_send_seconds: int | None = None


class KnowledgeEntrySchema(BaseModel):
    id: int
    title: str
    content: str
    source: str | None = None
    category: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class KnowledgeCreateRequest(BaseModel):
    title: str
    content: str
    source: str | None = None
    category: str | None = None


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
    title: str | None = None
    content: str | None = None
    status: str | None = None


class ContractGenerateRequest(BaseModel):
    conversation_id: int
    template_id: int | None = None
    language: str | None = None


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


class TelegramSimulatorSessionCreate(BaseModel):
    bot_id: int
    language: str | None = "zh-Hans"


class TelegramSimulatorSessionResponse(BaseModel):
    conversation_id: int
    telegram_chat_id: str


class TelegramSimulatorSendRequest(BaseModel):
    text: str


class TelegramSimulatorSendResponse(BaseModel):
    conversation_id: int
    outgoing: list[dict[str, Any]] = Field(default_factory=list)


class TelegramSimulatorEventSchema(BaseModel):
    id: str
    role: str
    type: str
    text: str | None = None
    caption: str | None = None
    url: str | None = None
    filename: str | None = None
    parse_mode: str | None = None
    created_at: datetime


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
    image_size: str = "1024x1024"
    image_quality: str = "high"
    image_style: str = "natural"
    profile_provider: str = ""
    profile_api_key: str = ""
    profile_base_url: str = ""
    profile_model: str = ""
    profile_temperature: float = 0.0
    profile_max_tokens: int = 500
    profile_timeout_seconds: float = 4.0
    temperature: float = 0.7
    max_tokens: int = 1000


class LLMSettingsUpdateRequest(BaseModel):
    provider: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    embedding_model: str | None = None
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None
    image_model: str | None = None
    image_base_url: str | None = None
    image_api_key: str | None = None
    image_size: str | None = None
    image_quality: str | None = None
    image_style: str | None = None
    profile_provider: str | None = None
    profile_api_key: str | None = None
    profile_base_url: str | None = None
    profile_model: str | None = None
    profile_temperature: float | None = None
    profile_max_tokens: int | None = None
    profile_timeout_seconds: float | None = None
    temperature: float | None = None
    max_tokens: int | None = None


# ─── File Library ─────────────────────────────────────────────────────────────


class FileEntrySchema(BaseModel):
    id: int
    filename: str
    original_name: str
    file_size: int
    mime_type: str | None = None
    description: str
    tags: str
    category: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class FileEntryUpdateRequest(BaseModel):
    description: str | None = None
    tags: str | None = None
    category: str | None = None


# ─── Telegram Bot Management ─────────────────────────────────────────────────


class TelegramBotSchema(BaseModel):
    id: int
    name: str
    token_masked: str
    admin_chat_id: str
    welcome_message: str
    is_active: bool
    bot_username: str | None = None
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
    name: str | None = None
    token: str | None = None
    admin_chat_id: str | None = None
    welcome_message: str | None = None
    is_active: bool | None = None
    description: str | None = None


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
    primary_category: str = ""
    secondary_categories_json: str = "[]"
    normalized_brand: str = ""
    normalized_space: str = ""
    normalized_style: str = ""
    normalized_color: str = ""
    normalized_materials_json: str = "[]"
    category_confidence: float = 0.0
    classification_source: str = ""
    classification_reason: str = ""
    translations: dict[str, dict[str, str]] = Field(default_factory=dict)
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
    primary_category: str = ""
    normalized_brand: str = ""
    normalized_space: str = ""
    normalized_style: str = ""
    normalized_color: str = ""
    normalized_materials_json: str = "[]"
    category_confidence: float = 0.0
    translations: dict[str, dict[str, str]] = Field(default_factory=dict)
    first_image_path: str | None = None
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
    scene_name: str | None = None
    style_hint: str | None = None
    user_request: str | None = None
    related_product_ids: list[int] = []
    conversation_id: int | None = None


class SceneGenerationRecordSchema(BaseModel):
    id: int
    conversation_id: int | None = None
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
    scene_name: str | None = None
    style_hint: str | None = None
    user_request: str | None = None


class SceneBatchActionRequest(BaseModel):
    record_ids: list[int]
    action: str


class SceneBatchActionResponse(BaseModel):
    action: str
    requested_count: int
    success_count: int
    failed_count: int
    affected_ids: list[int] = []
    failed_ids: list[int] = []


class SceneLibraryItemSchema(BaseModel):
    id: int
    conversation_id: int | None = None
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
