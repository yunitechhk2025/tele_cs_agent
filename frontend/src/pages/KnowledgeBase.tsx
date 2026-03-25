import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Table,
  Button,
  Modal,
  Form,
  Input,
  Upload,
  Tag,
  Popconfirm,
  message,
  Space,
  Typography,
  Card,
  Alert,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { UploadFile } from 'antd/es/upload/interface';
import {
  PlusOutlined,
  UploadOutlined,
  DeleteOutlined,
  SearchOutlined,
  BookOutlined,
  InboxOutlined,
  LoadingOutlined,
  EyeOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { knowledgeApi } from '../api';
import type { KnowledgeEntry } from '../types';

const { Title, Text } = Typography;
const { TextArea } = Input;

export default function KnowledgeBase() {
  const [entries, setEntries] = useState<KnowledgeEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [addOpen, setAddOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [addSubmitting, setAddSubmitting] = useState(false);
  const [uploadSubmitting, setUploadSubmitting] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadFileList, setUploadFileList] = useState<UploadFile[]>([]);
  const [addForm] = Form.useForm();
  const [uploadForm] = Form.useForm();
  const [viewOpen, setViewOpen] = useState(false);
  const [viewingEntry, setViewingEntry] = useState<KnowledgeEntry | null>(null);

  const loadEntries = useCallback(async () => {
    setLoading(true);
    try {
      const res = await knowledgeApi.list();
      setEntries(res.data);
    } catch {
      message.error('加载知识条目失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadEntries();
  }, [loadEntries]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return entries;
    return entries.filter(
      (e) =>
        e.title.toLowerCase().includes(q) ||
        e.content.toLowerCase().includes(q),
    );
  }, [entries, search]);

  const handleAddOk = async () => {
    try {
      const values = await addForm.validateFields();
      setAddSubmitting(true);
      await knowledgeApi.create({
        title: values.title,
        content: values.content,
        source: values.source || undefined,
        category: values.category || undefined,
      });
      message.success('嵌入完成：知识条目已写入并已生成向量索引');
      setAddOpen(false);
      addForm.resetFields();
      await loadEntries();
    } catch (e) {
      if (e && typeof e === 'object' && 'errorFields' in e) return;
      message.error('创建条目失败');
    } finally {
      setAddSubmitting(false);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await knowledgeApi.delete(id);
      message.success('条目已删除');
      await loadEntries();
    } catch {
      message.error('删除条目失败');
    }
  };

  const handleUploadOk = async () => {
    const category = uploadForm.getFieldValue('category') as string | undefined;
    if (!uploadFile) {
      message.warning('请选择一个文件');
      return;
    }
    setUploadSubmitting(true);
    try {
      const res = await knowledgeApi.upload(uploadFile, category);
      const body = res.data as { status?: string; chunks_created?: number };
      const chunks = body.chunks_created ?? 0;
      message.success(`嵌入完成：已生成 ${chunks} 个向量分块并写入知识库`);
      setUploadOpen(false);
      uploadForm.resetFields();
      setUploadFile(null);
      setUploadFileList([]);
      await loadEntries();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(typeof detail === 'string' ? detail : '上传失败');
    } finally {
      setUploadSubmitting(false);
    }
  };

  const columns: ColumnsType<KnowledgeEntry> = [
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
      render: (t: string) => <Text strong>{t}</Text>,
    },
    {
      title: '分类',
      dataIndex: 'category',
      key: 'category',
      width: 140,
      render: (c: string | null) =>
        c ? <Tag color="geekblue">{c}</Tag> : <Text type="secondary">—</Text>,
    },
    {
      title: '来源',
      dataIndex: 'source',
      key: 'source',
      ellipsis: true,
      render: (s: string | null) => s || <Text type="secondary">—</Text>,
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
      align: 'center',
      render: (_, record) => (
        <Space size="small" wrap>
          <Button
            type="link"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => {
              setViewingEntry(record);
              setViewOpen(true);
            }}
          >
            查看
          </Button>
          <Popconfirm
            title="确认删除此条目？"
            description="删除后不可恢复。"
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
        <Space
          direction="vertical"
          size="middle"
          style={{ width: '100%' }}
        >
          <Space
            align="center"
            style={{ width: '100%', justifyContent: 'space-between', flexWrap: 'wrap', gap: 16 }}
          >
            <Space align="center">
              <BookOutlined style={{ fontSize: 22, color: '#1677ff' }} />
              <Title level={4} style={{ margin: 0 }}>
                知识库
              </Title>
            </Space>
            <Space wrap>
              <Input
                allowClear
                prefix={<SearchOutlined style={{ color: '#bfbfbf' }} />}
                placeholder="搜索标题或内容…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                style={{ width: 280 }}
              />
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => setAddOpen(true)}
              >
                添加条目
              </Button>
              <Button icon={<UploadOutlined />} onClick={() => setUploadOpen(true)}>
                上传文件
              </Button>
            </Space>
          </Space>
        </Space>
      </Card>

      <Card bordered={false} style={{ borderRadius: 8 }}>
        <Table<KnowledgeEntry>
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={filtered}
          pagination={{ pageSize: 10, showSizeChanger: true }}
        />
      </Card>

      <Modal
        title="添加知识条目"
        open={addOpen}
        onOk={() => void handleAddOk()}
        onCancel={() => {
          setAddOpen(false);
          addForm.resetFields();
        }}
        okText="保存并嵌入"
        cancelText="取消"
        confirmLoading={addSubmitting}
        maskClosable={!addSubmitting}
        closable={!addSubmitting}
        cancelButtonProps={{ disabled: addSubmitting }}
        destroyOnClose
        width={560}
      >
        {addSubmitting ? (
          <Alert
            type="info"
            showIcon
            icon={<LoadingOutlined spin />}
            message="正在嵌入知识库"
            description="正在保存条目并调用向量模型写入索引，请稍候，勿关闭窗口。"
            style={{ marginBottom: 16 }}
          />
        ) : null}
        <Form form={addForm} layout="vertical" style={{ marginTop: 8 }}>
          <Form.Item
            name="title"
            label="标题"
            rules={[{ required: true, message: '请输入标题' }]}
          >
            <Input placeholder="条目标题" />
          </Form.Item>
          <Form.Item
            name="content"
            label="内容"
            rules={[{ required: true, message: '请输入内容' }]}
          >
            <TextArea rows={8} placeholder="完整文本内容" showCount />
          </Form.Item>
          <Form.Item name="category" label="分类">
            <Input placeholder="可选分类" />
          </Form.Item>
          <Form.Item name="source" label="来源">
            <Input placeholder="可选来源引用" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="查看知识条目"
        open={viewOpen}
        onCancel={() => {
          setViewOpen(false);
          setViewingEntry(null);
        }}
        footer={null}
        width={720}
        destroyOnClose
      >
        {viewingEntry ? (
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <div>
              <Text type="secondary">标题</Text>
              <div>
                <Text strong>{viewingEntry.title}</Text>
              </div>
            </div>
            <Space size="large" wrap>
              <div>
                <Text type="secondary">分类</Text>
                <div>
                  {viewingEntry.category ? (
                    <Tag color="geekblue">{viewingEntry.category}</Tag>
                  ) : (
                    <Text type="secondary">—</Text>
                  )}
                </div>
              </div>
              <div>
                <Text type="secondary">来源</Text>
                <div>{viewingEntry.source || '—'}</div>
              </div>
              <div>
                <Text type="secondary">更新时间</Text>
                <div>{dayjs(viewingEntry.updated_at).format('YYYY-MM-DD HH:mm')}</div>
              </div>
            </Space>
            <div>
              <Text type="secondary">正文内容</Text>
              <pre
                style={{
                  marginTop: 8,
                  marginBottom: 0,
                  padding: 12,
                  background: 'var(--ant-color-fill-quaternary, #fafafa)',
                  borderRadius: 8,
                  maxHeight: 420,
                  overflow: 'auto',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                  fontSize: 13,
                  lineHeight: 1.6,
                }}
              >
                {viewingEntry.content}
              </pre>
            </div>
          </Space>
        ) : null}
      </Modal>

      <Modal
        title="上传文档"
        open={uploadOpen}
        onOk={() => void handleUploadOk()}
        onCancel={() => {
          setUploadOpen(false);
          uploadForm.resetFields();
          setUploadFile(null);
          setUploadFileList([]);
        }}
        okText="上传并嵌入"
        cancelText="取消"
        confirmLoading={uploadSubmitting}
        maskClosable={!uploadSubmitting}
        closable={!uploadSubmitting}
        cancelButtonProps={{ disabled: uploadSubmitting }}
        destroyOnClose
        width={520}
      >
        <Form form={uploadForm} layout="vertical" style={{ marginTop: 8 }}>
          <Form.Item name="category" label="分类（可选）">
            <Input placeholder="为上传的分块添加分类标签" />
          </Form.Item>
        </Form>
        {uploadSubmitting ? (
          <Alert
            type="info"
            showIcon
            icon={<LoadingOutlined spin />}
            message="正在嵌入知识库"
            description={
              <>
                <div>正在上传、解析文档、切块并写入向量索引；完成后将弹出「嵌入完成」提示。</div>
                <div style={{ marginTop: 8 }}>
                  <Text type="secondary">大文件可能需数十秒，请勿关闭窗口。</Text>
                </div>
              </>
            }
            style={{ marginBottom: 16 }}
          />
        ) : null}
        <Upload.Dragger
          accept=".txt,.md,.csv,.docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          maxCount={1}
          disabled={uploadSubmitting}
          fileList={uploadFileList}
          beforeUpload={(file) => {
            setUploadFile(file);
            setUploadFileList([
              {
                uid: file.uid,
                name: file.name,
                status: 'done',
                originFileObj: file,
              },
            ]);
            return false;
          }}
          onRemove={() => {
            setUploadFile(null);
            setUploadFileList([]);
          }}
        >
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p className="ant-upload-text">点击或拖拽文件到此区域上传</p>
          <p className="ant-upload-hint">
            支持：.txt、.md、.csv、Word 2007+（.docx）。旧版 .doc 请先在 Word 中另存为 .docx。
          </p>
        </Upload.Dragger>
      </Modal>
    </div>
  );
}
