import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import utc from 'dayjs/plugin/utc';
import 'dayjs/locale/zh-cn';
import {
  Badge,
  Button,
  Card,
  Divider,
  Dropdown,
  Empty,
  Input,
  List,
  Modal,
  Radio,
  Segmented,
  Select,
  Space,
  Spin,
  Switch,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import {
  CloseCircleOutlined,
  CustomerServiceOutlined,
  DeleteOutlined,
  EditOutlined,
  ExportOutlined,
  FileTextOutlined,
  LoadingOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  RobotOutlined,
  SearchOutlined,
  SendOutlined,
  SwapOutlined,
  TranslationOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { conversationApi, contractApi, contractTemplateApi, dashboardApi, settingsApi, translateApi } from '../api';
import { TypewriterText } from '../components/TypewriterText';
import type {
  Contract,
  ContractTemplate,
  Conversation,
  ConversationDetail,
  CustomerServiceSettings,
  DashboardStats,
  Message,
  SimulatorOutgoingEvent,
} from '../types';

dayjs.extend(relativeTime);
dayjs.extend(utc);
dayjs.locale('zh-cn');

const { Text, Title } = Typography;

const PANEL_HEIGHT = 'calc(100vh - 188px)';

type FilterKey = 'all' | 'active' | 'pending_human' | 'human_handling';

const FILTER_TABS: { key: FilterKey; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'active', label: '进行中' },
  { key: 'pending_human', label: '待处理' },
  { key: 'human_handling', label: '处理中' },
];

const CONTRACT_OUTPUT_LANG_OPTIONS = [
  { value: 'zh', label: '中文' },
  { value: 'en', label: 'English' },
  { value: 'ja', label: '日本語' },
  { value: 'ko', label: '한국어' },
  { value: 'es', label: 'Español' },
  { value: 'fr', label: 'Français' },
  { value: 'de', label: 'Deutsch' },
  { value: 'ar', label: 'العربية' },
  { value: 'ru', label: 'Русский' },
  { value: 'pt', label: 'Português' },
];

function customerDisplayName(c: Pick<Conversation, 'first_name' | 'last_name' | 'username'>) {
  const parts = [c.first_name, c.last_name].filter(Boolean);
  if (parts.length) return parts.join(' ');
  if (c.username) return `@${c.username}`;
  return 'Telegram 用户';
}

function statusConfig(status: Conversation['status']) {
  switch (status) {
    case 'active':
      return { color: 'processing' as const, label: '进行中' };
    case 'pending_human':
      return { color: 'warning' as const, label: '待处理' };
    case 'human_handling':
      return { color: 'cyan' as const, label: '处理中' };
    case 'closed':
      return { color: 'default' as const, label: '已关闭' };
    default:
      return { color: 'default' as const, label: status };
  }
}

function languageLabel(code: string) {
  const upper = code?.toUpperCase() || '—';
  try {
    const dn = new Intl.DisplayNames(['zh'], { type: 'language' });
    const name = dn.of(code.split('-')[0]);
    return name ? `${upper} · ${name}` : upper;
  } catch {
    return upper;
  }
}

function isSimulatorConversation(c: Pick<Conversation, 'telegram_chat_id'>) {
  return (c.telegram_chat_id || '').startsWith('sim-');
}

function parseServerUtc(value?: string | null) {
  if (!value) return null;
  const parsed = dayjs.utc(value);
  return parsed.isValid() ? parsed : null;
}


function draftAutoSendLabel(detail: ConversationDetail | null, draftCountdownSeconds: number | null) {
  if (!detail?.ai_draft) return '—';
  if (detail.ai_draft.auto_send_paused) return '已暂停自动发送';
  return `${draftCountdownSeconds ?? '—'} 秒后自动发送`;
}

function draftTitle(detail: ConversationDetail | null) {
  const kind = detail?.ai_draft?.content_kind || 'text';
  if (kind === 'product_recommendation') return '商品推荐待确认';
  if (kind === 'scene_result') return '场景图待确认';
  return 'AI 待确认回复';
}

function canEditDraft(detail: ConversationDetail | null) {
  return detail?.ai_draft?.content_kind === 'text';
}

type ProductDraftCard = {
  product_id?: number;
  caption?: string;
  image_url?: string;
};

type ProductRecommendationDraftPayload = {
  intro_text?: string;
  followup_text?: string;
  cards?: ProductDraftCard[];
};

type SceneResultDraftPayload = {
  intro_text?: string;
  links_text?: string;
  image_urls?: string[];
};

function parseMarkdownLink(value: string) {
  const match = value.match(/\[([^\]]+)\]\(([^)]+)\)/);
  if (!match) return null;
  return { label: match[1], url: match[2] };
}

function ProductRecommendationDraftPreview({ payload }: { payload: Record<string, unknown> }) {
  const data = payload as ProductRecommendationDraftPayload;
  const cards = Array.isArray(data.cards) ? data.cards : [];

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      {data.intro_text ? (
        <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.6 }}>
          {data.intro_text}
        </div>
      ) : null}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
          gap: 12,
        }}
      >
        {cards.map((card, index) => {
          const lines = String(card.caption || '')
            .split('\n')
            .map((line) => line.trim())
            .filter(Boolean);
          const heading = lines[0]?.replace(/^\[(#[^\]]+)\]\s*\*/, '$1 ').replace(/\*$/g, '') || `#${index + 1}`;
          const detailLines = lines.slice(1).filter((line) => !line.startsWith('[查看详情]') && !line.startsWith('[View details]'));
          const linkLine = lines.find((line) => line.includes(']('));
          const link = linkLine ? parseMarkdownLink(linkLine) : null;
          return (
            <Card
              key={`${card.product_id || 'card'}-${index}`}
              size="small"
              style={{ borderRadius: 12, overflow: 'hidden' }}
              styles={{ body: { padding: 12 } }}
            >
              {card.image_url ? (
                <img
                  alt={heading}
                  src={card.image_url}
                  loading="lazy"
                  style={{
                    width: '100%',
                    maxWidth: 280,
                    maxHeight: 180,
                    aspectRatio: '4 / 3',
                    objectFit: 'cover',
                    borderRadius: 10,
                    display: 'block',
                    marginBottom: 10,
                    background: '#fafafa',
                  }}
                />
              ) : null}
              <Space direction="vertical" size={6} style={{ width: '100%' }}>
                <Text strong style={{ fontSize: 14, lineHeight: 1.5 }}>
                  {heading}
                </Text>
                {detailLines.map((line, lineIndex) => (
                  <Text key={lineIndex} type="secondary" style={{ fontSize: 13, lineHeight: 1.5 }}>
                    {line}
                  </Text>
                ))}
                {link ? (
                  <a href={link.url} target="_blank" rel="noreferrer" style={{ fontSize: 13 }}>
                    {link.label}
                  </a>
                ) : null}
              </Space>
            </Card>
          );
        })}
      </div>
      {data.followup_text ? (
        <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.6 }}>
          {data.followup_text}
        </div>
      ) : null}
    </Space>
  );
}

