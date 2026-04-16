import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  Checkbox,
  Col,
  Empty,
  Image,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Spin,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd';
import { CheckCircleOutlined, ClockCircleOutlined, DeleteOutlined, LinkOutlined, PictureOutlined, SyncOutlined } from '@ant-design/icons';
import { useSearchParams } from 'react-router-dom';
import { sceneGeneratorApi, sceneLibraryApi } from '../api';
import type { SceneLibraryFilters, SceneLibraryItem } from '../types';

const { Text, Title } = Typography;
const { Option } = Select;

type SceneTabKey = 'library' | 'review' | 'generating' | 'failed';

function tagColor(label: string) {
  const map: Record<string, string> = {
    客厅: 'blue', 餐厅: 'green', 卧室: 'purple', 书房: 'cyan',
    儿童房: 'orange', 玄关: 'geekblue',
    现代: 'blue', 简约: 'cyan', 北欧: 'green', 新中式: 'gold',
    欧式: 'purple', 美式: 'orange', 轻奢: 'magenta',
  };
  return map[label] || 'default';
}

function tabTitle(tab: SceneTabKey) {
  if (tab === 'review') return '待加入场景库';
  if (tab === 'generating') return '生成中';
  if (tab === 'failed') return '生成失败';
  return '当前场景库';
}

function statusTag(item: SceneLibraryItem) {
  if (item.status === 'completed' && item.in_library) return <Tag color="green">已入库</Tag>;
  if (item.status === 'completed') return <Tag color="gold">待审核</Tag>;
  if (item.status === 'failed') return <Tag color="red">生成失败</Tag>;
  return <Tag color="processing">生成中</Tag>;
}

