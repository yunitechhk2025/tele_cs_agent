import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { flushSync } from 'react-dom';
import { Button, Empty, Input, Select, Space, Spin, Typography, message } from 'antd';
import {
  LinkOutlined,
  ReloadOutlined,
  RobotOutlined,
  SendOutlined,
  UserOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { Link, useSearchParams } from 'react-router-dom';
import { botApi, conversationApi, simulatorApi } from '../api';
import type { Message, SimulatorOutgoingEvent, TelegramBot } from '../types';
import { RichText } from '../components/RichText';

const { Text } = Typography;

const TG_BG = '#0e1621';
const TG_PANEL = '#17212b';
const TG_INPUT_BG = '#242f3d';
const TG_USER_BUBBLE = '#2b5278';
const TG_ASSISTANT_BUBBLE = '#182533';
const TG_HUMAN_BUBBLE = '#30445a';
const TG_TEXT = '#f5f5f5';
const TG_SECONDARY = '#6d7f8e';
const TG_ACCENT = '#5ca5db';
const SIMULATOR_STORAGE_KEY = 'telegram-simulator-session';

type TimelineItem =
  | {
      id: string;
      kind: 'text';
      role: 'user' | 'assistant' | 'human_agent';
      content: string;
      created_at: string;
    }
  | {
      id: string;
      kind: 'photo' | 'document';
      role: 'assistant';
      url: string;
      caption?: string;
      filename?: string;
      created_at: string;
    };

type PersistedSimulatorState = {
  conversationId: number | null;
  selectedBotId: number | null;
  language: string;
  ephemeralEvents: TimelineItem[];
};

function readPersistedState(): PersistedSimulatorState | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(SIMULATOR_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as PersistedSimulatorState;
    return {
      conversationId: typeof parsed.conversationId === 'number' ? parsed.conversationId : null,
      selectedBotId: typeof parsed.selectedBotId === 'number' ? parsed.selectedBotId : null,
      language: typeof parsed.language === 'string' && parsed.language ? parsed.language : 'zh',
      ephemeralEvents: Array.isArray(parsed.ephemeralEvents) ? parsed.ephemeralEvents : [],
    };
  } catch {
    return null;
  }
}

function writePersistedState(state: PersistedSimulatorState) {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(SIMULATOR_STORAGE_KEY, JSON.stringify(state));
}

function clearPersistedState() {
  if (typeof window === 'undefined') return;
  window.localStorage.removeItem(SIMULATOR_STORAGE_KEY);
}

function isMediaEvent(event: SimulatorOutgoingEvent): event is SimulatorOutgoingEvent & { type: 'photo' | 'document' } {
  return event.type === 'photo' || event.type === 'document';
}

function mapMessages(messages: Message[]): TimelineItem[] {
  return messages.map((msg) => ({
    id: `msg-${msg.id}`,
    kind: 'text',
    role: msg.role === 'human_agent' ? 'human_agent' : (msg.role as 'user' | 'assistant'),
    content: msg.content,
    created_at: msg.created_at,
  }));
}