function SceneResultDraftPreview({ payload }: { payload: Record<string, unknown> }) {
  const data = payload as SceneResultDraftPayload;
  const imageUrls = Array.isArray(data.image_urls) ? data.image_urls : [];
  const linkLines = String(data.links_text || '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const prefixMatch = line.match(/^([^:]+):\s*(.+)$/);
      const prefix = prefixMatch?.[1] || '';
      const raw = prefixMatch?.[2] || line;
      const link = parseMarkdownLink(raw);
      return {
        prefix,
        label: link?.label || raw,
        url: link?.url || '',
      };
    });

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      {data.intro_text ? (
        <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.6 }}>
          {data.intro_text}
        </div>
      ) : null}
      {imageUrls.length ? (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
            gap: 12,
          }}
        >
          {imageUrls.map((url, index) => (
            <Card
              key={`${url}-${index}`}
              size="small"
              style={{ borderRadius: 12, overflow: 'hidden' }}
              styles={{ body: { padding: 12 } }}
            >
              <img
                alt={`scene-${index + 1}`}
                src={url}
                loading="lazy"
                style={{
                  width: '100%',
                  maxWidth: 360,
                  maxHeight: 260,
                  objectFit: 'contain',
                  borderRadius: 10,
                  display: 'block',
                  background: '#fafafa',
                  margin: '0 auto',
                }}
              />
            </Card>
          ))}
        </div>
      ) : null}
      {linkLines.length ? (
        <Card size="small" style={{ borderRadius: 12 }} styles={{ body: { padding: 12 } }}>
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            {linkLines.map((item, index) => (
              <div key={`${item.label}-${index}`} style={{ lineHeight: 1.6, wordBreak: 'break-word' }}>
                {item.prefix ? (
                  <Text strong style={{ marginRight: 6 }}>
                    {item.prefix}:
                  </Text>
                ) : null}
                {item.url ? (
                  <a href={item.url} target="_blank" rel="noreferrer">
                    {item.label}
                  </a>
                ) : (
                  <Text>{item.label}</Text>
                )}
              </div>
            ))}
          </Space>
        </Card>
      ) : null}
    </Space>
  );
}

function DraftPreview({ detail }: { detail: ConversationDetail }) {
  const kind = detail.ai_draft?.content_kind || 'text';
  const payload = detail.ai_draft?.payload_json || {};

  if (kind === 'product_recommendation') {
    return <ProductRecommendationDraftPreview payload={payload} />;
  }
  if (kind === 'scene_result') {
    return <SceneResultDraftPreview payload={payload} />;
  }
  return (
    <div
      style={{
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
        lineHeight: 1.6,
        fontSize: 14,
      }}
    >
      {detail.ai_draft?.draft_text}
    </div>
  );
}

type ConversationTimelineItem =
  | {
      id: string;
      created_at: string;
      kind: 'message';
      message: Message;
    }
  | {
      id: string;
      created_at: string;
      kind: 'event';
      event: SimulatorOutgoingEvent;
    };

