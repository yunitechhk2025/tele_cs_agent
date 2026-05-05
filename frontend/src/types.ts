export interface Message {
  id: number;
  conversation_id: number;
  role: 'user' | 'assistant' | 'human_agent';
  content: string;
  language: string | null;
  attachment_file_id: number | null;
  created_at: string;
}

export interface Conversation {
  id: number;
  bot_id: number | null;
  telegram_chat_id: string;
  telegram_user_id: string;
  username: string | null;
  first_name: string | null;
  last_name: string | null;
  language: string;
  status: 'active' | 'pending_human' | 'human_handling' | 'closed';
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail extends Conversation {
  messages: Message[];
  outbound_events: SimulatorOutgoingEvent[];
  processing_state?: ConversationProcessingState | null;
  latest_turn_metric?: ConversationTurnMetric | null;
  latest_turn_steps?: ConversationTurnStepMetric[];
  ai_draft?: PendingAIReply | null;
}

export interface ConversationProcessingState {
  stage_key: string;
  stage_label: string;
  stage_detail: string;
  is_processing: boolean;
  started_at: string | null;
  updated_at: string | null;
}

export interface ConversationTurnMetric {
  id: number;
  conversation_id: number;
  user_message_id: number | null;
  request_text: string;
  primary_intent: string;
  secondary_intents_json: string;
  intent_confidence: number | null;
  intent_source: string;
  intent_reason: string;
  response_kind: string;
  started_at: string;
  first_response_at: string | null;
  completed_at: string | null;
  first_response_ms: number | null;
  total_ms: number | null;
  success: boolean;
  error_message: string;
  created_at: string;
}

export interface ConversationTurnStepMetric {
  id: number;
  turn_metric_id: number;
  conversation_id: number;
  step_index: number;
  stage_key: string;
  stage_label: string;
  stage_detail: string;
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
  success: boolean;
  error_message: string;
  created_at: string;
}

export interface PendingAIReply {
  id: number;
  conversation_id: number;
  draft_text: string;
  final_text: string;
  language: string;
  content_kind: 'text' | 'product_recommendation' | 'scene_result' | string;
  payload_json: Record<string, unknown>;
  status: string;
  auto_send_at: string;
  auto_send_paused: boolean;
  sent_at: string | null;
  error_message: string;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeEntry {
  id: number;
  title: string;
  content: string;
  source: string | null;
  category: string | null;
  created_at: string;
  updated_at: string;
}

export interface Contract {
  id: number;
  conversation_id: number;
  title: string;
  content: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface ContractTemplate {
  id: number;
  name: string;
  description: string;
  original_name: string;
  file_size: number;
  created_at: string;
  updated_at: string;
}

export interface DashboardStats {
  total_conversations: number;
  active_conversations: number;
  pending_human: number;
  total_messages: number;
  total_knowledge_entries: number;
  total_contracts: number;
  total_files: number;
  total_bots: number;
  active_bots: number;
  recent_conversations: Conversation[];
}

export interface ProductImage {
  id: number;
  product_entry_id: number;
  local_path: string;
  display_order: number;
  created_at: string;
}

export interface ProductEntry {
  id: number;
  brand: string;
  product_id_ext: string;
  product_name: string;
  series_name: string;
  space: string;
  style: string;
  color: string;
  material: string;
  size: string;
  price_display: string;
  original_price: string;
  serial_number: string;
  description_text: string;
  detail_content_text: string;
  buy_url: string;
  detail_url: string;
  first_image_path: string | null;
  images: ProductImage[];
  created_at: string;
  updated_at: string;
}

export interface LLMSettings {
  provider: string;
  api_key: string;
  base_url: string;
  model: string;
  embedding_model: string;
  embedding_base_url: string;
  embedding_api_key: string;
  image_model: string;
  image_base_url: string;
  image_api_key: string;
  image_size: string;
  image_quality: string;
  image_style: string;
  temperature: number;
  max_tokens: number;
}

export interface CustomerServiceSettings {
  feature_name: string;
  mode: 'ai_auto' | 'ai_assist' | 'human_only';
  auto_send_seconds: number;
}

export interface FileEntry {
  id: number;
  filename: string;
  original_name: string;
  file_size: number;
  mime_type: string | null;
  description: string;
  tags: string;
  category: string | null;
  created_at: string;
  updated_at: string;
}

export interface TelegramBot {
  id: number;
  name: string;
  token_masked: string;
  admin_chat_id: string;
  welcome_message: string;
  is_active: boolean;
  bot_username: string | null;
  description: string;
  is_running: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProductLink {
  id: number;
  product_name: string;
  brand: string;
  buy_url: string;
  detail_url: string;
}

export interface SceneGenerationRecord {
  id: number;
  conversation_id: number | null;
  primary_product_id: number;
  primary_product_name: string;
  scene_name: string;
  style_hint: string;
  request_text: string;
  prompt_text: string;
  related_products: ProductLink[];
  image_urls: string[];
  duration_ms: number;
  status: string;
  in_library: boolean;
  error_message: string;
  created_at: string;
  updated_at: string;
}

export interface ProductImageRef {
  product_id: number;
  image_order: number;
}

export interface SceneGeneratorRequest {
  product_image_refs: ProductImageRef[];
  scene_name?: string;
  style_hint?: string;
  user_request?: string;
}

export interface SceneLibraryItem {
  id: number;
  conversation_id: number | null;
  primary_product_id: number;
  primary_product_name: string;
  primary_product_brand: string;
  primary_product_space: string;
  primary_product_style: string;
  scene_name: string;
  style_hint: string;
  request_text: string;
  related_products: ProductLink[];
  image_urls: string[];
  cover_url: string;
  duration_ms: number;
  status: string;
  in_library: boolean;
  error_message: string;
  created_at: string;
  updated_at: string;
}

export interface SceneLibraryFilters {
  brands: string[];
  spaces: string[];
  styles: string[];
  scene_names: string[];
}

export interface SceneBatchActionResponse {
  action: string;
  requested_count: number;
  success_count: number;
  failed_count: number;
  affected_ids: number[];
  failed_ids: number[];
}

export interface TelegramSimulatorSessionResponse {
  conversation_id: number;
  telegram_chat_id: string;
}

export interface SimulatorOutgoingEvent {
  id: string;
  type: 'text' | 'photo' | 'document';
  role: 'user' | 'assistant' | 'human_agent';
  text?: string;
  caption?: string;
  url?: string;
  filename?: string;
  parse_mode?: string | null;
  created_at: string;
}
