import { useCallback, useEffect, useMemo, useState } from 'react';
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
  Empty,
  Input,
  List,
  Modal,
  Radio,
  Select,
  Space,
  Spin,
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
  RobotOutlined,
  SearchOutlined,
  SendOutlined,
  SwapOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { conversationApi, contractApi, contractTemplateApi, settingsApi } from '../api';
import type {
  Contract,
  ContractTemplate,
  Conversation,
  ConversationDetail,
  CustomerServiceSettings,
  Message,
} from '../types';

dayjs.extend(relativeTime);
dayjs.extend(utc);
dayjs.locale('zh-cn');

const { Text, Title } = Typography;

const PANEL_HEIGHT = 'calc(100vh - 180px)';

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

function modeConfig(mode?: CustomerServiceSettings['mode']) {
  switch (mode) {
    case 'ai_auto':
      return { text: 'mode1: ai_auto', color: 'blue' as const, label: '模式1：全AI客服答复' };
    case 'ai_assist':
      return { text: 'mode2: ai_assist', color: 'gold' as const, label: '模式2：人工确认AI生成内容后答复' };
    case 'human_only':
      return { text: 'mode3: human_only', color: 'volcano' as const, label: '模式3：无AI，完全人工客服答复' };
    default:
      return { text: 'mode?: unknown', color: 'default' as const, label: '未知模式' };
  }
}

function draftAutoSendLabel(detail: ConversationDetail | null, draftCountdownSeconds: number | null) {
  if (!detail?.ai_draft) return '—';
  if (detail.ai_draft.auto_send_paused) return '已暂停自动发送';
  return `${draftCountdownSeconds ?? '—'} 秒后自动发送`;
}

function MessageBubble({ msg }: { msg: Message }) {
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
          {msg.content}
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

  useEffect(() => {
    loadList();
  }, [loadList]);

  useEffect(() => {
    void loadCustomerServiceSettings();
  }, [loadCustomerServiceSettings]);

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
  const currentMode = modeConfig(customerServiceSettings?.mode);

  return (
    <div
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
      }}
    >
      {/* 左侧：对话列表（minHeight:0 让内部列表在任意会话下都能出现滚动条） */}
      <div
        style={{
          width: 350,
          flexShrink: 0,
          alignSelf: 'stretch',
          minHeight: 0,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          borderRight: '1px solid #f0f0f0',
          background: '#fafafa',
        }}
      >
        <div style={{ padding: 16, paddingBottom: 8 }}>
          <Input
            allowClear
            size="large"
            placeholder="搜索对话…"
            prefix={<SearchOutlined style={{ color: '#bfbfbf' }} />}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
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
                    <Tooltip title={currentMode.label}>
                      <Tag color={currentMode.color}>{currentMode.text}</Tag>
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
                <Tooltip title="选择模板后根据聊天记录生成合同">
                  <Button
                    icon={<FileTextOutlined />}
                    loading={contractLoading}
                    onClick={() => void openGenerateModal()}
                  >
                    生成合同
                  </Button>
                </Tooltip>
                <Tooltip title="将已生成的合同以消息形式发送给客户">
                  <Button
                    icon={<ExportOutlined />}
                    onClick={() => void openSendContractModal()}
                    disabled={detail?.status === 'closed'}
                  >
                    发送合同
                  </Button>
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
                  title="AI 待确认回复"
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
                  <Space direction="vertical" size="middle" style={{ width: '100%' }}>
                    {editingAiDraft ? (
                      <Input.TextArea
                        value={aiDraftText}
                        onChange={(e) => setAiDraftText(e.target.value)}
                        autoSize={{ minRows: 4, maxRows: 10 }}
                      />
                    ) : (
                      <div
                        style={{
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-word',
                          lineHeight: 1.6,
                          fontSize: 14,
                        }}
                      >
                        {detail.ai_draft.draft_text}
                      </div>
                    )}
                    <Space wrap>
                      <Button danger loading={aiDraftCancelling} onClick={() => void handleCancelAiDraft()}>
                        取消
                      </Button>
                      <Button
                        icon={<EditOutlined />}
                        onClick={() => void handleToggleEditAiDraft()}
                      >
                        {editingAiDraft ? '取消编辑' : '编辑AI回复'}
                      </Button>
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
                {detail && !detailLoading && (!detail.messages || detail.messages.length === 0) ? (
                  <Empty description="暂无消息" />
                ) : detail?.messages?.length ? (
                  [...detail.messages]
                    .sort((a, b) => dayjs(a.created_at).valueOf() - dayjs(b.created_at).valueOf())
                    .map((m) => <MessageBubble key={m.id} msg={m} />)
                ) : null}
              </Spin>
            </div>

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
  );
}
