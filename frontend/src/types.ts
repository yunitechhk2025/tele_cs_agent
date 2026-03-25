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

export interface LLMSettings {
  provider: string;
  api_key: string;
  base_url: string;
  model: string;
  embedding_model: string;
  embedding_base_url: string;
  embedding_api_key: string;
  temperature: number;
  max_tokens: number;
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
