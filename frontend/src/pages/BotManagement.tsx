import { useCallback, useEffect, useState } from 'react';
import {
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  ApiOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  DeleteOutlined,
  EditOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  PlusOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { botApi } from '../api';
import type { TelegramBot } from '../types';

const { Title, Text } = Typography;
const { TextArea } = Input;

export default function BotManagement() {
  const [bots, setBots] = useState<TelegramBot[]>([]);
  const [loading, setLoading] = useState(false);

  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createForm] = Form.useForm();

  const [editOpen, setEditOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editingBot, setEditingBot] = useState<TelegramBot | null>(null);
  const [editForm] = Form.useForm();

  const loadBots = useCallback(async () => {
    setLoading(true);
    try {
      const res = await botApi.list();
      setBots(res.data);
    } catch {
      message.error('加载 Bot 列表失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadBots();
  }, [loadBots]);

  const handleCreate = async () => {
    try {
      const values = await createForm.validateFields();
      setCreating(true);
      await botApi.create({
        name: values.name,
        token: values.token,
        admin_chat_id: values.admin_chat_id || '',
        welcome_message: values.welcome_message || '',
        description: values.description || '',
        is_active: values.is_active ?? true,
      });
      message.success('Bot 创建成功');
      setCreateOpen(false);
      createForm.resetFields();
      await loadBots();
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      message.error(typeof detail === 'string' ? detail : '创建 Bot 失败');
    } finally {
      setCreating(false);
    }
  };

  const openEdit = (bot: TelegramBot) => {
    setEditingBot(bot);
    editForm.setFieldsValue({
      name: bot.name,
      token: '',
      admin_chat_id: bot.admin_chat_id,
      welcome_message: bot.welcome_message,
      description: bot.description,
      is_active: bot.is_active,
    });
    setEditOpen(true);
  };

  const handleEdit = async () => {
    if (!editingBot) return;
    try {
      const values = await editForm.validateFields();
      setEditing(true);
      const data: any = {
        name: values.name,
        admin_chat_id: values.admin_chat_id || '',
        welcome_message: values.welcome_message || '',
        description: values.description || '',
        is_active: values.is_active,
      };
      if (values.token && values.token.trim()) {
        data.token = values.token.trim();
      }
      await botApi.update(editingBot.id, data);
      message.success('Bot 更新成功');
      setEditOpen(false);
      setEditingBot(null);
      await loadBots();
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      message.error(typeof detail === 'string' ? detail : '更新 Bot 失败');
    } finally {
      setEditing(false);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await botApi.delete(id);
      message.success('Bot 已删除');
      await loadBots();
    } catch {
      message.error('删除 Bot 失败');
    }
  };

  const handleToggleRunning = async (bot: TelegramBot) => {
    try {
      if (bot.is_running) {
        await botApi.stop(bot.id);
        message.success(`${bot.name} 已停止`);
      } else {
        await botApi.start(bot.id);
        message.success(`${bot.name} 已启动`);
      }
      await loadBots();
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      message.error(typeof detail === 'string' ? detail : '操作失败');
    }
  };

  const columns: ColumnsType<TelegramBot> = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, record) => (
        <Space direction="vertical" size={0}>
          <Text strong>{name}</Text>
          {record.bot_username && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              @{record.bot_username}
            </Text>
          )}
        </Space>
      ),
    },
    {
      title: 'Token',
      dataIndex: 'token_masked',
      key: 'token_masked',
      width: 200,
      render: (t: string) => (
        <Text code style={{ fontSize: 12 }}>{t}</Text>
      ),
    },
    {
      title: '状态',
      key: 'status',
      width: 120,
      align: 'center',
      render: (_, record) => {
        if (record.is_running) {
          return <Tag icon={<CheckCircleOutlined />} color="success">运行中</Tag>;
        }
        if (record.is_active) {
          return <Tag icon={<PauseCircleOutlined />} color="warning">已停止</Tag>;
        }
        return <Tag icon={<CloseCircleOutlined />} color="default">已禁用</Tag>;
      },
    },
    {
      title: '管理员 ID',
      dataIndex: 'admin_chat_id',
      key: 'admin_chat_id',
      width: 140,
      render: (id: string) => id || <Text type="secondary">—</Text>,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      render: (d: string) => dayjs(d).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 240,
      fixed: 'right',
      render: (_, record) => (
        <Space size="small" wrap>
          <Tooltip title={record.is_running ? '停止' : '启动'}>
            <Button
              type="link"
              size="small"
              icon={record.is_running ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
              onClick={() => void handleToggleRunning(record)}
            >
              {record.is_running ? '停止' : '启动'}
            </Button>
          </Tooltip>
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => openEdit(record)}
          >
            编辑
          </Button>
          <Popconfirm
            title="确认删除此 Bot？"
            description="删除后将停止运行并清除配置。"
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            onConfirm={() => void handleDelete(record.id)}
          >
            <Button type="link" danger size="small" icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Card
        bordered={false}
        style={{
          marginBottom: 16,
          borderRadius: 8,
          boxShadow: '0 1px 2px rgba(0,0,0,0.03)',
        }}
      >
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Space
            align="start"
            style={{ width: '100%', justifyContent: 'space-between', flexWrap: 'wrap', gap: 16 }}
          >
            <Space align="start">
              <ApiOutlined style={{ fontSize: 26, color: '#1677ff', marginTop: 4 }} />
              <div>
                <Title level={4} style={{ margin: 0 }}>
                  Bot 管理
                </Title>
                <Text type="secondary">
                  创建和管理 Telegram Bot，支持多 Bot 同时运行
                </Text>
              </div>
            </Space>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
              创建 Bot
            </Button>
          </Space>
        </Space>
      </Card>

      <Card bordered={false} style={{ borderRadius: 8 }}>
        <Table<TelegramBot>
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={bots}
          pagination={{ pageSize: 10, showSizeChanger: true }}
          scroll={{ x: 900 }}
        />
      </Card>

      {/* 创建 Bot 弹窗 */}
      <Modal
        title="创建 Telegram Bot"
        open={createOpen}
        onCancel={() => {
          setCreateOpen(false);
          createForm.resetFields();
        }}
        okText="创建"
        cancelText="取消"
        confirmLoading={creating}
        onOk={() => void handleCreate()}
        destroyOnClose
        width={600}
      >
        <Form form={createForm} layout="vertical" style={{ marginTop: 8 }}
          initialValues={{ is_active: true }}
        >
          <Form.Item
            name="name"
            label="Bot 名称"
            rules={[{ required: true, message: '请输入 Bot 名称' }]}
          >
            <Input placeholder="例如：客服 Bot 1" />
          </Form.Item>
          <Form.Item
            name="token"
            label="Bot Token"
            rules={[{ required: true, message: '请输入 Bot Token' }]}
            extra="从 @BotFather 获取的 Token"
          >
            <Input.Password placeholder="123456:ABC-DEF..." autoComplete="off" />
          </Form.Item>
          <Form.Item
            name="admin_chat_id"
            label="管理员 Chat ID"
            extra="接收转人工通知的 Telegram Chat ID"
          >
            <Input placeholder="可选" />
          </Form.Item>
          <Form.Item
            name="welcome_message"
            label="欢迎语"
            extra="用户发送 /start 时的回复，留空使用默认多语言欢迎语"
          >
            <TextArea rows={3} placeholder="可选自定义欢迎语" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input placeholder="可选备注" />
          </Form.Item>
          <Form.Item name="is_active" label="创建后立即启动" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑 Bot 弹窗 */}
      <Modal
        title="编辑 Bot"
        open={editOpen}
        onCancel={() => {
          setEditOpen(false);
          setEditingBot(null);
        }}
        okText="保存"
        cancelText="取消"
        confirmLoading={editing}
        onOk={() => void handleEdit()}
        destroyOnClose
        width={600}
      >
        <Form form={editForm} layout="vertical" style={{ marginTop: 8 }}>
          <Form.Item
            name="name"
            label="Bot 名称"
            rules={[{ required: true, message: '请输入 Bot 名称' }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="token"
            label="Bot Token"
            extra={`当前 Token: ${editingBot?.token_masked ?? '—'}。留空表示不修改。`}
          >
            <Input.Password placeholder="输入新 Token（留空不修改）" autoComplete="off" />
          </Form.Item>
          <Form.Item name="admin_chat_id" label="管理员 Chat ID">
            <Input />
          </Form.Item>
          <Form.Item name="welcome_message" label="欢迎语">
            <TextArea rows={3} />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input />
          </Form.Item>
          <Form.Item name="is_active" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
