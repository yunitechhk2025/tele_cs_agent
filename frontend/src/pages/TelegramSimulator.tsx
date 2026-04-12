import { useCallback, useEffect, useRef, useState } from 'react';
import { Button, Empty, Input, Select, Space, Spin, Typography, message } from 'antd';
import {
  RobotOutlined,
  SendOutlined,
  UserOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { botApi, simulatorApi } from '../api';
import type { Message, TelegramBot } from '../types';

const { Text } = Typography;

/* ─── Telegram-style colours ─────────────────────────────────────────────── */
const TG_BG = '#0e1621';
const TG_PANEL = '#17212b';
const TG_INPUT_BG = '#242f3d';
const TG_USER_BUBBLE = '#2b5278';
const TG_BOT_BUBBLE = '#182533';
const TG_TEXT = '#f5f5f5';
const TG_SECONDARY = '#6d7f8e';
const TG_ACCENT = '#5ca5db';

function Bubble({ msg }: { msg: Message }) {
  const isUser = msg.role === 'user';
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: isUser ? 'flex-end' : 'flex-start',
        marginBottom: 6,
        padding: '0 12px',
      }}
    >
      <div
        style={{
          maxWidth: '72%',
          padding: '8px 12px',
          borderRadius: isUser ? '12px 12px 0 12px' : '12px 12px 12px 0',
          background: isUser ? TG_USER_BUBBLE : TG_BOT_BUBBLE,
          color: TG_TEXT,
          fontSize: 14,
          lineHeight: 1.5,
          wordBreak: 'break-word',
          whiteSpace: 'pre-wrap',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
          {isUser ? (
            <UserOutlined style={{ color: TG_ACCENT, fontSize: 12 }} />
          ) : (
            <RobotOutlined style={{ color: TG_ACCENT, fontSize: 12 }} />
          )}
          <Text style={{ color: TG_ACCENT, fontSize: 12, fontWeight: 600 }}>
            {isUser ? '模拟用户' : 'AI 助手'}
          </Text>
        </div>
        {msg.content}
        <div style={{ textAlign: 'right', marginTop: 4 }}>
          <Text style={{ color: TG_SECONDARY, fontSize: 11 }}>
            {dayjs(msg.created_at).format('HH:mm')}
          </Text>
        </div>
      </div>
    </div>
  );
}

export default function TelegramSimulator() {
  const [bots, setBots] = useState<TelegramBot[]>([]);
  const [selectedBotId, setSelectedBotId] = useState<number | null>(null);
  const [language, setLanguage] = useState('zh');
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputText, setInputText] = useState('');
  const [sending, setSending] = useState(false);
  const [starting, setStarting] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    botApi.list().then(({ data }) => {
      const list = Array.isArray(data) ? data : [];
      setBots(list);
      if (list.length > 0) setSelectedBotId(list[0].id);
    });
  }, []);

  const scrollToBottom = useCallback(() => {
    requestAnimationFrame(() => {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
    });
  }, []);

  const startSession = async () => {
    if (!selectedBotId) {
      message.warning('请先选择一个 Bot');
      return;
    }
    setStarting(true);
    try {
      const { data } = await simulatorApi.createSession(selectedBotId, language);
      setConversationId(data.conversation_id);
      const { data: msgs } = await simulatorApi.getMessages(data.conversation_id);
      setMessages(Array.isArray(msgs) ? msgs : []);
      setTimeout(scrollToBottom, 100);
    } catch {
      message.error('创建模拟对话失败');
    } finally {
      setStarting(false);
    }
  };

  const handleSend = async () => {
    if (!conversationId) return;
    const text = inputText.trim();
    if (!text) return;

    // Optimistic: append user bubble
    const tempUser: Message = {
      id: Date.now(),
      conversation_id: conversationId,
      role: 'user',
      content: text,
      language: null,
      attachment_file_id: null,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, tempUser]);
    setInputText('');
    scrollToBottom();
    setSending(true);

    try {
      await simulatorApi.sendMessage(conversationId, text);
      // Reload full history to capture all bot events saved as messages
      const { data: msgs } = await simulatorApi.getMessages(conversationId);
      setMessages(Array.isArray(msgs) ? msgs : []);
      setTimeout(scrollToBottom, 100);
    } catch {
      message.error('发送消息失败');
    } finally {
      setSending(false);
    }
  };

  const resetSession = () => {
    setConversationId(null);
    setMessages([]);
    setInputText('');
  };

  /* ─── Layout ────────────────────────────────────────────────────────────── */
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'flex-start',
        height: 'calc(100vh - 180px)',
        padding: '0 16px',
      }}
    >
      <div
        style={{
          width: 420,
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          borderRadius: 12,
          overflow: 'hidden',
          background: TG_BG,
          boxShadow: '0 4px 24px rgba(0,0,0,0.35)',
          border: `1px solid ${TG_PANEL}`,
        }}
      >
        {/* Header bar */}
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
            <Text style={{ color: TG_TEXT, fontWeight: 600, fontSize: 15 }}>Telegram 模拟器</Text>
          </Space>
          {conversationId && (
            <Button
              size="small"
              type="text"
              icon={<ReloadOutlined style={{ color: TG_SECONDARY }} />}
              onClick={resetSession}
              style={{ color: TG_SECONDARY }}
            >
              重置
            </Button>
          )}
        </div>

        {/* Session setup or chat */}
        {conversationId == null ? (
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
              style={{ width: 280 }}
              placeholder="选择 Bot"
              value={selectedBotId}
              onChange={setSelectedBotId}
              options={bots.map((b) => ({ value: b.id, label: b.name }))}
            />
            <Select
              style={{ width: 280 }}
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
              开始对话
            </Button>
          </div>
        ) : (
          <>
            {/* Messages */}
            <div
              ref={scrollRef}
              style={{
                flex: 1,
                overflowY: 'auto',
                overflowX: 'hidden',
                padding: '12px 0',
                background: TG_BG,
              }}
            >
              {messages.length === 0 ? (
                <Empty
                  description={<Text style={{ color: TG_SECONDARY }}>暂无消息</Text>}
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                />
              ) : (
                messages
                  .filter((m) => m.role === 'user' || m.role === 'assistant')
                  .map((m) => <Bubble key={m.id} msg={m} />)
              )}
              {sending && (
                <div style={{ display: 'flex', justifyContent: 'flex-start', padding: '0 12px' }}>
                  <div
                    style={{
                      padding: '10px 16px',
                      borderRadius: '12px 12px 12px 0',
                      background: TG_BOT_BUBBLE,
                    }}
                  >
                    <Spin size="small" />
                    <Text style={{ color: TG_SECONDARY, marginLeft: 8, fontSize: 13 }}>
                      正在输入…
                    </Text>
                  </div>
                </div>
              )}
            </div>

            {/* Input */}
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
