import axios from 'axios';
import type {
  Conversation, ConversationDetail, KnowledgeEntry, Message,
  Contract, ContractTemplate, DashboardStats, LLMSettings, CustomerServiceSettings, FileEntry, TelegramBot,
  ProductEntry, SceneGenerationRecord, SceneLibraryItem, SceneLibraryFilters,
  SceneGeneratorRequest, SceneBatchActionResponse, TelegramSimulatorSessionResponse, SimulatorOutgoingEvent,
} from './types';

const api = axios.create({ baseURL: '/api' });

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/login';
    }
    return Promise.reject(err);
  },
);

export const authApi = {
  login: (username: string, password: string) =>
    api.post<{ access_token: string }>('/auth/login', { username, password }),
};

export const dashboardApi = {
  getStats: () => api.get<DashboardStats>('/dashboard/stats'),
};

export const conversationApi = {
  list: (params?: { status?: string; search?: string }) =>
    api.get<Conversation[]>('/conversations', { params }),
  get: (id: number) =>
    api.get<ConversationDetail>(`/conversations/${id}`),
  reply: (id: number, content: string) =>
    api.post(`/conversations/${id}/reply`, { content }),
  sendAiDraft: (id: number, content?: string, sendAsHumanAgent?: boolean) =>
    api.post(`/conversations/${id}/ai-draft/send`, {
      content,
      send_as_human_agent: Boolean(sendAsHumanAgent),
    }),
  pauseAiDraft: (id: number) =>
    api.post(`/conversations/${id}/ai-draft/pause`),
  cancelAiDraft: (id: number) =>
    api.post(`/conversations/${id}/ai-draft/cancel`),
  close: (id: number) =>
    api.post(`/conversations/${id}/close`),
  delete: (id: number) =>
    api.delete(`/conversations/${id}`),
  sendContract: (conversationId: number, contractId: number) =>
    api.post(`/conversations/${conversationId}/send-contract`, { contract_id: contractId }),
};