function OutboundEventBubble({
  event,
  textOverride,
  captionOverride,
  animateKey,
}: {
  event: SimulatorOutgoingEvent;
  textOverride?: string;
  captionOverride?: string;
  /** 提供时使用打字机效果输出文本/图片说明。 */
  animateKey?: string;
}) {
  const isHuman = event.role === 'human_agent';
  const bg = isHuman ? '#f6ffed' : '#fff';
  const name = isHuman ? '人工客服' : 'AI 助手';
  const icon = isHuman ? <CustomerServiceOutlined /> : <RobotOutlined />;

  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'flex-end',
        marginBottom: 12,
      }}
    >
      <div
        style={{
          maxWidth: '78%',
          padding: '10px 14px',
          borderRadius: 12,
          background: bg,
          border: '1px solid #d9d9d9',
          boxShadow: '0 1px 4px rgba(0,0,0,0.06)',
        }}
      >
        <Space size={6} align="center" style={{ marginBottom: 6 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {icon} {name}
          </Text>
          <Text type="secondary" style={{ fontSize: 11 }}>
            {dayjs(event.created_at).format('YYYY-MM-DD · HH:mm')}
          </Text>
        </Space>
        {event.type === 'photo' && event.url ? (
          <div>
            <img
              alt={event.caption || 'outbound-photo'}
              src={event.url}
              style={{ maxWidth: '100%', maxHeight: 320, borderRadius: 10, display: 'block', background: '#fafafa' }}
            />
            {(captionOverride ?? event.caption) ? (
              <div style={{ marginTop: 10, whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.55, fontSize: 14 }}>
                {animateKey ? (
                  <TypewriterText id={animateKey} text={(captionOverride ?? event.caption) || ''} />
                ) : (
                  captionOverride ?? event.caption
                )}
              </div>
            ) : null}
          </div>
        ) : null}
        {event.type === 'document' && event.url ? (
          <a href={event.url} target="_blank" rel="noreferrer">
            {event.filename || 'Document'}
          </a>
        ) : null}
        {event.type === 'text' && (textOverride ?? event.text) ? (
          <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.55, fontSize: 14 }}>
            {animateKey ? (
              <TypewriterText id={animateKey} text={(textOverride ?? event.text) || ''} />
            ) : (
              textOverride ?? event.text
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function MessageBubble({
  msg,
  contentOverride,
  animateKey,
}: {
  msg: Message;
  contentOverride?: string;
  animateKey?: string;
}) {
  const isUser = msg.role === 'user';
  const isAssistant = msg.role === 'assistant';

  const roleLabel =
    msg.role === 'user'
      ? '客户'
      : msg.role === 'assistant'
        ? 'AI 助手'
        : '人工客服';

  const icon =
    msg.role === 'user' ? (
      <UserOutlined />
    ) : msg.role === 'assistant' ? (
      <RobotOutlined />
    ) : (
      <CustomerServiceOutlined />
    );

  const align: 'flex-start' | 'flex-end' = isUser ? 'flex-start' : 'flex-end';
  const bg = isUser
    ? '#e6f7ff'
    : isAssistant
      ? '#fff'
      : '#f6ffed';
  const border = isAssistant ? '1px solid #d9d9d9' : 'none';

  return (
    <div
      style={{
        display: 'flex',
        justifyContent: align,
        marginBottom: 12,
      }}
    >
      <div
        style={{
          maxWidth: '78%',
          padding: '10px 14px',
          borderRadius: 12,
          background: bg,
          border,
          boxShadow: isUser ? '0 1px 2px rgba(0,0,0,0.06)' : '0 1px 4px rgba(0,0,0,0.06)',
        }}
      >
        <Space size={6} align="center" style={{ marginBottom: 6 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {icon} {roleLabel}
          </Text>
          <Text type="secondary" style={{ fontSize: 11 }}>
            {dayjs(msg.created_at).format('YYYY-MM-DD · HH:mm')}
          </Text>
        </Space>
        <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: 14, lineHeight: 1.55 }}>
          {animateKey ? (
            <TypewriterText id={animateKey} text={(contentOverride ?? msg.content) || ''} />
          ) : (
            contentOverride ?? msg.content
          )}
        </div>
        {msg.attachment_file_id != null && msg.attachment_file_id !== undefined && (
          <div style={{ marginTop: 10 }}>
            <img
              alt=""
              src={`/api/files/${msg.attachment_file_id}/download`}
              style={{ maxWidth: '100%', maxHeight: 280, borderRadius: 8, display: 'block' }}
            />
          </div>
        )}
      </div>
    </div>
  );
}

export default function Conversations() {
  const navigate = useNavigate();
  const { id: idParam } = useParams();

  const selectedId = useMemo(() => {
    if (!idParam) return null;
    const n = parseInt(idParam, 10);
    return Number.isFinite(n) ? n : null;
  }, [idParam]);

  const [listLoading, setListLoading] = useState(true);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [stats, setStats] = useState<DashboardStats | null>(null);

  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [filter, setFilter] = useState<FilterKey>('all');

  const [detailLoading, setDetailLoading] = useState(false);
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [customerServiceSettings, setCustomerServiceSettings] = useState<CustomerServiceSettings | null>(null);
  const [draftCountdownSeconds, setDraftCountdownSeconds] = useState<number | null>(null);

  const [replyText, setReplyText] = useState('');
  const [replySending, setReplySending] = useState(false);
  const [aiDraftSending, setAiDraftSending] = useState(false);
  const [aiDraftCancelling, setAiDraftCancelling] = useState(false);
  const [editingAiDraft, setEditingAiDraft] = useState(false);
  const [aiDraftText, setAiDraftText] = useState('');
  const [contractLoading, setContractLoading] = useState(false);
  const [closeLoading, setCloseLoading] = useState(false);

  const [generateModalOpen, setGenerateModalOpen] = useState(false);
  const [templates, setTemplates] = useState<ContractTemplate[]>([]);
  const [genTemplateId, setGenTemplateId] = useState<number | null>(null);
  const [genOutputLang, setGenOutputLang] = useState<string>('en');
  const [templatesLoading, setTemplatesLoading] = useState(false);

  const [translationEnabled, setTranslationEnabled] = useState<boolean>(() => {
    try {
      return localStorage.getItem('conv:translation') === '1';
    } catch {
      return false;
    }
  });
  const [translations, setTranslations] = useState<Record<string, string>>({});
  const [translating, setTranslating] = useState(false);
  const translateInflight = useRef<Set<string>>(new Set());

  useEffect(() => {
    try {
      localStorage.setItem('conv:translation', translationEnabled ? '1' : '0');
    } catch {
      /* ignore */
    }
  }, [translationEnabled]);

  const [listWidth, setListWidth] = useState<number>(() => {
    try {
      const v = parseInt(localStorage.getItem('conv:listWidth') || '', 10);
      if (Number.isFinite(v) && v >= 220 && v <= 720) return v;
    } catch {
      /* ignore */
    }
    return 350;
  });
  const [listCollapsed, setListCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem('conv:listCollapsed') === '1';
    } catch {
      return false;
    }
  });
  const resizingRef = useRef(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    try {
      localStorage.setItem('conv:listWidth', String(listWidth));
    } catch {
      /* ignore */
    }
  }, [listWidth]);

  useEffect(() => {
    try {
      localStorage.setItem('conv:listCollapsed', listCollapsed ? '1' : '0');
    } catch {
      /* ignore */
    }
  }, [listCollapsed]);

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!resizingRef.current) return;
      const box = containerRef.current?.getBoundingClientRect();
      if (!box) return;
      const next = Math.min(720, Math.max(220, e.clientX - box.left));
      setListWidth(next);
    };
    const onUp = () => {
      if (!resizingRef.current) return;
      resizingRef.current = false;
      document.body.style.userSelect = '';
      document.body.style.cursor = '';
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, []);

  const startResizing = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    resizingRef.current = true;
    document.body.style.userSelect = 'none';
    document.body.style.cursor = 'col-resize';
  }, []);

  const [sendModalOpen, setSendModalOpen] = useState(false);
  const [convContracts, setConvContracts] = useState<Contract[]>([]);
  const [sendContractId, setSendContractId] = useState<number | null>(null);
  const [sendLoading, setSendLoading] = useState(false);
  const [contractsLoading, setContractsLoading] = useState(false);

  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedSearch(search.trim()), 320);
    return () => window.clearTimeout(t);
  }, [search]);

  const loadList = useCallback(async () => {
    setListLoading(true);
    try {
      const params: { status?: string; search?: string } = {};
      if (debouncedSearch) params.search = debouncedSearch;
      if (filter !== 'all') params.status = filter;
      const { data } = await conversationApi.list(params);
      setConversations(Array.isArray(data) ? data : []);
    } catch {
      message.error('加载对话列表失败');
      setConversations([]);
    } finally {
      setListLoading(false);
    }
  }, [debouncedSearch, filter]);

  const loadCustomerServiceSettings = useCallback(async () => {
    try {
      const { data } = await settingsApi.getCustomerService();
      setCustomerServiceSettings(data);
    } catch {
      setCustomerServiceSettings(null);
    }
  }, []);

  const [modeUpdating, setModeUpdating] = useState(false);
  const handleChangeMode = useCallback(
    async (mode: CustomerServiceSettings['mode']) => {
      if (!customerServiceSettings || customerServiceSettings.mode === mode) return;
      setModeUpdating(true);
      const previous = customerServiceSettings;
      // 乐观更新，让 Segmented 切换感官即时
      setCustomerServiceSettings({ ...customerServiceSettings, mode });
      try {
        const { data } = await settingsApi.updateCustomerService({ mode });
        setCustomerServiceSettings(data);
        const labelMap: Record<CustomerServiceSettings['mode'], string> = {
          ai_auto: '已切换到「全 AI 自动应答」',
          ai_assist: '已切换到「人机协同（人工确认 AI 草稿）」',
          human_only: '已切换到「纯人工应答」',
        };
        message.success(labelMap[mode]);
      } catch {
        setCustomerServiceSettings(previous);
        message.error('切换应答模式失败，请稍后重试');
      } finally {
        setModeUpdating(false);
      }
    },
    [customerServiceSettings],
  );

  const loadStats = useCallback(async () => {
    try {
      const { data } = await dashboardApi.getStats();
      setStats(data);
    } catch {
      setStats(null);
    }
  }, []);

  useEffect(() => {
    loadList();
  }, [loadList]);

  useEffect(() => {
    void loadCustomerServiceSettings();
  }, [loadCustomerServiceSettings]);

  useEffect(() => {
    void loadStats();
    const timer = window.setInterval(() => void loadStats(), 30000);
    return () => window.clearInterval(timer);
  }, [loadStats]);

  const loadDetail = useCallback(async (conversationId: number) => {
    setDetailLoading(true);
    try {
      const { data } = await conversationApi.get(conversationId);
      setDetail(data);
    } catch {
      message.error('加载对话详情失败');
      setDetail(null);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selectedId == null) {
      setDetail(null);
      return;
    }
    loadDetail(selectedId);
  }, [selectedId, loadDetail]);

  useEffect(() => {
    if (!detail?.ai_draft) {
      setEditingAiDraft(false);
      setAiDraftText('');
      return;
    }
    if (!editingAiDraft) {
      setAiDraftText(detail.ai_draft.draft_text || '');
    }
  }, [detail?.ai_draft?.id, detail?.ai_draft?.draft_text, editingAiDraft]);

  useEffect(() => {
    if (!detail?.ai_draft?.auto_send_at) {
      setDraftCountdownSeconds(null);
      return undefined;
    }

    const updateCountdown = () => {
      const target = parseServerUtc(detail.ai_draft?.auto_send_at);
      if (!target) {
        setDraftCountdownSeconds(null);
        return;
      }
      setDraftCountdownSeconds(Math.max(0, target.diff(dayjs.utc(), 'second')));
    };

    updateCountdown();
    const timer = window.setInterval(updateCountdown, 1000);
    return () => window.clearInterval(timer);
  }, [detail?.ai_draft?.id, detail?.ai_draft?.auto_send_at]);

  useEffect(() => {
    if (selectedId == null) return undefined;
    const timer = window.setInterval(() => {
      void loadDetail(selectedId);
      void loadList();
      void loadCustomerServiceSettings();
    }, 3000);
    return () => window.clearInterval(timer);
  }, [selectedId, loadCustomerServiceSettings, loadDetail, loadList]);

  const handleSelectConversation = (conversationId: number) => {
    navigate(`/conversations/${conversationId}`);
  };

  const handleOpenSimulator = (conversationId: number) => {
    navigate(`/simulator?conversationId=${conversationId}`);
  };

  const handleDeleteSimulatorConversation = (conversation: Conversation) => {
    Modal.confirm({
      title: '确认删除这个模拟对话？',
      content: '删除后将移除该模拟会话的消息、场景状态和关联场景记录，且不可恢复。',
      okText: '删除',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await conversationApi.delete(conversation.id);
          message.success('模拟对话已删除');
          if (selectedId === conversation.id) {
            setDetail(null);
            setReplyText('');
            navigate('/conversations');
          }
          await loadList();
        } catch {
          message.error('删除模拟对话失败');
        }
      },
    });
  };

  const handleSendReply = async () => {
    if (selectedId == null || !detail) return;
    const text = replyText.trim();
    if (!text) {
      message.warning('请输入回复内容');
      return;
    }
    setReplySending(true);
    try {
      await conversationApi.reply(selectedId, text);
      setReplyText('');
      message.success('消息已发送');
      await loadDetail(selectedId);
      await loadList();
    } catch {
      message.error('发送回复失败');
    } finally {
      setReplySending(false);
    }
  };

  const handleSendAiDraft = async () => {
    if (selectedId == null || !detail?.ai_draft) return;
    setAiDraftSending(true);
    try {
      await conversationApi.sendAiDraft(
        selectedId,
        editingAiDraft ? aiDraftText.trim() : undefined,
        editingAiDraft,
      );
      message.success(editingAiDraft ? '编辑后的 AI 回复已发送' : 'AI 回复已发送');
      setEditingAiDraft(false);
      await loadDetail(selectedId);
      await loadList();
    } catch {
      message.error('发送 AI 草稿失败');
    } finally {
      setAiDraftSending(false);
    }
  };

  const handleCancelAiDraft = async () => {
    if (selectedId == null || !detail?.ai_draft) return;
    setAiDraftCancelling(true);
    try {
      await conversationApi.cancelAiDraft(selectedId);
      message.success('AI 草稿已取消');
      setEditingAiDraft(false);
      setAiDraftText('');
      await loadDetail(selectedId);
      await loadList();
    } catch {
      message.error('取消 AI 草稿失败');
    } finally {
      setAiDraftCancelling(false);
    }
  };

  const handleToggleEditAiDraft = async () => {
    if (!detail?.ai_draft) return;
    if (!canEditDraft(detail)) return;
    if (editingAiDraft) {
      setEditingAiDraft(false);
      setAiDraftText(detail.ai_draft.draft_text || '');
      return;
    }

    if (!detail.ai_draft.auto_send_paused) {
      try {
        await conversationApi.pauseAiDraft(detail.id);
        await loadDetail(detail.id);
        await loadList();
      } catch {
        message.error('暂停 AI 草稿自动发送失败');
        return;
      }
    }

    setEditingAiDraft(true);
  };

  const openGenerateModal = async () => {
    if (selectedId == null) return;
    setGenerateModalOpen(true);
    setGenTemplateId(null);
    const base = detail?.language?.split('-')[0]?.toLowerCase() || 'en';
    const match = CONTRACT_OUTPUT_LANG_OPTIONS.some((o) => o.value === base);
    setGenOutputLang(match ? base : 'en');
    setTemplatesLoading(true);
    try {
      const { data } = await contractTemplateApi.list();
      setTemplates(Array.isArray(data) ? data : []);
    } catch {
      message.error('加载合同模板失败');
      setTemplates([]);
    } finally {
      setTemplatesLoading(false);
    }
  };

  const confirmGenerateContract = async () => {
    if (selectedId == null) return;
    setContractLoading(true);
    try {
      const { data } = await contractApi.generate(
        selectedId,
        genTemplateId === null ? undefined : genTemplateId,
        genOutputLang,
      );
      message.success(`合同已生成：${data.title || `ID ${data.id}`}`);
      setGenerateModalOpen(false);
      await loadDetail(selectedId);
    } catch {
      message.error('生成合同失败');
    } finally {
      setContractLoading(false);
    }
  };

  const openSendContractModal = async () => {
    if (selectedId == null) return;
    setSendModalOpen(true);
    setSendContractId(null);
    setContractsLoading(true);
    try {
      const { data } = await contractApi.list({ conversation_id: selectedId });
      const list = Array.isArray(data) ? data : [];
      setConvContracts(list);
      if (list.length === 1) setSendContractId(list[0].id);
    } catch {
      message.error('加载合同列表失败');
      setConvContracts([]);
    } finally {
      setContractsLoading(false);
    }
  };

  const confirmSendContract = async () => {
    if (selectedId == null || sendContractId == null) {
      message.warning('请选择要发送的合同');
      return;
    }
    setSendLoading(true);
    try {
      await conversationApi.sendContract(selectedId, sendContractId);
      message.success('合同已发送给客户');
      setSendModalOpen(false);
      await loadDetail(selectedId);
    } catch {
      message.error('发送合同失败');
    } finally {
      setSendLoading(false);
    }
  };

  const handleCloseConversation = () => {
    if (selectedId == null || !detail) return;
    Modal.confirm({
      title: '确认关闭此对话？',
      content: '关闭后客户需要重新发起对话。',
      okText: '关闭',
      cancelText: '取消',
      okButtonProps: { danger: true, loading: closeLoading },
      onOk: async () => {
        setCloseLoading(true);
        try {
          await conversationApi.close(selectedId);
          message.success('对话已关闭');
          setReplyText('');
          await loadList();
          await loadDetail(selectedId);
          navigate('/conversations');
        } catch {
          message.error('关闭对话失败');
        } finally {
          setCloseLoading(false);
        }
      },
    });
  };

  const activeTabKey = filter;
  const timeline = useMemo<ConversationTimelineItem[]>(() => {
    if (!detail) return [];
    const messageItems = (detail.messages || []).map((msg) => ({
      id: `msg-${msg.id}`,
      created_at: msg.created_at,
      kind: 'message' as const,
      message: msg,
    }));
    const eventItems = (detail.outbound_events || [])
      .filter((event) => event.type === 'photo' || event.type === 'document')
      .map((event) => ({
        id: event.id,
        created_at: event.created_at,
        kind: 'event' as const,
        event,
      }));
    return [...messageItems, ...eventItems].sort((a, b) => {
      const diff = dayjs(a.created_at).valueOf() - dayjs(b.created_at).valueOf();
      if (diff !== 0) return diff;
      if (a.kind === b.kind) return 0;
      return a.kind === 'message' ? -1 : 1;
    });
  }, [detail]);

  const timelineKeyAndText = useCallback((item: ConversationTimelineItem): { key: string; text: string } | null => {
    if (item.kind === 'message') {
      const text = item.message.content;
      if (!text || !text.trim()) return null;
      return { key: `msg-${item.message.id}`, text };
    }
    const ev = item.event;
    const text = ev.type === 'text' ? ev.text || '' : ev.type === 'photo' ? ev.caption || '' : '';
    if (!text.trim()) return null;
    return { key: `evt-${ev.id}`, text };
  }, []);

  const isLikelyChinese = useCallback((text: string) => {
    if (!text) return true;
    const matches = text.match(/[\u4e00-\u9fff]/g);
    return !!matches && matches.length / text.length > 0.5;
  }, []);

  // 切换翻译开关 / 切换对话时，清空 inflight 集合，避免上一次失败/挂死的请求
  // 在 ref 里残留导致后续请求被误判为"已在请求中"。
  useEffect(() => {
    translateInflight.current.clear();
    setTranslating(false);
  }, [translationEnabled, selectedId]);

  useEffect(() => {
    if (!translationEnabled) return undefined;
    const missing: { key: string; text: string }[] = [];
    for (const item of timeline) {
      const src = timelineKeyAndText(item);
      if (!src) continue;
      if (translations[src.key] != null) continue;
      if (translateInflight.current.has(src.key)) continue;
      if (isLikelyChinese(src.text)) continue;
      missing.push(src);
    }
    if (missing.length === 0) return undefined;

    // 注意：这里**不**用 cancel 标记。translations 是按消息 key 写入的纯 cache，
    // 即使 effect 在请求未完成前因 timeline 轮询重建而再次运行，把延迟到达的
    // 译文写入也是安全且必要的——之前用 cancelled 反而会把好不容易到手的
    // 译文丢掉，导致页面永远卡在"AI 实时翻译中…"。
    missing.forEach((m) => translateInflight.current.add(m.key));
    setTranslating(true);
    translateApi
      .batch(missing.map((m) => m.text), 'zh')
      .then((res) => {
        setTranslations((prev) => {
          const next = { ...prev };
          missing.forEach((m, i) => {
            next[m.key] = res.data.translations?.[i] ?? m.text;
          });
          return next;
        });
      })
      .catch(() => {
        /* keep original on failure */
      })
      .finally(() => {
        missing.forEach((m) => translateInflight.current.delete(m.key));
        setTranslating(false);
      });

    return undefined;
  }, [timeline, translationEnabled, translations, timelineKeyAndText, isLikelyChinese]);

  const renderTimelineItem = useCallback(
    (item: ConversationTimelineItem, useTranslation: boolean) => {
      const src = useTranslation ? timelineKeyAndText(item) : null;
      const tr = src ? translations[src.key] : undefined;
      // 译文未到位时（非中文且尚未缓存），在左侧气泡里显示占位提示。
      const pending =
        useTranslation && !!src && tr == null && !isLikelyChinese(src.text)
          ? 'AI 实时翻译中…'
          : undefined;
      const override = tr ?? pending;
      // 译文已成功生成时，对译文气泡使用打字机效果（占位文本不动画）。
      const translationAnimKey =
        useTranslation && tr != null ? `tr-${item.id}` : undefined;
      if (item.kind === 'message') {
        // 原文气泡：仅 AI 回复使用打字机效果。
        const originalAnimKey =
          !useTranslation && item.message.role === 'assistant' ? `msg-${item.id}` : undefined;
        return (
          <MessageBubble
            key={item.id}
            msg={item.message}
            contentOverride={useTranslation ? override : undefined}
            animateKey={translationAnimKey ?? originalAnimKey}
          />
        );
      }
      const ev = item.event;
      const originalAnimKey =
        !useTranslation && ev.role !== 'human_agent' ? `evt-${item.id}` : undefined;
      return (
        <OutboundEventBubble
          key={item.id}
          event={ev}
          textOverride={useTranslation && ev.type === 'text' ? override : undefined}
          captionOverride={useTranslation && ev.type === 'photo' ? override : undefined}
          animateKey={translationAnimKey ?? originalAnimKey}
        />
      );
    },
    [timelineKeyAndText, translations, isLikelyChinese],
  );

  const pendingCount = stats?.pending_human ?? 0;
  const renderStatItem = (
    label: string,
    value: React.ReactNode,
    options?: { color?: string; onClick?: () => void; emphasizeWhen?: boolean }
  ) => (
    <div
      onClick={options?.onClick}
      style={{
        cursor: options?.onClick ? 'pointer' : 'default',
        display: 'flex',
        flexDirection: 'column',
        gap: 2,
        minWidth: 80,
        padding: '2px 4px',
        borderRadius: 6,
        transition: 'background 0.2s ease',
      }}
      onMouseEnter={(e) => {
        if (options?.onClick) (e.currentTarget as HTMLDivElement).style.background = '#f5f5f5';
      }}
      onMouseLeave={(e) => {
        if (options?.onClick) (e.currentTarget as HTMLDivElement).style.background = 'transparent';
      }}
    >
      <span style={{ fontSize: 11, color: '#8c8c8c', lineHeight: 1.1 }}>{label}</span>
      <span
        style={{
          fontSize: 16,
          fontWeight: 600,
          lineHeight: 1.2,
          color: options?.emphasizeWhen ? options.color : undefined,
        }}
      >
        {value}
      </span>
    </div>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 22,
          padding: '6px 16px',
          background: '#fff',
          borderRadius: 12,
          boxShadow: '0 2px 12px rgba(0,0,0,0.04)',
          border: '1px solid #f0f0f0',
        }}
      >
        {renderStatItem('总对话', stats?.total_conversations ?? 0)}
        {renderStatItem('待人工', pendingCount, {
          color: pendingCount > 0 ? '#fa8c16' : undefined,
          emphasizeWhen: pendingCount > 0,
          onClick: () => setFilter('pending_human'),
        })}
        {renderStatItem('合同', stats?.total_contracts ?? 0)}
        {renderStatItem(
          'Bot 在线',
          `${stats?.active_bots ?? 0}/${stats?.total_bots ?? 0}`
        )}
        <Divider type="vertical" style={{ height: 28 }} />
        <Text type="secondary" style={{ fontSize: 12 }}>
          知识 {stats?.total_knowledge_entries ?? 0} · 文件 {stats?.total_files ?? 0} · 消息{' '}
          {stats?.total_messages ?? 0}
        </Text>
      </div>
      <div
        ref={containerRef}
        style={{
          display: 'flex',
          gap: 0,
          height: PANEL_HEIGHT,
          minHeight: 420,
          maxHeight: PANEL_HEIGHT,
          background: '#fff',
          borderRadius: 12,
          overflow: 'hidden',
          boxShadow: '0 2px 12px rgba(0,0,0,0.06)',
          border: '1px solid #f0f0f0',
          position: 'relative',
        }}
      >
      {/* 左侧：对话列表（minHeight:0 让内部列表在任意会话下都能出现滚动条） */}
      <div
        style={{
          width: listCollapsed ? 0 : listWidth,
          flexShrink: 0,
          alignSelf: 'stretch',
          minHeight: 0,
          display: listCollapsed ? 'none' : 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          borderRight: '1px solid #f0f0f0',
          background: '#fafafa',
        }}
      >
        <div style={{ padding: '12px 12px 6px', display: 'flex', alignItems: 'center', gap: 6 }}>
          <Input
            allowClear
            size="small"
            placeholder="搜索对话…"
            prefix={<SearchOutlined style={{ color: '#bfbfbf' }} />}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ flex: 1 }}
          />
          <Tooltip title="收起对话列表" placement="left">
            <Button
              size="small"
              type="text"
              icon={<MenuFoldOutlined />}
              onClick={() => setListCollapsed(true)}
            />
          </Tooltip>
        </div>
        <Tabs
          size="small"
          activeKey={activeTabKey}
          onChange={(k) => setFilter(k as FilterKey)}
          items={FILTER_TABS.map((t) => ({
            key: t.key,
            label: t.label,
          }))}
          style={{ padding: '0 12px', marginBottom: 0 }}
        />
        <div
          style={{
            flex: 1,
            minHeight: 0,
            overflowY: 'auto',
            overflowX: 'hidden',
            overscrollBehavior: 'contain',
            scrollbarGutter: 'stable',
            WebkitOverflowScrolling: 'touch',
            padding: '8px 12px 16px',
          }}
        >
          <Spin spinning={listLoading}>
            {!listLoading && conversations.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无对话" />
            ) : (
              <List
                rowKey="id"
                dataSource={conversations}
                split={false}
                renderItem={(item) => {
                  const selected = selectedId === item.id;
                  const st = statusConfig(item.status);
                  const showDot = item.status === 'pending_human';
                  const isSimulator = isSimulatorConversation(item);
                  return (
                    <List.Item style={{ padding: '6px 0', border: 'none' }}>
                      <Card
                        size="small"
                        hoverable
                        onClick={() => handleSelectConversation(item.id)}
                        style={{
                          width: '100%',
                          cursor: 'pointer',
                          borderRadius: 10,
                          border: selected ? '1px solid #1890ff' : '1px solid #f0f0f0',
                          background: selected ? '#e6f7ff' : '#fff',
                          transition: 'all 0.2s ease',
                        }}
                        styles={{ body: { padding: '12px 14px' } }}
                      >
                        <Space direction="vertical" size={6} style={{ width: '100%' }}>
                          <div
                            style={{
                              display: 'flex',
                              justifyContent: 'space-between',
                              alignItems: 'flex-start',
                              gap: 8,
                            }}
                          >
                            <Text strong ellipsis style={{ flex: 1 }}>
                              {customerDisplayName(item)}
                            </Text>
                            {showDot ? <Badge status="processing" /> : null}
                          </div>
                          <Space size={[6, 6]} wrap>
                            <Tag color="default">ID #{item.id}</Tag>
                            <Tooltip title={languageLabel(item.language)}>
                              <Tag>{item.language?.toUpperCase() || '—'}</Tag>
                            </Tooltip>
                            <Tag color={st.color}>{st.label}</Tag>
                            {isSimulator ? <Tag color="geekblue">模拟对话</Tag> : null}
                          </Space>
                          {isSimulator ? (
                            <Space size={8} wrap>
                              <Button
                                size="small"
                                icon={<SwapOutlined />}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleOpenSimulator(item.id);
                                }}
                              >
                                打开模拟器
                              </Button>
                              <Button
                                size="small"
                                danger
                                icon={<DeleteOutlined />}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleDeleteSimulatorConversation(item);
                                }}
                              >
                                删除
                              </Button>
                            </Space>
                          ) : null}
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            更新于 {dayjs(item.updated_at).fromNow()}
                          </Text>
                        </Space>
                      </Card>
                    </List.Item>
                  );
                }}
              />
            )}
          </Spin>
        </div>
      </div>

      {/* 拖动分隔条 */}
      {!listCollapsed && (
        <div
          onMouseDown={startResizing}
          title="拖动调整宽度"
          style={{
            width: 6,
            cursor: 'col-resize',
            background: 'transparent',
            position: 'relative',
            flexShrink: 0,
            zIndex: 2,
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLDivElement).style.background = 'rgba(24,144,255,0.12)';
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLDivElement).style.background = 'transparent';
          }}
        >
          <div
            style={{
              position: 'absolute',
              top: 0,
              bottom: 0,
              left: 2,
              width: 2,
              background: '#f0f0f0',
            }}
          />
        </div>
      )}

      {/* 折叠时显示的展开浮动按钮 */}
      {listCollapsed && (
        <Tooltip title="展开对话列表" placement="right">
          <Button
            size="small"
            type="default"
            icon={<MenuUnfoldOutlined />}
            onClick={() => setListCollapsed(false)}
            style={{
              position: 'absolute',
              top: 10,
              left: 8,
              zIndex: 5,
              boxShadow: '0 2px 6px rgba(0,0,0,0.08)',
              background: '#fff',
            }}
          />
        </Tooltip>
      )}

      {/* 右侧：对话详情 */}
      <div
        style={{
          flex: 1,
          minWidth: 0,
          minHeight: 0,
          display: 'flex',
          flexDirection: 'column',
          background: '#f5f5f5',
          overflow: 'hidden',
        }}
      >
        {selectedId == null ? (
          <div
            style={{
              flex: 1,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: 24,
            }}
          >
            <Empty description="选择一个对话查看消息" />
          </div>
        ) : (
          <>
            <div
              style={{
                padding: '16px 20px',
                background: '#fff',
                borderBottom: '1px solid #f0f0f0',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 16,
                flexWrap: 'wrap',
              }}
            >
              <Space align="center" size="middle" style={{ minWidth: 0 }}>
                <Title level={4} style={{ margin: 0 }} ellipsis>
                  {detail ? customerDisplayName(detail) : '…'}
                </Title>
                {detail ? (
                  <>
                    <Tag color="default">ID #{detail.id}</Tag>
                    <Tag color={statusConfig(detail.status).color}>{statusConfig(detail.status).label}</Tag>
                    <Tooltip title="切换全局客服应答模式（影响所有对话）">
                      <Segmented
                        size="small"
                        value={customerServiceSettings?.mode ?? 'ai_auto'}
                        onChange={(val) =>
                          void handleChangeMode(val as CustomerServiceSettings['mode'])
                        }
                        disabled={!customerServiceSettings || modeUpdating}
                        options={[
                          { label: '全 AI', value: 'ai_auto' },
                          { label: '人机协同', value: 'ai_assist' },
                          { label: '纯人工', value: 'human_only' },
                        ]}
                      />
                    </Tooltip>
                  </>
                ) : (
                  <Tag>…</Tag>
                )}
              </Space>
              <Space wrap>
                {detail && isSimulatorConversation(detail) ? (
                  <>
                    <Button
                      icon={<SwapOutlined />}
                      onClick={() => handleOpenSimulator(detail.id)}
                    >
                      打开模拟器
                    </Button>
                    <Button
                      danger
                      icon={<DeleteOutlined />}
                      onClick={() => handleDeleteSimulatorConversation(detail)}
                    >
                      删除模拟对话
                    </Button>
                  </>
                ) : null}
                <Tooltip title="点击生成合同；右侧箭头可发送已生成合同">
                  <Dropdown.Button
                    loading={contractLoading}
                    onClick={() => void openGenerateModal()}
                    menu={{
                      items: [
                        {
                          key: 'generate',
                          icon: <FileTextOutlined />,
                          label: '生成合同',
                          onClick: () => void openGenerateModal(),
                        },
                        {
                          key: 'send',
                          icon: <ExportOutlined />,
                          label: '发送合同给客户',
                          disabled: detail?.status === 'closed',
                          onClick: () => void openSendContractModal(),
                        },
                      ],
                    }}
                  >
                    <FileTextOutlined /> 合同
                  </Dropdown.Button>
                </Tooltip>
                <Button
                  danger
                  icon={<CloseCircleOutlined />}
                  loading={closeLoading}
                  disabled={detail?.status === 'closed'}
                  onClick={handleCloseConversation}
                >
                  关闭对话
                </Button>
                <Tooltip title="开启后左侧实时同步翻译为简体中文">
                  <Space size={6} align="center">
                    <TranslationOutlined style={{ color: translationEnabled ? '#1677ff' : '#bfbfbf' }} />
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      实时翻译
                    </Text>
                    <Switch
                      size="small"
                      checked={translationEnabled}
                      onChange={setTranslationEnabled}
                    />
                    {translationEnabled && translating ? (
                      <LoadingOutlined style={{ color: '#1677ff', fontSize: 12 }} />
                    ) : null}
                  </Space>
                </Tooltip>
              </Space>
            </div>

            {detail?.ai_draft ? (
              <div
                style={{
                  padding: '12px 20px',
                  background: '#fffbe6',
                  borderBottom: '1px solid #f0e6a6',
                }}
              >
                <Card
                  size="small"
                  title={draftTitle(detail)}
                  extra={
                    <Space size={8}>
                      <Tag color="gold">
                        {draftAutoSendLabel(detail, draftCountdownSeconds)}
                      </Tag>
                      {detail.ai_draft.error_message ? <Tag color="red">{detail.ai_draft.error_message}</Tag> : null}
                    </Space>
                  }
                  styles={{ body: { paddingTop: 12 } }}
                >
                  <Space
                    direction="vertical"
                    size="middle"
                    style={{
                      width: '100%',
                      maxHeight: 420,
                      overflowY: 'auto',
                      overflowX: 'hidden',
                      paddingRight: 4,
                    }}
                  >
                    {editingAiDraft ? (
                      <Input.TextArea
                        value={aiDraftText}
                        onChange={(e) => setAiDraftText(e.target.value)}
                        autoSize={{ minRows: 4, maxRows: 10 }}
                      />
                    ) : (
                      <DraftPreview detail={detail} />
                    )}
                    <Space wrap>
                      <Button danger loading={aiDraftCancelling} onClick={() => void handleCancelAiDraft()}>
                        取消
                      </Button>
                      {canEditDraft(detail) ? (
                        <Button
                          icon={<EditOutlined />}
                          onClick={() => void handleToggleEditAiDraft()}
                        >
                          {editingAiDraft ? '取消编辑' : '编辑AI回复'}
                        </Button>
                      ) : null}
                      <Button
                        type="primary"
                        icon={<SendOutlined />}
                        loading={aiDraftSending}
                        onClick={() => void handleSendAiDraft()}
                      >
                        {editingAiDraft ? '发送编辑后的回复' : '直接发送'}
                      </Button>
                    </Space>
                  </Space>
                </Card>
              </div>
            ) : null}

            {translationEnabled ? (
              <div
                style={{
                  flex: 1,
                  display: 'flex',
                  minHeight: 0,
                  overflow: 'hidden',
                }}
              >
                <div
                  style={{
                    flex: 1,
                    minWidth: 0,
                    minHeight: 0,
                    overflowY: 'scroll',
                    overflowX: 'hidden',
                    overscrollBehavior: 'contain',
                    scrollbarGutter: 'stable',
                    background: 'linear-gradient(180deg, #f0f7ff 0%, #f8fbff 100%)',
                    borderRight: '1px solid #e8e8e8',
                    position: 'relative',
                  }}
                >
                  <div
                    style={{
                      position: 'sticky',
                      top: 0,
                      zIndex: 2,
                      padding: '8px 16px',
                      background: '#e6f4ff',
                      borderBottom: '1px solid #bae0ff',
                      fontSize: 12,
                      color: '#1677ff',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 6,
                    }}
                  >
                    <TranslationOutlined /> 简体中文译文
                    {translating ? (
                      <LoadingOutlined style={{ marginLeft: 'auto' }} />
                    ) : null}
                  </div>
                  <div style={{ padding: '20px 20px 20px 24px' }}>
                    <Spin spinning={detailLoading}>
                      {detail && !detailLoading && timeline.length === 0 ? (
                        <Empty description="暂无消息" />
                      ) : timeline.length ? (
                        timeline.map((item) => renderTimelineItem(item, true))
                      ) : null}
                    </Spin>
                  </div>
                </div>
                <div
                  style={{
                    flex: 1,
                    minWidth: 0,
                    minHeight: 0,
                    overflowY: 'scroll',
                    overflowX: 'hidden',
                    overscrollBehavior: 'contain',
                    scrollbarGutter: 'stable',
                    background: 'linear-gradient(180deg, #f0f2f5 0%, #f5f5f5 100%)',
                    position: 'relative',
                  }}
                >
                  <div
                    style={{
                      position: 'sticky',
                      top: 0,
                      zIndex: 2,
                      padding: '8px 16px',
                      background: '#fafafa',
                      borderBottom: '1px solid #e8e8e8',
                      fontSize: 12,
                      color: '#666',
                    }}
                  >
                    原始消息
                  </div>
                  <div style={{ padding: '20px 20px 20px 24px' }}>
                    <Spin spinning={detailLoading}>
                      {detail && !detailLoading && timeline.length === 0 ? (
                        <Empty description="暂无消息" />
                      ) : timeline.length ? (
                        timeline.map((item) => renderTimelineItem(item, false))
                      ) : null}
                    </Spin>
                  </div>
                </div>
              </div>
            ) : (
              <div
                style={{
                  flex: 1,
                  minHeight: 0,
                  overflowY: 'scroll',
                  overflowX: 'hidden',
                  overscrollBehavior: 'contain',
                  scrollbarGutter: 'stable',
                  WebkitOverflowScrolling: 'touch',
                  padding: '20px 20px 20px 24px',
                  background: 'linear-gradient(180deg, #f0f2f5 0%, #f5f5f5 100%)',
                  position: 'relative',
                }}
              >
                <Spin spinning={detailLoading}>
                  {detail && !detailLoading && timeline.length === 0 ? (
                    <Empty description="暂无消息" />
                  ) : timeline.length ? (
                    timeline.map((item) => renderTimelineItem(item, false))
                  ) : null}
                </Spin>
              </div>
            )}

            <div
              style={{
                padding: '12px 16px 16px',
                background: '#fff',
                borderTop: '1px solid #f0f0f0',
              }}
            >
              <Space direction="vertical" size="small" style={{ width: '100%' }}>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  以人工客服身份回复
                </Text>
                <Input.TextArea
                  value={replyText}
                  onChange={(e) => setReplyText(e.target.value)}
                  placeholder="输入回复内容…"
                  autoSize={{ minRows: 2, maxRows: 6 }}
                  onPressEnter={(e) => {
                    if (!e.shiftKey) {
                      e.preventDefault();
                      handleSendReply();
                    }
                  }}
                  disabled={detail?.status === 'closed'}
                />
                <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                  <Button
                    type="primary"
                    icon={<SendOutlined />}
                    loading={replySending}
                    disabled={detail?.status === 'closed'}
                    onClick={handleSendReply}
                  >
                    发送
                  </Button>
                </div>
              </Space>
            </div>
          </>
        )}
      </div>

      <Modal
        title={
          <Space direction="vertical" size={0}>
            <span>
              <FileTextOutlined style={{ marginRight: 8 }} />
              生成合同
            </span>
            <Text type="secondary" style={{ fontSize: 13, fontWeight: 'normal' }}>
              第一步：选择合同正文语言；第二步（可选）：选择 Word 模板
            </Text>
          </Space>
        }
        width={520}
        open={generateModalOpen}
        onCancel={() => setGenerateModalOpen(false)}
        okText="生成"
        confirmLoading={contractLoading}
        onOk={() => void confirmGenerateContract()}
        destroyOnClose
        styles={{ body: { paddingTop: 8 } }}
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <div>
            <Text strong style={{ display: 'block', marginBottom: 10 }}>
              1. 合同输出语言（必选）
            </Text>
            <Select
              size="large"
              style={{ width: '100%' }}
              value={genOutputLang}
              onChange={setGenOutputLang}
              options={CONTRACT_OUTPUT_LANG_OPTIONS}
              placeholder="选择输出语言"
              showSearch
              optionFilterProp="label"
            />
          </div>
          <Divider style={{ margin: '8px 0' }} />
          <div>
            <Text strong style={{ display: 'block', marginBottom: 8 }}>
              2. Word 合同模板（可选）
            </Text>
            <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
              不选则 AI 根据聊天记录从零起草；选择后 AI 会按模板结构填充修订
            </Text>
            <Select
              loading={templatesLoading}
              placeholder="不使用模板"
              allowClear
              style={{ width: '100%' }}
              value={genTemplateId ?? undefined}
              onChange={(v) => setGenTemplateId(v ?? null)}
              options={templates.map((t) => ({
                label: `${t.name}（${t.original_name}）`,
                value: t.id,
              }))}
            />
          </div>
        </Space>
      </Modal>

      <Modal
        title="发送合同给客户"
        open={sendModalOpen}
        onCancel={() => setSendModalOpen(false)}
        okText="发送"
        confirmLoading={sendLoading}
        onOk={() => void confirmSendContract()}
      >
        <Spin spinning={contractsLoading}>
          {convContracts.length === 0 ? (
            <Text type="secondary">该对话下暂无合同，请先在「生成合同」中创建。</Text>
          ) : (
            <Radio.Group
              style={{ width: '100%' }}
              value={sendContractId ?? undefined}
              onChange={(e) => setSendContractId(e.target.value)}
            >
              <Space direction="vertical" style={{ width: '100%' }}>
                {convContracts.map((c) => (
                  <Radio key={c.id} value={c.id}>
                    <Text strong>{c.title}</Text>
                    <Text type="secondary" style={{ marginLeft: 8 }}>
                      {c.status} · {dayjs(c.created_at).format('YYYY-MM-DD HH:mm')}
                    </Text>
                  </Radio>
                ))}
              </Space>
            </Radio.Group>
          )}
        </Spin>
      </Modal>
      </div>
    </div>
  );
}
