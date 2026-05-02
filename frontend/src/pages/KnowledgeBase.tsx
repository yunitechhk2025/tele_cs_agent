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
  Alert,
  Select,
  Tree,
  Empty,
  AutoComplete,
  Badge,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { UploadFile } from 'antd/es/upload/interface';
import type { DataNode } from 'antd/es/tree';
import {
  UploadOutlined,
  DeleteOutlined,
  SearchOutlined,
  BookOutlined,
  InboxOutlined,
  LoadingOutlined,
  EyeOutlined,
  FolderOutlined,
  AppstoreOutlined,
  QuestionCircleOutlined,
  SafetyCertificateOutlined,
  ApartmentOutlined,
  TagsOutlined,
  ReadOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { knowledgeApi } from '../api';
import type { KnowledgeEntry } from '../types';

const { Title, Text } = Typography;

const ROOT_KEY = '__all__';
const UNCATEGORIZED_KEY = '__uncategorized__';

type CategoryDef = {
  name: string;
  children: string[];
  icon: ReactNode;
  color: string;
};

const CATEGORY_TREE: CategoryDef[] = [
  {
    name: '常见问题',
    children: ['订单', '退货', '产品'],
    icon: <QuestionCircleOutlined style={{ color: '#1677ff' }} />,
    color: '#1677ff',
  },
  {
    name: '政策文档',
    children: ['退货政策', '保修条款', '隐私政策'],
    icon: <SafetyCertificateOutlined style={{ color: '#52c41a' }} />,
    color: '#52c41a',
  },
  {
    name: '操作流程',
    children: [],
    icon: <ApartmentOutlined style={{ color: '#fa8c16' }} />,
    color: '#fa8c16',
  },
  {
    name: '案例库',
    children: ['退款纠纷', '物流问题', '产品质量', '大客户', '跨境关税'],
    icon: <TagsOutlined style={{ color: '#722ed1' }} />,
    color: '#722ed1',
  },
];

const TOP_CATEGORIES = CATEGORY_TREE.map((c) => c.name);
const SUB_OPTIONS: Record<string, string[]> = Object.fromEntries(
  CATEGORY_TREE.map((c) => [c.name, c.children]),
);

function joinCategory(top?: string | null, sub?: string | null) {
  const t = (top || '').trim();
  const s = (sub || '').trim();
  if (!t) return '';
  return s ? `${t}/${s}` : t;
}

function splitCategory(category?: string | null): { top: string; sub: string } {
  const raw = (category || '').trim();
  if (!raw) return { top: '', sub: '' };
  const idx = raw.indexOf('/');
  if (idx < 0) return { top: raw, sub: '' };
  return { top: raw.slice(0, idx).trim(), sub: raw.slice(idx + 1).trim() };
}

export default function KnowledgeBase() {
  const [entries, setEntries] = useState<KnowledgeEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [treeSearch, setTreeSearch] = useState('');
  const [selectedKey, setSelectedKey] = useState<string>(ROOT_KEY);

  const [uploadSubmitting, setUploadSubmitting] = useState(false);
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [uploadFileList, setUploadFileList] = useState<UploadFile[]>([]);
  const [uploadProgress, setUploadProgress] = useState<{ done: number; total: number } | null>(null);
  const [uploadForm] = Form.useForm();
  const [viewOpen, setViewOpen] = useState(false);
  const [viewingEntry, setViewingEntry] = useState<KnowledgeEntry | null>(null);

  const uploadTopCategory = Form.useWatch('top_category', uploadForm) as string | undefined;

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

  const counts = useMemo(() => {
    const c: Record<string, number> = { [ROOT_KEY]: entries.length, [UNCATEGORIZED_KEY]: 0 };
    for (const e of entries) {
      const { top, sub } = splitCategory(e.category);
      if (!top) {
        c[UNCATEGORIZED_KEY] = (c[UNCATEGORIZED_KEY] || 0) + 1;
        continue;
      }
      const topKey = `top:${top}`;
      c[topKey] = (c[topKey] || 0) + 1;
      if (sub) {
        const subKey = `sub:${top}/${sub}`;
        c[subKey] = (c[subKey] || 0) + 1;
      }
    }
    return c;
  }, [entries]);

  const renderTreeTitle = (
    label: string,
    count: number,
    options?: { strong?: boolean; accent?: string },
  ) => (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 8,
        paddingRight: 4,
        width: '100%',
      }}
    >
      <span
        style={{
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          fontWeight: options?.strong ? 600 : 500,
          color: options?.accent ?? 'inherit',
          fontSize: 13,
        }}
      >
        {label}
      </span>
      <Badge
        count={count}
        showZero
        overflowCount={9999}
        style={{
          backgroundColor: count > 0 ? '#f0f5ff' : '#f5f5f5',
          color: count > 0 ? '#1677ff' : '#bfbfbf',
          boxShadow: 'none',
          fontWeight: 500,
          fontSize: 11,
          minWidth: 22,
          height: 18,
          lineHeight: '18px',
          padding: '0 6px',
          borderRadius: 9,
        }}
      />
    </div>
  );

  const treeData: DataNode[] = useMemo(() => {
    const q = treeSearch.trim().toLowerCase();
    const matches = (label: string) => !q || label.toLowerCase().includes(q);

    const knownTops = new Set(TOP_CATEGORIES);
    const dynamicTopMap = new Map<string, Set<string>>();
    for (const e of entries) {
      const { top, sub } = splitCategory(e.category);
      if (!top || knownTops.has(top)) continue;
      const set = dynamicTopMap.get(top) ?? new Set<string>();
      if (sub) set.add(sub);
      dynamicTopMap.set(top, set);
    }

    const buildSubChildren = (topName: string, predefined: string[]) => {
      const seen = new Set<string>();
      const subs: string[] = [];
      for (const s of predefined) {
        if (!seen.has(s)) {
          seen.add(s);
          subs.push(s);
        }
      }
      for (const e of entries) {
        const { top, sub } = splitCategory(e.category);
        if (top === topName && sub && !seen.has(sub)) {
          seen.add(sub);
          subs.push(sub);
        }
      }
      return subs
        .filter((s) => matches(s))
        .map<DataNode>((s) => {
          const key = `sub:${topName}/${s}`;
          return {
            key,
            title: renderTreeTitle(s, counts[key] || 0),
            icon: <TagsOutlined style={{ color: '#8c8c8c' }} />,
            isLeaf: true,
          };
        });
    };

    const fixedNodes: DataNode[] = CATEGORY_TREE.map((cat) => {
      const topKey = `top:${cat.name}`;
      const children = buildSubChildren(cat.name, cat.children);
      const showSelf = matches(cat.name) || children.length > 0;
      if (!showSelf) return null;
      return {
        key: topKey,
        title: renderTreeTitle(cat.name, counts[topKey] || 0, { strong: true }),
        icon: cat.icon,
        children,
      } as DataNode;
    }).filter(Boolean) as DataNode[];

    const dynamicNodes: DataNode[] = Array.from(dynamicTopMap.keys())
      .sort()
      .map((name) => {
        const topKey = `top:${name}`;
        const children = buildSubChildren(name, []);
        const showSelf = matches(name) || children.length > 0;
        if (!showSelf) return null;
        return {
          key: topKey,
          title: renderTreeTitle(name, counts[topKey] || 0, { strong: true }),
          icon: <FolderOutlined style={{ color: '#8c8c8c' }} />,
          children,
        } as DataNode;
      })
      .filter(Boolean) as DataNode[];

    const uncategorizedCount = counts[UNCATEGORIZED_KEY] || 0;
    const uncategorizedNode: DataNode | null =
      matches('未分类') && (uncategorizedCount > 0 || !q)
        ? {
            key: UNCATEGORIZED_KEY,
            title: renderTreeTitle('未分类', uncategorizedCount, { accent: '#bfbfbf' }),
            icon: <FolderOutlined style={{ color: '#bfbfbf' }} />,
            isLeaf: true,
          }
        : null;

    const rootChildren = [
      ...fixedNodes,
      ...dynamicNodes,
      ...(uncategorizedNode ? [uncategorizedNode] : []),
    ];

    return [
      {
        key: ROOT_KEY,
        title: renderTreeTitle('全部知识库', counts[ROOT_KEY] || 0, {
          strong: true,
          accent: '#262626',
        }),
        icon: <AppstoreOutlined style={{ color: '#1677ff' }} />,
        children: rootChildren,
      },
    ];
  }, [entries, counts, treeSearch]);

  const filteredByCategory = useMemo(() => {
    if (selectedKey === ROOT_KEY) return entries;
    if (selectedKey === UNCATEGORIZED_KEY) {
      return entries.filter((e) => {
        const { top } = splitCategory(e.category);
        return !top;
      });
    }
    if (selectedKey.startsWith('top:')) {
      const top = selectedKey.slice(4);
      return entries.filter((e) => splitCategory(e.category).top === top);
    }
    if (selectedKey.startsWith('sub:')) {
      const path = selectedKey.slice(4);
      const slash = path.indexOf('/');
      if (slash < 0) return entries;
      const top = path.slice(0, slash);
      const sub = path.slice(slash + 1);
      return entries.filter((e) => {
        const sp = splitCategory(e.category);
        return sp.top === top && sp.sub === sub;
      });
    }
    return entries;
  }, [entries, selectedKey]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return filteredByCategory;
    return filteredByCategory.filter(
      (e) =>
        e.title.toLowerCase().includes(q) ||
        e.content.toLowerCase().includes(q),
    );
  }, [filteredByCategory, search]);

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
    const top = uploadForm.getFieldValue('top_category') as string | undefined;
    const sub = uploadForm.getFieldValue('sub_category') as string | undefined;
    const category = joinCategory(top, sub) || undefined;
    if (uploadFiles.length === 0) {
      message.warning('请选择至少一个文件');
      return;
    }
    setUploadSubmitting(true);
    setUploadProgress({ done: 0, total: uploadFiles.length });
    let totalChunks = 0;
    let okCount = 0;
    const failures: { name: string; reason: string }[] = [];
    for (let i = 0; i < uploadFiles.length; i++) {
      const file = uploadFiles[i];
      try {
        const res = await knowledgeApi.upload(file, category);
        const body = res.data as { status?: string; chunks_created?: number };
        totalChunks += body.chunks_created ?? 0;
        okCount += 1;
      } catch (e: unknown) {
        const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
        failures.push({ name: file.name, reason: typeof detail === 'string' ? detail : '上传失败' });
      } finally {
        setUploadProgress({ done: i + 1, total: uploadFiles.length });
      }
    }
    setUploadSubmitting(false);
    setUploadProgress(null);
    if (failures.length === 0) {
      message.success(`批量上传完成：${okCount} 个文件，共生成 ${totalChunks} 个向量分块`);
      uploadForm.resetFields();
      setUploadFiles([]);
      setUploadFileList([]);
    } else {
      Modal.warning({
        title: `上传完成：${okCount} 成功 / ${failures.length} 失败`,
        content: (
          <div>
            <div style={{ marginBottom: 8 }}>共生成 {totalChunks} 个向量分块。</div>
            <div style={{ maxHeight: 200, overflow: 'auto' }}>
              {failures.map((f) => (
                <div key={f.name} style={{ fontSize: 12 }}>
                  <Text type="danger">{f.name}</Text>: {f.reason}
                </div>
              ))}
            </div>
          </div>
        ),
      });
    }
    await loadEntries();
  };

  const renderCategoryTags = (category?: string | null) => {
    const { top, sub } = splitCategory(category);
    if (!top) return <Text type="secondary">—</Text>;
    return (
      <Space size={4} wrap>
        <Tag color="geekblue">{top}</Tag>
        {sub ? <Tag color="blue">{sub}</Tag> : null}
      </Space>
    );
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
      width: 200,
      render: (c: string | null) => renderCategoryTags(c),
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

  const currentLabel = useMemo(() => {
    if (selectedKey === ROOT_KEY) return '全部知识库';
    if (selectedKey === UNCATEGORIZED_KEY) return '未分类';
    if (selectedKey.startsWith('top:')) return selectedKey.slice(4);
    if (selectedKey.startsWith('sub:')) {
      const path = selectedKey.slice(4);
      return path.replace('/', ' / ');
    }
    return '';
  }, [selectedKey]);

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
          align="center"
          style={{ width: '100%', justifyContent: 'space-between', flexWrap: 'wrap', gap: 16 }}
        >
          <Space align="center">
            <BookOutlined style={{ fontSize: 22, color: '#1677ff' }} />
            <Title level={4} style={{ margin: 0 }}>
              知识库
            </Title>
            <Text type="secondary">{currentLabel}</Text>
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
          </Space>
        </Space>
      </Card>

      <Card
        bordered={false}
        style={{
          marginBottom: 16,
          borderRadius: 10,
          boxShadow: '0 1px 2px rgba(0,0,0,0.03)',
        }}
        styles={{ body: { padding: 16 } }}
      >
        <Space align="center" style={{ marginBottom: 14 }}>
          <UploadOutlined style={{ color: '#1677ff', fontSize: 18 }} />
          <Text strong style={{ fontSize: 16 }}>批量上传文档</Text>
          <Text type="secondary" style={{ fontSize: 13 }}>
            拖入或选择多个文件，将自动解析切块并生成向量索引
          </Text>
        </Space>
        {uploadSubmitting ? (
          <Alert
            type="info"
            showIcon
            icon={<LoadingOutlined spin />}
            message={
              uploadProgress
                ? `正在嵌入知识库（${uploadProgress.done}/${uploadProgress.total}）`
                : '正在嵌入知识库'
            }
            description="逐个上传、解析、切块并写入向量索引；大文件可能需要数分钟。"
            style={{ marginBottom: 12 }}
          />
        ) : null}
        <div style={{ display: 'flex', gap: 16, alignItems: 'stretch' }}>
          <div
            style={{
              width: 320,
              flexShrink: 0,
              padding: '14px 18px',
              borderRadius: 10,
              background:
                'linear-gradient(135deg, rgba(22,119,255,0.05) 0%, rgba(82,196,26,0.04) 100%)',
              border: '1px solid #f0f0f0',
            }}
          >
            <Space size={8} align="center" style={{ marginBottom: 4 }}>
              <FolderOutlined style={{ color: '#1677ff', fontSize: 16 }} />
              <Text strong style={{ fontSize: 15 }}>归类到</Text>
            </Space>
            <div style={{ marginBottom: 14 }}>
              <Text type="secondary" style={{ fontSize: 13 }}>
                本批所有文件将归入同一分类
              </Text>
            </div>
            <Form form={uploadForm} layout="vertical">
              <Form.Item name="top_category" label="一级分类" style={{ marginBottom: 12 }}>
                <Select
                  allowClear
                  placeholder="选择一级分类"
                  options={TOP_CATEGORIES.map((c) => ({ value: c, label: c }))}
                  onChange={() => uploadForm.setFieldsValue({ sub_category: undefined })}
                />
              </Form.Item>
              <Form.Item name="sub_category" label="二级分类" style={{ marginBottom: 0 }}>
                <AutoComplete
                  allowClear
                  placeholder={uploadTopCategory ? '选择或输入二级分类' : '先选择一级分类'}
                  disabled={!uploadTopCategory}
                  options={(SUB_OPTIONS[uploadTopCategory || ''] || []).map((s) => ({
                    value: s,
                    label: s,
                  }))}
                />
              </Form.Item>
            </Form>
            <div style={{ marginTop: 12 }}>
              <Button
                type="primary"
                block
                icon={<UploadOutlined />}
                disabled={uploadFiles.length === 0}
                loading={uploadSubmitting}
                onClick={() => void handleUploadOk()}
              >
                {uploadFiles.length > 1
                  ? `上传 ${uploadFiles.length} 个文件并嵌入`
                  : '上传并嵌入'}
              </Button>
              {uploadFiles.length > 0 && !uploadSubmitting ? (
                <Button
                  block
                  size="small"
                  type="text"
                  style={{ marginTop: 4 }}
                  onClick={() => {
                    setUploadFiles([]);
                    setUploadFileList([]);
                  }}
                >
                  清空待上传列表
                </Button>
              ) : null}
            </div>
          </div>

          <div style={{ flex: 1, minWidth: 0 }}>
            <Upload.Dragger
              accept=".txt,.md,.csv,.docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
              multiple
              disabled={uploadSubmitting}
              fileList={uploadFileList}
              style={{ padding: '6px 4px' }}
              beforeUpload={(_file, fileList) => {
                setUploadFiles((prev) => {
                  const next = [...prev];
                  for (const f of fileList) {
                    if (!next.some((x) => x.name === f.name && x.size === f.size)) {
                      next.push(f);
                    }
                  }
                  return next;
                });
                setUploadFileList((prev) => {
                  const next = [...prev];
                  for (const f of fileList) {
                    if (!next.some((x) => x.uid === f.uid)) {
                      next.push({
                        uid: f.uid,
                        name: f.name,
                        status: 'done',
                        originFileObj: f,
                      });
                    }
                  }
                  return next;
                });
                return false;
              }}
              onRemove={(file) => {
                setUploadFiles((prev) =>
                  prev.filter((f) => !(f.name === file.name && f.size === (file.size || 0))),
                );
                setUploadFileList((prev) => prev.filter((f) => f.uid !== file.uid));
              }}
            >
              <p className="ant-upload-drag-icon" style={{ marginBottom: 6 }}>
                <InboxOutlined style={{ fontSize: 52, color: '#1677ff' }} />
              </p>
              <p className="ant-upload-text" style={{ fontSize: 17, fontWeight: 500 }}>
                把文件拖到这里，或点击选择
              </p>
              <p className="ant-upload-hint" style={{ fontSize: 13 }}>
                支持批量拖入多个文件 · .txt / .md / .csv / .docx
              </p>
            </Upload.Dragger>
          </div>
        </div>
      </Card>

      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
        <Card
          bordered={false}
          style={{
            width: 360,
            flexShrink: 0,
            borderRadius: 12,
            overflow: 'hidden',
            position: 'sticky',
            top: 16,
            boxShadow: '0 4px 16px rgba(0,0,0,0.04)',
          }}
          styles={{ body: { padding: 0 } }}
        >
          <div
            style={{
              padding: '16px 18px 14px',
              background:
                'linear-gradient(135deg, rgba(22,119,255,0.08) 0%, rgba(82,196,26,0.06) 100%)',
              borderBottom: '1px solid #f0f0f0',
            }}
          >
            <Space size={10} align="center" style={{ marginBottom: 2 }}>
              <ReadOutlined style={{ fontSize: 20, color: '#1677ff' }} />
              <Text strong style={{ fontSize: 16 }}>
                知识目录
              </Text>
            </Space>
            <div style={{ marginTop: 4 }}>
              <Text type="secondary" style={{ fontSize: 13 }}>
                共 {counts[ROOT_KEY] || 0} 条 · 结构清晰 = 检索更准
              </Text>
            </div>
          </div>
          <div style={{ padding: '12px 14px 4px' }}>
            <Input
              allowClear
              placeholder="搜索分类…"
              prefix={<SearchOutlined style={{ color: '#bfbfbf' }} />}
              value={treeSearch}
              onChange={(e) => setTreeSearch(e.target.value)}
            />
          </div>
          <div
            className="kb-tree-wrapper"
            style={{
              padding: '6px 8px 14px',
              maxHeight: 'calc(100vh - 260px)',
              overflowY: 'auto',
            }}
          >
            <Tree
              showIcon
              blockNode
              defaultExpandAll
              selectedKeys={[selectedKey]}
              onSelect={(keys) => {
                const k = keys[0];
                if (typeof k === 'string') setSelectedKey(k);
              }}
              treeData={treeData}
              style={{ background: 'transparent', fontSize: 14 }}
            />
          </div>
        </Card>

        <Card bordered={false} style={{ borderRadius: 8, flex: 1, minWidth: 0 }}>
          {filtered.length === 0 && !loading ? (
            <Empty description="该分类下暂无条目" />
          ) : (
            <Table<KnowledgeEntry>
              rowKey="id"
              loading={loading}
              columns={columns}
              dataSource={filtered}
              pagination={{ pageSize: 10, showSizeChanger: true }}
            />
          )}
        </Card>
      </div>

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
                <div>{renderCategoryTags(viewingEntry.category)}</div>
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

    </div>
  );
}