export const knowledgeApi = {
  list: (params?: { category?: string; search?: string }) =>
    api.get<KnowledgeEntry[]>('/knowledge', { params }),
  create: (data: { title: string; content: string; source?: string; category?: string }) =>
    api.post<KnowledgeEntry>('/knowledge', data),
  delete: (id: number) =>
    api.delete(`/knowledge/${id}`),
  upload: (file: File, category?: string) => {
    const form = new FormData();
    form.append('file', file);
    return api.post('/knowledge/upload', form, {
      params: { category },
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
};

export const contractApi = {
  list: (params?: { status?: string; conversation_id?: number }) =>
    api.get<Contract[]>('/contracts', { params }),
  get: (id: number) =>
    api.get<Contract>(`/contracts/${id}`),
  generate: (conversationId: number, templateId?: number | null, language?: string) =>
    api.post<Contract>('/contracts/generate', {
      conversation_id: conversationId,
      template_id: templateId ?? undefined,
      language: language || undefined,
    }),
  update: (id: number, data: { title?: string; content?: string; status?: string }) =>
    api.put<Contract>(`/contracts/${id}`, data),
  delete: (id: number) =>
    api.delete(`/contracts/${id}`),
};

export const contractTemplateApi = {
  list: () => api.get<ContractTemplate[]>('/contract-templates'),
  upload: (file: File, name: string, description: string) => {
    const form = new FormData();
    form.append('file', file);
    return api.post<ContractTemplate>('/contract-templates/upload', form, {
      params: { name, description },
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  delete: (id: number) => api.delete(`/contract-templates/${id}`),
  downloadBlob: (id: number) =>
    api.get<Blob>(`/contract-templates/${id}/download`, { responseType: 'blob' }),
};

export const settingsApi = {
  getLLM: () => api.get<LLMSettings>('/settings/llm'),
  updateLLM: (data: Partial<LLMSettings>) => api.put<LLMSettings>('/settings/llm', data),
  getCustomerService: () => api.get<CustomerServiceSettings>('/settings/customer-service'),
  updateCustomerService: (data: Partial<CustomerServiceSettings>) =>
    api.put<CustomerServiceSettings>('/settings/customer-service', data),
  testLLM: (data: Partial<LLMSettings>) =>
    api.post<{ ok: boolean; message: string }>('/settings/llm/test', data),
  testEmbedding: (data: Partial<LLMSettings>) =>
    api.post<{ ok: boolean; message: string }>('/settings/llm/test-embedding', data),
  testImage: (data: Partial<LLMSettings>) =>
    api.post<{ ok: boolean; message: string }>('/settings/llm/test-image', data),
};

export const fileApi = {
  list: (params?: { category?: string; search?: string }) =>
    api.get<FileEntry[]>('/files', { params }),
  upload: (file: File, description: string, tags: string, category?: string) => {
    const form = new FormData();
    form.append('file', file);
    return api.post<FileEntry>('/files/upload', form, {
      params: { description, tags, category },
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  update: (id: number, data: { description?: string; tags?: string; category?: string }) =>
    api.put<FileEntry>(`/files/${id}`, data),
  delete: (id: number) =>
    api.delete(`/files/${id}`),
  downloadUrl: (id: number) => `/api/files/${id}/download`,
};

export const botApi = {
  list: () => api.get<TelegramBot[]>('/bots'),
  get: (id: number) => api.get<TelegramBot>(`/bots/${id}`),
  create: (data: {
    name: string;
    token: string;
    admin_chat_id?: string;
    welcome_message?: string;
    is_active?: boolean;
    description?: string;
  }) => api.post<TelegramBot>('/bots', data),
  update: (id: number, data: {
    name?: string;
    token?: string;
    admin_chat_id?: string;
    welcome_message?: string;
    is_active?: boolean;
    description?: string;
  }) => api.put<TelegramBot>(`/bots/${id}`, data),
  delete: (id: number) => api.delete(`/bots/${id}`),
  start: (id: number) => api.post<{ status: string; is_running: boolean }>(`/bots/${id}/start`),
  stop: (id: number) => api.post<{ status: string; is_running: boolean }>(`/bots/${id}/stop`),
};

export const productApi = {
  list: (params?: { keyword?: string; brand?: string; space?: string; style?: string; series?: string; color?: string; skip?: number; limit?: number }) =>
    api.get<ProductEntry[]>('/products', { params }),
  get: (id: number) => api.get<ProductEntry>(`/products/${id}`),
  meta: () => api.get<{ spaces: string[]; styles: string[]; series: string[]; brands: string[] }>('/products/meta'),
  imageUrl: (productId: number, order: number) => `/api/products/${productId}/images/${order}`,
  triggerImport: () => api.post<{ status: string; output: string }>('/products/import'),
  listSceneImages: (productId: number) => api.get<SceneGenerationRecord[]>(`/products/${productId}/scene-images`),
  generateSceneImages: (productId: number, data: {
    scene_name?: string;
    style_hint?: string;
    user_request?: string;
    related_product_ids?: number[];
    conversation_id?: number;
  }) => api.post<SceneGenerationRecord>(`/products/${productId}/scene-images`, data),
};

export const sceneGeneratorApi = {
  generate: (data: SceneGeneratorRequest) =>
    api.post<SceneGenerationRecord>('/scene-generator/generate', data),
  get: (recordId: number) =>
    api.get<SceneGenerationRecord>(`/scene-generations/${recordId}`),
  retry: (recordId: number) =>
    api.post<SceneGenerationRecord>(`/scene-generations/${recordId}/retry`),
  delete: (recordId: number) =>
    api.delete<{ status: string; id: number }>(`/scene-generations/${recordId}`),
  toggleLibrary: (recordId: number) =>
    api.post<{ id: number; in_library: boolean }>(`/scene-generations/${recordId}/toggle-library`),
  batchAction: (data: { record_ids: number[]; action: 'delete' | 'add_to_library' | 'remove_from_library' | 'retry' }) =>
    api.post<SceneBatchActionResponse>('/scene-generations/batch', data),
};

export const sceneLibraryApi = {
  filters: (params?: { view?: 'library' | 'review' | 'generating' | 'failed' }) =>
    api.get<SceneLibraryFilters>('/scene-library/filters', { params }),
  list: (params?: { view?: 'library' | 'review' | 'generating' | 'failed'; brand?: string; space?: string; style?: string; scene_name?: string; skip?: number; limit?: number }) =>
    api.get<SceneLibraryItem[]>('/scene-library', { params }),
};

export const simulatorApi = {
  createSession: (botId: number, language?: string) =>
    api.post<TelegramSimulatorSessionResponse>('/simulator/sessions', {
      bot_id: botId,
      language: language || 'zh-Hans',
    }),
  sendMessage: (conversationId: number, text: string) =>
    api.post<{ conversation_id: number; outgoing: SimulatorOutgoingEvent[] }>(
      `/simulator/sessions/${conversationId}/send`,
      { text },
    ),
  getMessages: (conversationId: number) =>
    api.get<Message[]>(`/simulator/sessions/${conversationId}/messages`),
  getEvents: (conversationId: number) =>
    api.get<SimulatorOutgoingEvent[]>(`/simulator/sessions/${conversationId}/events`),
};

export default api;
