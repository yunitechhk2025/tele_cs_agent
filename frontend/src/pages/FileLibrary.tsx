import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
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
  Tooltip,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { UploadFile } from 'antd/es/upload/interface';
import {
  FolderOutlined,
  PlusOutlined,
  DeleteOutlined,
  EditOutlined,
  DownloadOutlined,
  SearchOutlined,
  InboxOutlined,
  FileOutlined,
  FileImageOutlined,
  FilePdfOutlined,
  FileWordOutlined,
  EyeOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { fileApi } from '../api';
import type { FileEntry } from '../types';

const { Title, Text } = Typography;
const { TextArea } = Input;

function formatFileSize(bytes: number): string {
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function fileTypeIcon(mime: string | null): ReactNode {
  if (!mime) {
    return <FileOutlined style={{ color: '#8c8c8c' }} />;
  }
  const m = mime.toLowerCase();
  if (m.startsWith('image/')) {
    return <FileImageOutlined style={{ color: '#52c41a' }} />;
  }
  if (m === 'application/pdf' || m.includes('pdf')) {
    return <FilePdfOutlined style={{ color: '#ff4d4f' }} />;
  }
  if (
    m.includes('word') ||
    m.includes('msword') ||
    m.includes('wordprocessingml')
  ) {
    return <FileWordOutlined style={{ color: '#1677ff' }} />;
  }
  return <FileOutlined style={{ color: '#8c8c8c' }} />;
}

function parseTags(tags: string): string[] {
  return tags
    .split(',')
    .map((t) => t.trim())
    .filter(Boolean);
}

export default function FileLibrary() {
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');

  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadFileList, setUploadFileList] = useState<UploadFile[]>([]);
  const [uploadForm] = Form.useForm<{
    description: string;
    tags: string;
    category?: string;
  }>();

  const [editOpen, setEditOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editingRecord, setEditingRecord] = useState<FileEntry | null>(null);
  const [editForm] = Form.useForm<{
    description: string;
    tags: string;
    category?: string;
  }>();

  const [viewOpen, setViewOpen] = useState(false);
  const [viewingFile, setViewingFile] = useState<FileEntry | null>(null);

  const loadFiles = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fileApi.list();
      setFiles(res.data);
    } catch {
      message.error('加载文件列表失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadFiles();
  }, [loadFiles]);

  const filteredFiles = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return files;
    return files.filter((f) => {
      const inName = f.original_name.toLowerCase().includes(q);
      const inDesc = f.description.toLowerCase().includes(q);
      const inTags = f.tags.toLowerCase().includes(q);
      return inName || inDesc || inTags;
    });
  }, [files, search]);

  const openUpload = () => {
    uploadForm.resetFields();
    setUploadFileList([]);
    setUploadOpen(true);
  };

  const submitUpload = async () => {
    const values = await uploadForm.validateFields();
    const file = uploadFileList[0]?.originFileObj as File | undefined;
    if (!file) {
      message.error('请选择要上传的文件');
      return;
    }
    setUploading(true);
    try {
      await fileApi.upload(
        file,
        values.description,
        values.tags ?? '',
        values.category?.trim() || undefined,
      );
      message.success('文件上传成功');
      setUploadOpen(false);
      uploadForm.resetFields();
      setUploadFileList([]);
      await loadFiles();
    } catch {
      message.error('上传失败');
    } finally {
      setUploading(false);
    }
  };

  const openEdit = (record: FileEntry) => {
    setEditingRecord(record);
    editForm.setFieldsValue({
      description: record.description,
      tags: record.tags,
      category: record.category ?? undefined,
    });
    setEditOpen(true);
  };

  const submitEdit = async () => {
    if (!editingRecord) return;
    const values = await editForm.validateFields();
    setEditing(true);
    try {
      await fileApi.update(editingRecord.id, {
        description: values.description,
        tags: values.tags ?? '',
        category: values.category?.trim() || undefined,
      });
      message.success('文件信息已更新');
      setEditOpen(false);
      setEditingRecord(null);
      await loadFiles();
    } catch {
      message.error('更新失败');
    } finally {
      setEditing(false);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await fileApi.delete(id);
      message.success('文件已删除');
      await loadFiles();
    } catch {
      message.error('删除失败');
    }
  };

  const columns: ColumnsType<FileEntry> = [
    {
      title: '文件名',
      dataIndex: 'original_name',
      key: 'original_name',
      ellipsis: { showTitle: false },
      render: (_, record) => (
        <Tooltip title={record.original_name}>
          <Space>
            {fileTypeIcon(record.mime_type)}
            <Text>{record.original_name}</Text>
          </Space>
        </Tooltip>
      ),
    },
    {
      title: '大小',
      dataIndex: 'file_size',
      key: 'file_size',
      width: 110,
      render: (n: number) => formatFileSize(n),
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
      render: (text: string) => (
        <Tooltip title={text}>
          <Text ellipsis style={{ maxWidth: 280, display: 'inline-block' }}>
            {text || '—'}
          </Text>
        </Tooltip>
      ),
    },
    {
      title: '标签',
      dataIndex: 'tags',
      key: 'tags',
      width: 220,
      render: (tags: string) => {
        const parts = parseTags(tags);
        if (parts.length === 0) {
          return <Text type="secondary">—</Text>;
        }
        return (
          <Space size={[4, 4]} wrap>
            {parts.map((t) => (
              <Tag key={t}>{t}</Tag>
            ))}
          </Space>
        );
      },
    },
    {
      title: '分类',
      dataIndex: 'category',
      key: 'category',
      width: 130,
      render: (c: string | null) =>
        c ? <Tag color="blue">{c}</Tag> : <Text type="secondary">—</Text>,
    },
    {
      title: '上传时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      render: (d: string) => dayjs(d).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 260,
      fixed: 'right',
      render: (_, record) => (
        <Space size="small" wrap>
          <Button
            type="link"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => {
              setViewingFile(record);
              setViewOpen(true);
            }}
          >
            查看
          </Button>
          <Button
            type="link"
            size="small"
            icon={<DownloadOutlined />}
            href={fileApi.downloadUrl(record.id)}
            target="_blank"
            rel="noopener noreferrer"
          >
            下载
          </Button>
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => openEdit(record)}
          >
            编辑
          </Button>
          <Popconfirm
            title="确认删除此文件？"
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
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Space align="start" style={{ width: '100%', justifyContent: 'space-between', flexWrap: 'wrap', gap: 16 }}>
            <Space align="start">
              <FolderOutlined style={{ fontSize: 26, color: '#1677ff', marginTop: 4 }} />
              <div>
                <Title level={4} style={{ margin: 0 }}>
                  文件库
                </Title>
                <Text type="secondary">
                  上传文件供 AI 根据客户需求自动发送
                </Text>
              </div>
            </Space>
            <Space wrap align="center">
              <Input
                allowClear
                placeholder="按名称、描述或标签搜索"
                prefix={<SearchOutlined style={{ color: '#bfbfbf' }} />}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                style={{ width: 280 }}
              />
              <Button type="primary" icon={<PlusOutlined />} onClick={openUpload}>
                上传文件
              </Button>
            </Space>
          </Space>
        </Space>
      </Card>

      <Card bordered={false} style={{ borderRadius: 8 }}>
        <Table<FileEntry>
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={filteredFiles}
          pagination={{ pageSize: 10, showSizeChanger: true }}
          scroll={{ x: 960 }}
        />
      </Card>

      <Modal
        title="查看文件"
        open={viewOpen}
        onCancel={() => {
          setViewOpen(false);
          setViewingFile(null);
        }}
        footer={null}
        width={640}
        destroyOnClose
      >
        {viewingFile ? (
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <Space align="start">
              {fileTypeIcon(viewingFile.mime_type)}
              <div>
                <Text strong style={{ fontSize: 15 }}>
                  {viewingFile.original_name}
                </Text>
                <div style={{ marginTop: 4 }}>
                  <Text type="secondary">
                    {formatFileSize(viewingFile.file_size)}
                    {viewingFile.mime_type ? ` · ${viewingFile.mime_type}` : ''}
                  </Text>
                </div>
              </div>
            </Space>
            <div>
              <Text type="secondary">描述</Text>
              <div style={{ marginTop: 4 }}>{viewingFile.description || '—'}</div>
            </div>
            <div>
              <Text type="secondary">标签</Text>
              <div style={{ marginTop: 8 }}>
                {parseTags(viewingFile.tags).length ? (
                  <Space size={[4, 4]} wrap>
                    {parseTags(viewingFile.tags).map((t) => (
                      <Tag key={t}>{t}</Tag>
                    ))}
                  </Space>
                ) : (
                  <Text type="secondary">—</Text>
                )}
              </div>
            </div>
            <div>
              <Text type="secondary">分类</Text>
              <div style={{ marginTop: 4 }}>
                {viewingFile.category ? (
                  <Tag color="blue">{viewingFile.category}</Tag>
                ) : (
                  <Text type="secondary">—</Text>
                )}
              </div>
            </div>
            <div>
              <Text type="secondary">上传时间</Text>
              <div>{dayjs(viewingFile.created_at).format('YYYY-MM-DD HH:mm')}</div>
            </div>
            {viewingFile.mime_type?.toLowerCase().startsWith('image/') ? (
              <div>
                <Text type="secondary">预览</Text>
                <div style={{ marginTop: 8, textAlign: 'center' }}>
                  <img
                    src={fileApi.downloadUrl(viewingFile.id)}
                    alt={viewingFile.original_name}
                    style={{ maxWidth: '100%', maxHeight: 360, objectFit: 'contain' }}
                  />
                </div>
              </div>
            ) : (
              <div>
                <Text type="secondary">预览</Text>
                <div style={{ marginTop: 8 }}>
                  <Text type="secondary">
                    当前类型无法在页面内直接预览，请使用「下载」在本地打开。
                  </Text>
                </div>
              </div>
            )}
            <Button
              type="primary"
              icon={<DownloadOutlined />}
              href={fileApi.downloadUrl(viewingFile.id)}
              target="_blank"
              rel="noopener noreferrer"
            >
              下载文件
            </Button>
          </Space>
        ) : null}
      </Modal>

      <Modal
        title="上传文件"
        open={uploadOpen}
        onCancel={() => {
          setUploadOpen(false);
          uploadForm.resetFields();
          setUploadFileList([]);
        }}
        okText="上传"
        cancelText="取消"
        confirmLoading={uploading}
        onOk={() => void submitUpload()}
        destroyOnClose
        width={560}
      >
        <Form form={uploadForm} layout="vertical" style={{ marginTop: 8 }}>
          <Form.Item label="文件" required>
            <Upload.Dragger
              maxCount={1}
              fileList={uploadFileList}
              beforeUpload={() => false}
              onChange={({ fileList }) => setUploadFileList(fileList)}
            >
              <p className="ant-upload-drag-icon">
                <InboxOutlined />
              </p>
              <p className="ant-upload-text">点击或拖拽文件到此区域</p>
              <p className="ant-upload-hint">支持任意格式，每次上传一个文件。</p>
            </Upload.Dragger>
          </Form.Item>
          <Form.Item
            name="description"
            label="描述"
            rules={[{ required: true, message: '请描述文件内容' }]}
            extra="描述文件内容，以便 AI 能根据客户需求匹配发送"
          >
            <TextArea rows={4} placeholder="这个文件是关于什么的？" />
          </Form.Item>
          <Form.Item
            name="tags"
            label="标签"
            extra="用逗号分隔的标签，例如：产品目录、宣传册、手册"
          >
            <Input placeholder="例如：目录、报价、宣传册" />
          </Form.Item>
          <Form.Item name="category" label="分类" extra="可选的分组类别">
            <Input placeholder="可选分类" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="编辑文件信息"
        open={editOpen}
        onCancel={() => {
          setEditOpen(false);
          setEditingRecord(null);
        }}
        okText="保存"
        cancelText="取消"
        confirmLoading={editing}
        onOk={() => void submitEdit()}
        destroyOnClose
        width={520}
      >
        {editingRecord && (
          <Form form={editForm} layout="vertical" style={{ marginTop: 8 }}>
            <Form.Item label="文件名">
              <Text>{editingRecord.original_name}</Text>
            </Form.Item>
            <Form.Item
              name="description"
              label="描述"
              rules={[{ required: true, message: '请输入描述' }]}
            >
              <TextArea rows={4} />
            </Form.Item>
            <Form.Item name="tags" label="标签">
              <Input />
            </Form.Item>
            <Form.Item name="category" label="分类">
              <Input placeholder="可选" />
            </Form.Item>
          </Form>
        )}
      </Modal>
    </div>
  );
}
