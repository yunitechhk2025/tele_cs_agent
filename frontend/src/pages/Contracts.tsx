import { useCallback, useEffect, useState } from 'react';
import {
  Table,
  Button,
  Select,
  Tag,
  Popconfirm,
  message,
  Space,
  Typography,
  Card,
  Drawer,
  Input,
  Tabs,
  Modal,
  Form,
  Upload,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { UploadFile } from 'antd/es/upload/interface';
import {
  FileTextOutlined,
  DeleteOutlined,
  EyeOutlined,
  EditOutlined,
  PrinterOutlined,
  CopyOutlined,
  PlusOutlined,
  DownloadOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { contractApi, contractTemplateApi } from '../api';
import type { Contract, ContractTemplate } from '../types';

const { Title, Text } = Typography;
const { TextArea } = Input;

const STATUS_OPTIONS = [
  { label: '全部', value: 'all' },
  { label: '草稿', value: 'draft' },
  { label: '已审核', value: 'reviewed' },
  { label: '已批准', value: 'approved' },
  { label: '已发送', value: 'sent' },
] as const;

const EDIT_STATUS_OPTIONS = STATUS_OPTIONS.filter((o) => o.value !== 'all');

function statusTagColor(status: string): string {
  const s = status.toLowerCase();
  const map: Record<string, string> = {
    draft: 'blue',
    reviewed: 'orange',
    approved: 'green',
    sent: 'purple',
  };
  return map[s] ?? 'default';
}

function formatStatusLabel(status: string): string {
  const s = status.toLowerCase();
  const found = EDIT_STATUS_OPTIONS.find((o) => o.value === s);
  return found ? found.label : status;
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export default function Contracts() {
  const [activeTab, setActiveTab] = useState('contracts');

  const [contracts, setContracts] = useState<Contract[]>([]);
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editTitle, setEditTitle] = useState('');
  const [editContent, setEditContent] = useState('');
  const [editStatus, setEditStatus] = useState<string>('draft');

  const [templates, setTemplates] = useState<ContractTemplate[]>([]);
  const [templatesLoading, setTemplatesLoading] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadSubmitting, setUploadSubmitting] = useState(false);
  const [uploadForm] = Form.useForm();
  const [uploadFileList, setUploadFileList] = useState<UploadFile[]>([]);

  const loadContracts = useCallback(async () => {
    setLoading(true);
    try {
      const params =
        statusFilter === 'all' ? undefined : { status: statusFilter };
      const res = await contractApi.list(params);
      setContracts(res.data);
    } catch {
      message.error('加载合同列表失败');
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  const loadTemplates = useCallback(async () => {
    setTemplatesLoading(true);
    try {
      const res = await contractTemplateApi.list();
      setTemplates(res.data);
    } catch {
      message.error('加载模板列表失败');
    } finally {
      setTemplatesLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadContracts();
  }, [loadContracts]);

  useEffect(() => {
    if (activeTab === 'templates') void loadTemplates();
  }, [activeTab, loadTemplates]);

  const openView = async (id: number) => {
    setSelectedId(id);
    setDrawerOpen(true);
    setDetailLoading(true);
    try {
      const res = await contractApi.get(id);
      const c = res.data;
      setEditTitle(c.title);
      setEditContent(c.content);
      setEditStatus(c.status.toLowerCase());
    } catch {
      message.error('加载合同详情失败');
      setDrawerOpen(false);
    } finally {
      setDetailLoading(false);
    }
  };

  const handleSave = async () => {
    if (selectedId == null) return;
    setSaving(true);
    try {
      await contractApi.update(selectedId, {
        title: editTitle,
        content: editContent,
        status: editStatus,
      });
      message.success('合同已保存');
      await loadContracts();
    } catch {
      message.error('保存合同失败');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await contractApi.delete(id);
      message.success('合同已删除');
      if (selectedId === id) {
        setDrawerOpen(false);
        setSelectedId(null);
      }
      await loadContracts();
    } catch {
      message.error('删除合同失败');
    }
  };

  const handlePrint = () => {
    window.print();
  };

  const handleCopy = async () => {
    const text = `${editTitle}\n\n${editContent}`;
    try {
      await navigator.clipboard.writeText(text);
      message.success('已复制到剪贴板');
    } catch {
      message.error('复制失败');
    }
  };

  const handleDownload = () => {
    const blob = new Blob([`${editTitle}\n\n${editContent}`], {
      type: 'text/plain;charset=utf-8',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${editTitle.replace(/[^\w\-]+/g, '_') || 'contract'}.txt`;
    a.click();
    URL.revokeObjectURL(url);
    message.success('下载已开始');
  };

  const handleDeleteTemplate = async (id: number) => {
    try {
      await contractTemplateApi.delete(id);
      message.success('模板已删除');
      await loadTemplates();
    } catch {
      message.error('删除模板失败');
    }
  };

  const handleDownloadTemplate = async (row: ContractTemplate) => {
    try {
      const res = await contractTemplateApi.downloadBlob(row.id);
      const blob = res.data;
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = row.original_name || `template-${row.id}.docx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      message.error('下载失败');
    }
  };

  const submitUpload = async () => {
    const vals = await uploadForm.validateFields();
    const file = uploadFileList[0]?.originFileObj as File | undefined;
    if (!file) {
      message.warning('请选择 .docx 文件');
      return;
    }
    if (!file.name.toLowerCase().endsWith('.docx')) {
      message.error('仅支持 .docx 格式');
      return;
    }
    setUploadSubmitting(true);
    try {
      await contractTemplateApi.upload(file, vals.name, vals.description || '');
      message.success('模板已上传');
      setUploadOpen(false);
      uploadForm.resetFields();
      setUploadFileList([]);
      await loadTemplates();
    } catch {
      message.error('上传失败');
    } finally {
      setUploadSubmitting(false);
    }
  };

  const columns: ColumnsType<Contract> = [
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
      render: (t: string) => <Text strong>{t}</Text>,
    },
    {
      title: '对话 ID',
      dataIndex: 'conversation_id',
      key: 'conversation_id',
      width: 140,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 130,
      render: (s: string) => (
        <Tag color={statusTagColor(s)}>{formatStatusLabel(s)}</Tag>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (d: string) => dayjs(d).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 160,
      render: (_, record) => (
        <Space>
          <Button
            type="link"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => void openView(record.id)}
          >
            查看
          </Button>
          <Popconfirm
            title="确认删除此合同？"
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

  const templateColumns: ColumnsType<ContractTemplate> = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      ellipsis: true,
      render: (t: string) => <Text strong>{t}</Text>,
    },
    {
      title: '文件名',
      dataIndex: 'original_name',
      key: 'original_name',
      ellipsis: true,
    },
    {
      title: '大小',
      dataIndex: 'file_size',
      key: 'file_size',
      width: 100,
      render: (n: number) => formatBytes(n),
    },
    {
      title: '上传时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (d: string) => dayjs(d).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 160,
      render: (_, record) => (
        <Space>
          <Button
            type="link"
            size="small"
            icon={<DownloadOutlined />}
            onClick={() => void handleDownloadTemplate(record)}
          >
            下载
          </Button>
          <Popconfirm
            title="确认删除此模板？"
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            onConfirm={() => void handleDeleteTemplate(record.id)}
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
        <Space align="center">
          <FileTextOutlined style={{ fontSize: 22, color: '#1677ff' }} />
          <Title level={4} style={{ margin: 0 }}>
            合同管理
          </Title>
        </Space>
      </Card>

      <Card bordered={false} style={{ borderRadius: 8 }}>
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            {
              key: 'contracts',
              label: '合同列表',
              children: (
                <Space direction="vertical" size="middle" style={{ width: '100%' }}>
                  <Space wrap align="center">
                    <Text type="secondary">状态</Text>
                    <Select
                      style={{ width: 180 }}
                      value={statusFilter}
                      onChange={setStatusFilter}
                      options={STATUS_OPTIONS.map((o) => ({
                        label: o.label,
                        value: o.value,
                      }))}
                    />
                  </Space>
                  <Table<Contract>
                    rowKey="id"
                    loading={loading}
                    columns={columns}
                    dataSource={contracts}
                    pagination={{ pageSize: 10, showSizeChanger: true }}
                  />
                </Space>
              ),
            },
            {
              key: 'templates',
              label: '合同模板',
              children: (
                <Space direction="vertical" size="middle" style={{ width: '100%' }}>
                  <Space>
                    <Button
                      type="primary"
                      icon={<PlusOutlined />}
                      onClick={() => {
                        setUploadOpen(true);
                        uploadForm.resetFields();
                        setUploadFileList([]);
                      }}
                    >
                      上传 Word 模板
                    </Button>
                    <Text type="secondary">仅支持 .docx，生成合同时可选择模板由 AI 填充修订。</Text>
                  </Space>
                  <Table<ContractTemplate>
                    rowKey="id"
                    loading={templatesLoading}
                    columns={templateColumns}
                    dataSource={templates}
                    pagination={{ pageSize: 10 }}
                  />
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        title="上传合同模板"
        open={uploadOpen}
        onCancel={() => setUploadOpen(false)}
        onOk={() => void submitUpload()}
        confirmLoading={uploadSubmitting}
        destroyOnClose
      >
        <Form form={uploadForm} layout="vertical" style={{ marginTop: 8 }}>
          <Form.Item
            name="name"
            label="模板名称"
            rules={[{ required: true, message: '请输入名称' }]}
          >
            <Input placeholder="例如：销售合同模板" />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input.TextArea rows={2} placeholder="可选" />
          </Form.Item>
          <Form.Item label="Word 文件 (.docx)" required>
            <Upload
              maxCount={1}
              fileList={uploadFileList}
              beforeUpload={() => false}
              onChange={({ fileList }) => setUploadFileList(fileList)}
              accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            >
              <Button>选择文件</Button>
            </Upload>
          </Form.Item>
        </Form>
      </Modal>

      <Drawer
        title={
          <Space>
            <EditOutlined />
            <span>合同详情</span>
          </Space>
        }
        width={720}
        open={drawerOpen}
        onClose={() => {
          setDrawerOpen(false);
          setSelectedId(null);
        }}
        destroyOnClose
        styles={{ body: { paddingBottom: 24 } }}
      >
        {detailLoading ? (
          <Text type="secondary">加载中…</Text>
        ) : (
          <Space direction="vertical" size="large" style={{ width: '100%' }}>
            <div>
              <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
                标题
              </Text>
              <Input
                value={editTitle}
                onChange={(e) => setEditTitle(e.target.value)}
                placeholder="合同标题"
                size="large"
              />
            </div>

            <div>
              <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
                内容
              </Text>
              <TextArea
                value={editContent}
                onChange={(e) => setEditContent(e.target.value)}
                rows={16}
                placeholder="合同正文"
                style={{
                  whiteSpace: 'pre-wrap',
                  fontFamily: 'inherit',
                  fontSize: 14,
                  lineHeight: 1.7,
                }}
                showCount
              />
            </div>

            <div>
              <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
                状态
              </Text>
              <Select
                style={{ width: '100%', maxWidth: 320 }}
                value={editStatus}
                onChange={setEditStatus}
                options={EDIT_STATUS_OPTIONS.map((o) => ({
                  label: o.label,
                  value: o.value,
                }))}
              />
            </div>

            <Space wrap>
              <Button
                type="primary"
                icon={<EditOutlined />}
                loading={saving}
                onClick={() => void handleSave()}
              >
                保存
              </Button>
              <Button icon={<PrinterOutlined />} onClick={handlePrint}>
                打印
              </Button>
              <Button icon={<CopyOutlined />} onClick={() => void handleCopy()}>
                复制
              </Button>
              <Button onClick={handleDownload}>下载 .txt</Button>
            </Space>
          </Space>
        )}
      </Drawer>
    </div>
  );
}