export default function SceneLibrary() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get('tab');
  const tab: SceneTabKey = tabParam === 'review' || tabParam === 'generating' || tabParam === 'failed' ? tabParam : 'library';
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState<SceneLibraryItem[]>([]);
  const [filters, setFilters] = useState<SceneLibraryFilters>({ brands: [], spaces: [], styles: [], scene_names: [] });

  const [brandFilter, setBrandFilter] = useState<string | undefined>();
  const [spaceFilter, setSpaceFilter] = useState<string | undefined>();
  const [styleFilter, setStyleFilter] = useState<string | undefined>();
  const [sceneNameFilter, setSceneNameFilter] = useState<string | undefined>();

  const [selected, setSelected] = useState<SceneLibraryItem | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [togglingId, setTogglingId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [retryingId, setRetryingId] = useState<number | null>(null);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [batchLoading, setBatchLoading] = useState(false);

  const fetchFilters = useCallback(async () => {
    try {
      const res = await sceneLibraryApi.filters({ view: tab });
      setFilters(res.data);
    } catch {
      setFilters({ brands: [], spaces: [], styles: [], scene_names: [] });
    }
  }, [tab]);

  const fetchItems = useCallback(async () => {
    setLoading(true);
    try {
      const res = await sceneLibraryApi.list({
        view: tab,
        brand: brandFilter,
        space: spaceFilter,
        style: styleFilter,
        scene_name: sceneNameFilter,
        limit: 100,
      });
      setItems(res.data);
      setSelected((prev) => {
        if (!prev) return prev;
        return res.data.find((item) => item.id === prev.id) || prev;
      });
      setSelectedIds((prev) => prev.filter((id) => res.data.some((item) => item.id === id)));
    } catch {
      message.error('加载场景图列表失败');
    } finally {
      setLoading(false);
    }
  }, [tab, brandFilter, spaceFilter, styleFilter, sceneNameFilter]);

  useEffect(() => {
    fetchFilters();
    fetchItems();
  }, [fetchFilters, fetchItems]);

  useEffect(() => {
    if (tab !== 'generating') return undefined;
    const timer = window.setInterval(() => {
      fetchItems();
    }, 10000);
    return () => window.clearInterval(timer);
  }, [tab, fetchItems]);

  const resetFilters = () => {
    setBrandFilter(undefined);
    setSpaceFilter(undefined);
    setStyleFilter(undefined);
    setSceneNameFilter(undefined);
    setSelectedIds([]);
  };

  const handleTabChange = (key: string) => {
    resetFilters();
    setSelected(null);
    setModalOpen(false);
    const next = new URLSearchParams(searchParams);
    next.set('tab', key);
    setSearchParams(next, { replace: true });
  };

  const openDetail = (item: SceneLibraryItem) => {
    setSelected(item);
    setModalOpen(true);
  };

  const handleToggleLibrary = async (item: SceneLibraryItem) => {
    setTogglingId(item.id);
    try {
      const res = await sceneGeneratorApi.toggleLibrary(item.id);
      message.success(res.data.in_library ? '已加入场景库' : '已从场景库移除');
      await fetchItems();
      if (selected?.id === item.id) {
        setSelected({ ...item, in_library: res.data.in_library });
      }
    } catch {
      message.error('操作失败');
    } finally {
      setTogglingId(null);
    }
  };

  const handleDelete = async (item: SceneLibraryItem) => {
    setDeletingId(item.id);
    try {
      await sceneGeneratorApi.delete(item.id);
      message.success('场景图已删除');
      if (selected?.id === item.id) {
        setModalOpen(false);
        setSelected(null);
      }
      await fetchItems();
    } catch {
      message.error('删除失败');
    } finally {
      setDeletingId(null);
    }
  };

  const handleRetry = async (item: SceneLibraryItem) => {
    setRetryingId(item.id);
    try {
      await sceneGeneratorApi.retry(item.id);
      message.success('已重新提交生成任务，可前往“生成中”查看');
      if (selected?.id === item.id) {
        setModalOpen(false);
        setSelected(null);
      }
      setSelectedIds((prev) => prev.filter((id) => id !== item.id));
      if (tab === 'failed') {
        const next = new URLSearchParams(searchParams);
        next.set('tab', 'generating');
        setSearchParams(next, { replace: true });
      } else {
        await fetchItems();
      }
    } catch {
      message.error('重试失败');
    } finally {
      setRetryingId(null);
    }
  };

  const performBatchAction = async (action: 'delete' | 'add_to_library' | 'remove_from_library' | 'retry') => {
    if (selectedIds.length === 0) {
      message.warning('请先选择任务');
      return;
    }
    setBatchLoading(true);
    try {
      const res = await sceneGeneratorApi.batchAction({ record_ids: selectedIds, action });
      const { success_count, failed_count } = res.data;
      if (success_count > 0) {
        if (action === 'retry') {
          message.success(`已重新提交 ${success_count} 个任务`);
        } else if (action === 'add_to_library') {
          message.success(`已加入场景库 ${success_count} 项`);
        } else if (action === 'remove_from_library') {
          message.success(`已移出场景库 ${success_count} 项`);
        } else {
          message.success(`已处理 ${success_count} 项`);
        }
      }
      if (failed_count > 0) {
        message.warning(`${failed_count} 项操作失败`);
      }
      setSelectedIds([]);
      if (action === 'retry' && tab === 'failed') {
        const next = new URLSearchParams(searchParams);
        next.set('tab', 'generating');
        setSearchParams(next, { replace: true });
      } else {
        await fetchItems();
      }
    } catch {
      message.error('批量操作失败');
    } finally {
      setBatchLoading(false);
    }
  };

  const allCurrentIds = useMemo(() => items.map((item) => item.id), [items]);
  const allSelected = allCurrentIds.length > 0 && allCurrentIds.every((id) => selectedIds.includes(id));

  return (
    <div style={{ padding: 0 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 16,
          flexWrap: 'wrap',
          gap: 12,
        }}
      >
        <Title level={4} style={{ margin: 0 }}>
          <PictureOutlined style={{ marginRight: 8 }} />
          场景图管理
          <Badge count={items.length} overflowCount={9999} style={{ marginLeft: 10, backgroundColor: '#1677ff' }} />
        </Title>
        <Space wrap>
          <Select
            placeholder="品牌"
            allowClear
            style={{ width: 130 }}
            value={brandFilter}
            onChange={setBrandFilter}
            showSearch
            optionFilterProp="children"
          >
            {filters.brands.map((b) => (
              <Option key={b} value={b}>{b}</Option>
            ))}
          </Select>
          <Select
            placeholder="空间"
            allowClear
            style={{ width: 120 }}
            value={spaceFilter}
            onChange={setSpaceFilter}
            showSearch
            optionFilterProp="children"
          >
            {filters.spaces.map((s) => (
              <Option key={s} value={s}>{s}</Option>
            ))}
          </Select>
          <Select
            placeholder="风格"
            allowClear
            style={{ width: 120 }}
            value={styleFilter}
            onChange={setStyleFilter}
            showSearch
            optionFilterProp="children"
          >
            {filters.styles.map((s) => (
              <Option key={s} value={s}>{s}</Option>
            ))}
          </Select>
          <Select
            placeholder="场景名"
            allowClear
            style={{ width: 140 }}
            value={sceneNameFilter}
            onChange={setSceneNameFilter}
            showSearch
            optionFilterProp="children"
          >
            {filters.scene_names.map((s) => (
              <Option key={s} value={s}>{s}</Option>
            ))}
          </Select>
          <Button icon={<SyncOutlined />} onClick={fetchItems}>刷新</Button>
        </Space>
      </div>

      <Tabs
        activeKey={tab}
        onChange={handleTabChange}
        items={[
          { key: 'library', label: '当前场景库' },
          { key: 'review', label: '待加入场景库' },
          { key: 'generating', label: '生成中' },
          { key: 'failed', label: '生成失败' },
        ]}
      />

      <div style={{ marginBottom: 14, color: '#666', fontSize: 13 }}>
        {tab === 'library' && '这里展示已经入库、可复用的正式场景图。'}
        {tab === 'review' && '这里展示已生成完成但尚未入库的场景图，包括 agent 在客户对话中生成的结果。'}
        {tab === 'generating' && '这里展示仍在生成中的任务。新建场景图后可来这里查看最新状态。'}
        {tab === 'failed' && '这里展示生成失败的任务。可重试，或直接丢弃。'}
      </div>

      <div
        style={{
          marginBottom: 16,
          padding: '10px 12px',
          border: '1px solid #f0f0f0',
          borderRadius: 10,
          background: '#fafafa',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 12,
          flexWrap: 'wrap',
        }}
      >
        <Space wrap>
          <Checkbox
            checked={allSelected}
            indeterminate={selectedIds.length > 0 && !allSelected}
            onChange={(e) => setSelectedIds(e.target.checked ? allCurrentIds : [])}
            disabled={allCurrentIds.length === 0}
          >
            全选当前页
          </Checkbox>
          <Text type="secondary">
            已选择 {selectedIds.length} 项
          </Text>
          {selectedIds.length > 0 && (
            <Button size="small" onClick={() => setSelectedIds([])}>
              清空选择
            </Button>
          )}
        </Space>
        <Space wrap>
          {tab === 'review' && (
            <Button
              type="primary"
              icon={<CheckCircleOutlined />}
              loading={batchLoading}
              disabled={selectedIds.length === 0}
              onClick={() => performBatchAction('add_to_library')}
            >
              批量加入场景库
            </Button>
          )}
          {tab === 'library' && (
            <Button
              loading={batchLoading}
              disabled={selectedIds.length === 0}
              onClick={() => performBatchAction('remove_from_library')}
            >
              批量移出场景库
            </Button>
          )}
          {tab === 'failed' && (
            <Button
              type="primary"
              icon={<SyncOutlined />}
              loading={batchLoading}
              disabled={selectedIds.length === 0}
              onClick={() => performBatchAction('retry')}
            >
              批量重试
            </Button>
          )}
          <Popconfirm
            title={tab === 'library' ? '确认批量删除已入库场景图？' : '确认批量丢弃选中任务？'}
            description="删除后将同时移除图片文件和数据库记录。"
            okText={tab === 'library' ? '删除' : '丢弃'}
            cancelText="取消"
            okButtonProps={{ danger: true, loading: batchLoading }}
            onConfirm={() => performBatchAction('delete')}
            disabled={selectedIds.length === 0}
          >
            <Button
              danger
              icon={<DeleteOutlined />}
              loading={batchLoading}
              disabled={selectedIds.length === 0}
            >
              {tab === 'library' ? '批量删除' : '批量丢弃'}
            </Button>
          </Popconfirm>
        </Space>
      </div>

      <Spin spinning={loading}>
        {items.length === 0 && !loading ? (
          <Empty description={`${tabTitle(tab)}暂无数据`} />
        ) : (
          <Row gutter={[16, 16]}>
            {items.map((item) => (
              <Col key={item.id} xs={24} sm={12} md={8} lg={6} xl={6}>
                <Card
                  hoverable
                  style={{ borderRadius: 10, overflow: 'hidden' }}
                  cover={
                    <div style={{ position: 'relative' }}>
                      <div
                        style={{
                          position: 'absolute',
                          top: 10,
                          left: 10,
                          zIndex: 2,
                          background: 'rgba(255,255,255,0.92)',
                          borderRadius: 8,
                          padding: '4px 8px',
                        }}
                        onClick={(e) => e.stopPropagation()}
                      >
                        <Checkbox
                          checked={selectedIds.includes(item.id)}
                          onChange={(e) => {
                            const checked = e.target.checked;
                            setSelectedIds((prev) =>
                              checked ? Array.from(new Set([...prev, item.id])) : prev.filter((id) => id !== item.id)
                            );
                          }}
                        />
                      </div>
                      {item.cover_url ? (
                        <img
                          src={item.cover_url}
                          alt={item.primary_product_name}
                          style={{ width: '100%', height: 200, objectFit: 'cover', display: 'block' }}
                        />
                      ) : (
                        <div
                          style={{
                            height: 200,
                            background: '#f5f5f5',
                            display: 'flex',
                            flexDirection: 'column',
                            alignItems: 'center',
                            justifyContent: 'center',
                            color: '#999',
                            gap: 8,
                          }}
                        >
                          {item.status === 'failed' ? <Text type="danger">生成失败</Text> : <ClockCircleOutlined style={{ fontSize: 28 }} />}
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            {item.status === 'failed' ? '请查看详情中的错误信息' : '图片生成完成后会自动显示在这里'}
                          </Text>
                        </div>
                      )}
                    </div>
                  }
                  onClick={() => openDetail(item)}
                  bodyStyle={{ padding: '10px 14px' }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6, gap: 6 }}>
                    <Text strong ellipsis={{ tooltip: item.primary_product_name }} style={{ fontSize: 14, flex: 1 }}>
                      {item.primary_product_name || '—'}
                    </Text>
                    {statusTag(item)}
                  </div>
                  <Space size={4} wrap>
                    {item.scene_name && <Tag color="purple">{item.scene_name}</Tag>}
                    {item.primary_product_brand && <Tag color="blue">{item.primary_product_brand}</Tag>}
                    {item.style_hint && <Tag color={tagColor(item.style_hint)}>{item.style_hint}</Tag>}
                  </Space>
                  {item.request_text && (
                    <div style={{ marginTop: 8, minHeight: 34 }}>
                      <Text type="secondary" ellipsis={{ tooltip: item.request_text }} style={{ fontSize: 12 }}>
                        {item.request_text}
                      </Text>
                    </div>
                  )}
                  <div style={{ marginTop: 8, fontSize: 12, color: '#888' }}>
                    {item.duration_ms > 0 ? `耗时 ${(item.duration_ms / 1000).toFixed(1)} 秒` : `创建于 ${new Date(item.created_at).toLocaleString()}`}
                  </div>
                  <div style={{ marginTop: 10 }}>
                    {tab === 'review' && (
                      <Space size={8}>
                        <Button
                          type="primary"
                          size="small"
                          icon={<CheckCircleOutlined />}
                          loading={togglingId === item.id}
                          onClick={(e) => {
                            e.stopPropagation();
                            handleToggleLibrary(item);
                          }}
                        >
                          加入场景库
                        </Button>
                        <Popconfirm
                          title="确认丢弃这组场景图？"
                          description="删除后将同时移除图片文件和数据库记录。"
                          okText="丢弃"
                          cancelText="取消"
                          okButtonProps={{ danger: true, loading: deletingId === item.id }}
                          onConfirm={(e) => {
                            e?.stopPropagation();
                            return handleDelete(item);
                          }}
                        >
                          <Button
                            size="small"
                            danger
                            icon={<DeleteOutlined />}
                            loading={deletingId === item.id}
                            onClick={(e) => e.stopPropagation()}
                          >
                            丢弃
                          </Button>
                        </Popconfirm>
                      </Space>
                    )}
                    {tab === 'library' && (
                      <Space size={8}>
                        <Button
                          size="small"
                          loading={togglingId === item.id}
                          onClick={(e) => {
                            e.stopPropagation();
                            handleToggleLibrary(item);
                          }}
                        >
                          移出场景库
                        </Button>
                        <Popconfirm
                          title="确认删除这组场景图？"
                          description="删除后将同时移除图片文件和数据库记录。"
                          okText="删除"
                          cancelText="取消"
                          okButtonProps={{ danger: true, loading: deletingId === item.id }}
                          onConfirm={(e) => {
                            e?.stopPropagation();
                            return handleDelete(item);
                          }}
                        >
                          <Button
                            size="small"
                            danger
                            icon={<DeleteOutlined />}
                            loading={deletingId === item.id}
                            onClick={(e) => e.stopPropagation()}
                          >
                            删除
                          </Button>
                        </Popconfirm>
                      </Space>
                    )}
                    {tab === 'failed' && (
                      <Space size={8}>
                        <Button
                          type="primary"
                          size="small"
                          icon={<SyncOutlined />}
                          loading={retryingId === item.id}
                          onClick={(e) => {
                            e.stopPropagation();
                            handleRetry(item);
                          }}
                        >
                          重试
                        </Button>
                        <Popconfirm
                          title="确认丢弃这条失败任务？"
                          description="删除后将同时移除图片文件和数据库记录。"
                          okText="丢弃"
                          cancelText="取消"
                          okButtonProps={{ danger: true, loading: deletingId === item.id }}
                          onConfirm={(e) => {
                            e?.stopPropagation();
                            return handleDelete(item);
                          }}
                        >
                          <Button
                            size="small"
                            danger
                            icon={<DeleteOutlined />}
                            loading={deletingId === item.id}
                            onClick={(e) => e.stopPropagation()}
                          >
                            丢弃
                          </Button>
                        </Popconfirm>
                      </Space>
                    )}
                    {tab === 'generating' && (
                      <Space size={8}>
                        <Popconfirm
                          title="确认丢弃这条生成任务？"
                          description="删除后将同时移除图片文件和数据库记录。"
                          okText="丢弃"
                          cancelText="取消"
                          okButtonProps={{ danger: true, loading: deletingId === item.id }}
                          onConfirm={(e) => {
                            e?.stopPropagation();
                            return handleDelete(item);
                          }}
                        >
                          <Button
                            size="small"
                            danger
                            icon={<DeleteOutlined />}
                            loading={deletingId === item.id}
                            onClick={(e) => e.stopPropagation()}
                          >
                            丢弃
                          </Button>
                        </Popconfirm>
                      </Space>
                    )}
                  </div>
                </Card>
              </Col>
            ))}
          </Row>
        )}
      </Spin>

      <Modal
        title={selected ? `场景详情 — ${selected.primary_product_name}` : '场景详情'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        footer={null}
        width={860}
        destroyOnClose
      >
        {selected && (
          <div>
            <div style={{ marginBottom: 16 }}>
              <Space wrap style={{ marginBottom: 8 }}>
                {statusTag(selected)}
                {selected.scene_name && <Tag color="purple">{selected.scene_name}</Tag>}
                {selected.style_hint && <Tag>{selected.style_hint}</Tag>}
                {selected.primary_product_brand && <Tag color="blue">{selected.primary_product_brand}</Tag>}
              </Space>
              {selected.request_text && (
                <div style={{ padding: '10px 12px', background: '#fafafa', borderRadius: 8, border: '1px solid #f0f0f0' }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>原始请求</Text>
                  <div style={{ marginTop: 4 }}>{selected.request_text}</div>
                </div>
              )}
              {selected.error_message && (
                <div style={{ marginTop: 10, padding: '10px 12px', background: '#fff2f0', borderRadius: 8, border: '1px solid #ffccc7', color: '#cf1322' }}>
                  {selected.error_message}
                </div>
              )}
            </div>

            {selected.image_urls.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <Text strong style={{ marginBottom: 8, display: 'block' }}>场景图</Text>
                <Image.PreviewGroup>
                  <Space wrap>
                    {selected.image_urls.map((url, idx) => (
                      <Image
                        key={idx}
                        src={url}
                        width={220}
                        height={160}
                        style={{ objectFit: 'cover', borderRadius: 8 }}
                      />
                    ))}
                  </Space>
                </Image.PreviewGroup>
              </div>
            )}

            <div style={{ marginBottom: 16 }}>
              <Text strong style={{ marginBottom: 8, display: 'block' }}>产品组合</Text>
              <div
                style={{
                  padding: '16px',
                  background: '#fafafa',
                  borderRadius: 8,
                  border: '1px solid #f0f0f0',
                  display: 'flex',
                  gap: 12,
                  flexWrap: 'wrap',
                }}
              >
                <div style={{ textAlign: 'center', width: 110 }}>
                  <div style={{ width: 110, height: 80, borderRadius: 6, overflow: 'hidden', border: '2px solid #597ef7', marginBottom: 6 }}>
                    <img
                      src={`/api/products/${selected.primary_product_id}/images/0`}
                      alt={selected.primary_product_name}
                      style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
                      onError={(e) => { (e.target as HTMLImageElement).src = 'data:image/svg+xml,<svg xmlns=\"http://www.w3.org/2000/svg\"/>'; }}
                    />
                  </div>
                  <Tag color="geekblue" style={{ fontSize: 11 }}>主产品</Tag>
                  <div style={{ fontSize: 12, marginTop: 2, lineHeight: '16px', wordBreak: 'break-all' }}>
                    {selected.primary_product_name}
                  </div>
                </div>

                {selected.related_products.map((rp) => (
                  <div key={rp.id} style={{ textAlign: 'center', width: 130 }}>
                    <div style={{ width: 130, height: 90, borderRadius: 6, overflow: 'hidden', border: '2px solid #ffa940', marginBottom: 6 }}>
                      <img
                        src={`/api/products/${rp.id}/images/0`}
                        alt={rp.product_name}
                        style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
                        onError={(e) => { (e.target as HTMLImageElement).src = 'data:image/svg+xml,<svg xmlns=\"http://www.w3.org/2000/svg\"/>'; }}
                      />
                    </div>
                    <div style={{ marginBottom: 2 }}>
                      <Tag color="orange" style={{ fontSize: 11 }}>搭配</Tag>
                      {rp.brand && <Tag style={{ fontSize: 10 }}>{rp.brand}</Tag>}
                    </div>
                    <div style={{ fontSize: 12, lineHeight: '16px', wordBreak: 'break-all', marginBottom: 4 }}>
                      {rp.product_name}
                    </div>
                    {(rp.buy_url || rp.detail_url) && (
                      <a
                        href={rp.buy_url || rp.detail_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{ fontSize: 11 }}
                        onClick={(e) => e.stopPropagation()}
                      >
                        <LinkOutlined /> 查看详情
                      </a>
                    )}
                  </div>
                ))}
              </div>
            </div>

            <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', marginBottom: 14 }}>
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>生成耗时</Text>
                <div><Text>{selected.duration_ms > 0 ? `${(selected.duration_ms / 1000).toFixed(1)} 秒` : '进行中'}</Text></div>
              </div>
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>创建时间</Text>
                <div><Text>{new Date(selected.created_at).toLocaleString()}</Text></div>
              </div>
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>更新时间</Text>
                <div><Text>{new Date(selected.updated_at).toLocaleString()}</Text></div>
              </div>
              {selected.conversation_id && (
                <div>
                  <Text type="secondary" style={{ fontSize: 12 }}>来源</Text>
                  <div><Tag color="geekblue">来自对话 #{selected.conversation_id}</Tag></div>
                </div>
              )}
            </div>

            <Space>
              {selected.status === 'completed' && (
                <Button
                  type={selected.in_library ? 'default' : 'primary'}
                  loading={togglingId === selected.id}
                  onClick={() => handleToggleLibrary(selected)}
                >
                  {selected.in_library ? '移出场景库' : '加入场景库'}
                </Button>
              )}
              {(selected.status === 'completed' || selected.status === 'failed' || selected.status === 'pending') && (
                <Popconfirm
                  title={selected.in_library ? '确认删除这组场景图？' : '确认丢弃这组场景图？'}
                  description="删除后将同时移除图片文件和数据库记录。"
                  okText={selected.in_library ? '删除' : '丢弃'}
                  cancelText="取消"
                  okButtonProps={{ danger: true, loading: deletingId === selected.id }}
                  onConfirm={() => handleDelete(selected)}
                >
                  <Button danger icon={<DeleteOutlined />} loading={deletingId === selected.id}>
                    {selected.in_library ? '删除' : '丢弃'}
                  </Button>
                </Popconfirm>
              )}
              {selected.status === 'failed' && (
                <Button
                  type="primary"
                  icon={<SyncOutlined />}
                  loading={retryingId === selected.id}
                  onClick={() => handleRetry(selected)}
                >
                  重试
                </Button>
              )}
              {tab === 'generating' && <Button onClick={fetchItems}>刷新状态</Button>}
            </Space>
          </div>
        )}
      </Modal>
    </div>
  );
}