function Bubble({ item }: { item: TimelineItem }) {
  const isUser = item.role === 'user';
  const isHuman = item.role === 'human_agent';
  const bg = isUser ? TG_USER_BUBBLE : isHuman ? TG_HUMAN_BUBBLE : TG_ASSISTANT_BUBBLE;
  const name = isUser ? '模拟用户' : isHuman ? '人工客服' : 'AI 助手';
  const icon = isUser ? <UserOutlined /> : <RobotOutlined />;

  return (
    <div
      style={{
        display: 'flex',
        justifyContent: isUser ? 'flex-end' : 'flex-start',
        marginBottom: 8,
        padding: '0 12px',
      }}
    >
      <div
        style={{
          maxWidth: '78%',
          padding: '8px 12px',
          borderRadius: isUser ? '12px 12px 0 12px' : '12px 12px 12px 0',
          background: bg,
          color: TG_TEXT,
          fontSize: 14,
          lineHeight: 1.5,
          wordBreak: 'break-word',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
          <span style={{ color: TG_ACCENT, fontSize: 12 }}>{icon}</span>
          <Text style={{ color: TG_ACCENT, fontSize: 12, fontWeight: 600 }}>{name}</Text>
        </div>
        {item.kind === 'text' && (
          <div style={{ whiteSpace: 'pre-wrap' }}><RichText text={item.content} /></div>
        )}
        {item.kind === 'photo' && (
          <div>
            <img
              src={item.url}
              alt={item.caption || 'scene'}
              style={{ width: '100%', borderRadius: 10, display: 'block' }}
            />
            {item.caption && (
              <div style={{ marginTop: 6, whiteSpace: 'pre-wrap' }}>
                <RichText text={item.caption} />
              </div>
            )}
          </div>
        )}
        {item.kind === 'document' && (
          <div>
            <a
              href={item.url}
              target="_blank"
              rel="noreferrer"
              style={{ color: '#9fd4ff' }}
            >
              <LinkOutlined /> {item.filename || 'Document'}
            </a>
            {item.caption && (
              <div style={{ marginTop: 6, whiteSpace: 'pre-wrap' }}>
                <RichText text={item.caption} />
              </div>
            )}
          </div>
        )}
        <div style={{ textAlign: 'right', marginTop: 4 }}>
          <Text style={{ color: TG_SECONDARY, fontSize: 11 }}>
            {dayjs(item.created_at).format('HH:mm:ss')}
          </Text>
        </div>
      </div>
    </div>
  );
}

export default function TelegramSimulator() {
  const [searchParams] = useSearchParams();
  const [bots, setBots] = useState<TelegramBot[]>([]);
  const [selectedBotId, setSelectedBotId] = useState<number | null>(null);
  const [language, setLanguage] = useState('zh');
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [persistedEvents, setPersistedEvents] = useState<TimelineItem[]>([]);
  const [ephemeralEvents, setEphemeralEvents] = useState<TimelineItem[]>([]);
  const [inputText, setInputText] = useState('');
  const [sending, setSending] = useState(false);
  const [starting, setStarting] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const restoredRef = useRef(false);
  const queryConversationId = useMemo(() => {
    const raw = searchParams.get('conversationId');
    if (!raw) return null;
    const parsed = Number(raw);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }, [searchParams]);

  const loadMessages = useCallback(async (targetConversationId: number) => {
    const { data } = await simulatorApi.getMessages(targetConversationId);
    setMessages(Array.isArray(data) ? data : []);
  }, []);

  const loadEvents = useCallback(async (targetConversationId: number) => {
    const { data } = await simulatorApi.getEvents(targetConversationId);
    const items = (Array.isArray(data) ? data : [])
      .filter((event) => event.type === 'text' || event.type === 'photo' || event.type === 'document')
      .map<TimelineItem>((event) => {
        if (event.type === 'text') {
          return {
            id: event.id,
            kind: 'text',
            role: event.role === 'human_agent' ? 'human_agent' : (event.role as 'user' | 'assistant'),
            content: event.text || '',
            created_at: event.created_at,
          };
        }
        return {
          id: event.id,
          kind: event.type,
          role: 'assistant',
          url: event.url || '',
          caption: event.caption,
          filename: event.filename,
          created_at: event.created_at,
        };
      });
    setPersistedEvents(items);
  }, []);

  useEffect(() => {
    const persisted = readPersistedState();
    if (queryConversationId != null) {
      setConversationId(queryConversationId);
    } else if (persisted) {
      setSelectedBotId(persisted.selectedBotId);
      setLanguage(persisted.language);
      setConversationId(persisted.conversationId);
      setEphemeralEvents(persisted.ephemeralEvents);
    }
    restoredRef.current = true;
  }, [queryConversationId]);

  useEffect(() => {
    botApi.list().then(({ data }) => {
      const list = Array.isArray(data) ? data : [];
      setBots(list);
      if (list.length > 0) {
        setSelectedBotId((current) => {
          if (current && list.some((bot) => bot.id === current)) return current;
          return list[0].id;
        });
      }
    });
  }, []);

  useEffect(() => {
    if (queryConversationId == null) return;
    conversationApi.get(queryConversationId).then(({ data }) => {
      setSelectedBotId(data.bot_id ?? null);
      setLanguage(data.language || 'zh');
      setConversationId(data.id);
    }).catch(() => {
      message.error('加载指定模拟会话失败');
    });
  }, [queryConversationId]);

  useEffect(() => {
    if (!conversationId) return undefined;
    const timer = window.setInterval(() => {
      Promise.all([loadMessages(conversationId), loadEvents(conversationId)]).catch(() => {
        message.warning('上次模拟会话无法恢复，已清空当前状态');
        clearPersistedState();
        setConversationId(null);
        setMessages([]);
        setPersistedEvents([]);
        setEphemeralEvents([]);
      });
    }, 4000);
    return () => window.clearInterval(timer);
  }, [conversationId, loadEvents, loadMessages]);

  useEffect(() => {
    if (!conversationId) return;
    Promise.all([loadMessages(conversationId), loadEvents(conversationId)]).catch(() => {
      message.warning('上次模拟会话无法恢复，已清空当前状态');
      clearPersistedState();
      setConversationId(null);
      setMessages([]);
      setPersistedEvents([]);
      setEphemeralEvents([]);
    });
  }, [conversationId, loadEvents, loadMessages]);

  useEffect(() => {
    if (!restoredRef.current) return;
    if (!conversationId && !selectedBotId && language === 'zh' && ephemeralEvents.length === 0) {
      clearPersistedState();
      return;
    }
    writePersistedState({
      conversationId,
      selectedBotId,
      language,
      ephemeralEvents,
    });
  }, [conversationId, selectedBotId, language, ephemeralEvents]);

  const stickToBottomRef = useRef<boolean>(true);

  const handleScroll = useCallback(() => {
    const node = scrollRef.current;
    if (!node) return;
    const distance = node.scrollHeight - node.scrollTop - node.clientHeight;
    stickToBottomRef.current = distance < 60;
  }, []);

  const scrollToBottom = useCallback((force = false) => {
    requestAnimationFrame(() => {
      const node = scrollRef.current;
      if (!node) return;
      if (!force && !stickToBottomRef.current) return;
      node.scrollTo({ top: node.scrollHeight, behavior: 'smooth' });
    });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, ephemeralEvents, scrollToBottom]);

  useEffect(() => {
    stickToBottomRef.current = true;
    scrollToBottom(true);
  }, [conversationId, scrollToBottom]);

  const timeline = useMemo(() => {
    const textItems = mapMessages(messages);
    const persistedTextKeys = new Set<string>();
    textItems.forEach((item) => {
      if (item.kind === 'text') {
        persistedTextKeys.add(`${item.role}\n${item.content.trim()}`);
      }
    });
    persistedEvents.forEach((item) => {
      if (item.kind === 'text') {
        persistedTextKeys.add(`${item.role}\n${item.content.trim()}`);
      }
    });
    const dedupedEphemeral = ephemeralEvents.filter((item) => {
      if (item.kind === 'text') {
        const key = `${item.role}\n${item.content.trim()}`;
        return !persistedTextKeys.has(key);
      }
      return !persistedEvents.some(
        (persisted) =>
          persisted.kind === item.kind &&
          persisted.role === item.role &&
          'url' in persisted &&
          persisted.url === item.url,
      );
    });
    return [...textItems, ...persistedEvents, ...dedupedEphemeral].sort((a, b) => a.created_at.localeCompare(b.created_at));
  }, [messages, persistedEvents, ephemeralEvents]);

  const startSession = async () => {
    if (!selectedBotId) {
      message.warning('请先选择一个 Bot');
      return;
    }
    setStarting(true);
    try {
      const { data } = await simulatorApi.createSession(selectedBotId, language);
      setConversationId(data.conversation_id);
      setPersistedEvents([]);
      setEphemeralEvents([]);
      await Promise.all([loadMessages(data.conversation_id), loadEvents(data.conversation_id)]);
    } catch {
      message.error('创建模拟会话失败');
    } finally {
      setStarting(false);
    }
  };

  const handleSend = async () => {
    if (!conversationId) return;
    const text = inputText.trim();
    if (!text) return;
    setSending(true);
    setInputText('');
    try {
      const { data } = await simulatorApi.sendMessage(conversationId, text);
      const outgoingEvents = (data.outgoing || [])
        .filter((event) => event.type === 'text' || isMediaEvent(event))
        .map<TimelineItem>((event, index) => ({
          id: event.id || `evt-${Date.now()}-${index}`,
          ...(event.type === 'text'
            ? {
                kind: 'text' as const,
                role: event.role === 'human_agent' ? 'human_agent' : (event.role as 'user' | 'assistant'),
                content: event.text || '',
                created_at: event.created_at,
              }
            : {
                kind: event.type,
                role: 'assistant' as const,
                url: event.url || '',
                caption: event.caption,
                filename: event.filename,
                created_at: event.created_at,
              }),
        }));
      flushSync(() => {
        setEphemeralEvents((prev) => [...prev, ...outgoingEvents]);
        setSending(false);
      });
      void Promise.all([loadMessages(conversationId), loadEvents(conversationId)]).catch(() => {
        /* polling will retry */
      });
    } catch {
      message.error('发送失败');
      setSending(false);
    } finally {
      // setSending is handled above so outgoing events can render in the same commit as spinner removal.
    }
  };

  const resetSession = () => {
    setConversationId(null);
    setMessages([]);
    setPersistedEvents([]);
    setEphemeralEvents([]);
    setInputText('');
    clearPersistedState();
  };

  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'center',
        padding: '8px 0 28px',
        minHeight: 'calc(100vh - 180px)',
        overflowY: 'auto',
      }}
    >
      <div
        style={{
          width: 'min(100%, 430px)',
          height: 'min(calc(100vh - 220px), 764px)',
          minHeight: 720,
          display: 'flex',
          flexDirection: 'column',
          borderRadius: 20,
          overflow: 'hidden',
          background: TG_BG,
          boxShadow: '0 4px 24px rgba(0,0,0,0.35)',
          border: `1px solid ${TG_PANEL}`,
        }}
      >
        <div
          style={{
            padding: '12px 16px',
            background: TG_PANEL,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            borderBottom: `1px solid ${TG_INPUT_BG}`,
          }}
        >
          <Space>
            <RobotOutlined style={{ color: TG_ACCENT, fontSize: 18 }} />
            <Text style={{ color: TG_TEXT, fontWeight: 600, fontSize: 15 }}>Telegram 模拟对话</Text>
            {conversationId ? (
              <Text
                style={{
                  color: '#9fd4ff',
                  fontSize: 12,
                  padding: '2px 8px',
                  borderRadius: 999,
                  background: 'rgba(92,165,219,0.14)',
                  border: '1px solid rgba(92,165,219,0.32)',
                }}
              >
                ID #{conversationId}
              </Text>
            ) : null}
          </Space>
          <Space>
            {conversationId && (
              <Link to={`/conversations/${conversationId}`}>
                <Button size="small" icon={<LinkOutlined />}>打开会话</Button>
              </Link>
            )}
            <Button size="small" icon={<ReloadOutlined />} onClick={resetSession}>重置</Button>
          </Space>
        </div>

        {!conversationId ? (
          <div
            style={{
              flex: 1,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 16,
              padding: 24,
            }}
          >
            <RobotOutlined style={{ fontSize: 48, color: TG_ACCENT, opacity: 0.6 }} />
            <Text style={{ color: TG_SECONDARY }}>选择 Bot 并开始模拟对话</Text>
            <Select
              style={{ width: 300 }}
              placeholder="选择 Bot"
              value={selectedBotId ?? undefined}
              onChange={setSelectedBotId}
              options={bots.map((bot) => ({ value: bot.id, label: bot.name }))}
            />
            <Select
              style={{ width: 300 }}
              value={language}
              onChange={setLanguage}
              options={[
                { value: 'zh', label: '中文' },
                { value: 'en', label: 'English' },
                { value: 'ja', label: '日本語' },
                { value: 'ko', label: '한국어' },
                { value: 'es', label: 'Español' },
                { value: 'fr', label: 'Français' },
              ]}
            />
            <Button type="primary" loading={starting} onClick={startSession}>
              开始模拟
            </Button>
            {conversationId && (
              <Text style={{ color: TG_SECONDARY }}>
                已恢复模拟会话 #{conversationId}
              </Text>
            )}
          </div>
        ) : (
          <>
            <div
              ref={scrollRef}
              onScroll={handleScroll}
              style={{
                flex: 1,
                overflowY: 'auto',
                overflowX: 'hidden',
                padding: '12px 0',
                background: TG_BG,
              }}
            >
              {timeline.length === 0 ? (
                <Empty
                  description={<Text style={{ color: TG_SECONDARY }}>暂无消息</Text>}
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                />
              ) : (
                timeline.map((item) => <Bubble key={item.id} item={item} />)
              )}
              {sending && (
                <div style={{ display: 'flex', justifyContent: 'flex-start', padding: '0 12px' }}>
                  <div
                    style={{
                      padding: '10px 16px',
                      borderRadius: '12px 12px 12px 0',
                      background: TG_ASSISTANT_BUBBLE,
                      display: 'inline-flex',
                      alignItems: 'center',
                    }}
                  >
                    <Spin size="small" />
                  </div>
                </div>
              )}
            </div>

            <div
              style={{
                padding: '10px 12px',
                background: TG_PANEL,
                borderTop: `1px solid ${TG_INPUT_BG}`,
                display: 'flex',
                gap: 8,
                alignItems: 'flex-end',
              }}
            >
              <Input.TextArea
                value={inputText}
                onChange={(e) => setInputText(e.target.value)}
                placeholder="发送消息…"
                autoSize={{ minRows: 1, maxRows: 4 }}
                onPressEnter={(e) => {
                  if (!e.shiftKey) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
                disabled={sending}
                style={{
                  flex: 1,
                  background: TG_INPUT_BG,
                  border: 'none',
                  color: TG_TEXT,
                  borderRadius: 8,
                }}
              />
              <Button
                type="primary"
                shape="circle"
                icon={<SendOutlined />}
                loading={sending}
                onClick={handleSend}
                style={{ background: TG_ACCENT, border: 'none', flexShrink: 0 }}
              />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
