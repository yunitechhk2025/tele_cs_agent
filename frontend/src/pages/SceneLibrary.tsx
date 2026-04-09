import { useCallback, useEffect, useState } from 'react';
import {
  Badge,
  Card,
  Col,
  Empty,
  Image,
  Modal,
  Row,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from 'antd';
import { LinkOutlined, PictureOutlined } from '@ant-design/icons';
import { sceneLibraryApi } from '../api';
import type { SceneLibraryItem, SceneLibraryFilters } from '../types';

const { Text, Title } = Typography;
const { Option } = Select;

function tagColor(label: string) {
  const map: Record<string, string> = {
    客厅: 'blue', 餐厅: 'green', 卧室: 'purple', 书房: 'cyan',
    儿童房: 'orange', 玄关: 'geekblue',
    现代: 'blue', 简约: 'cyan', 北欧: 'green', 新中式: 'gold',
    欧式: 'purple', 美式: 'orange', 轻奢: 'magenta',
  };
  return map[label] || 'default';
}

export default function SceneLibrary() {
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState<SceneLibraryItem[]>([]);
  const [filters, setFilters] = useState<SceneLibraryFilters>({ brands: [], spaces: [], styles: [], scene_names: [] });

  const [brandFilter, setBrandFilter] = useState<string | undefined>();
  const [spaceFilter, setSpaceFilter] = useState<string | undefined>();
  const [styleFilter, setStyleFilter] = useState<string | undefined>();
  const [sceneNameFilter, setSceneNameFilter] = useState<string | undefined>();

  const [selected, setSelected] = useState<SceneLibraryItem | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  useEffect(() => {
    sceneLibraryApi.filters().then((res) => setFilters(res.data)).catch(() => {});
  }, []);

  const fetchItems = useCallback(async () => {
    setLoading(true);
    try {
      const res = await sceneLibraryApi.list({
        brand: brandFilter,
        space: spaceFilter,
        style: styleFilter,
        scene_name: sceneNameFilter,
        limit: 100,
      });
      setItems(res.data);
    } catch {
      message.error('加载场景库失败');
    } finally {
      setLoading(false);
    }
  }, [brandFilter, spaceFilter, styleFilter, sceneNameFilter]);

  useEffect(() => {
    fetchItems();
  }, [fetchItems]);

  const openDetail = (item: SceneLibraryItem) => {
    setSelected(item);
    setModalOpen(true);
  };

  return (
    <div style={{ padding: 0 }}>
      {/* Header */}
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
          场景库
          <Badge
            count={items.length}
            overflowCount={9999}
            style={{ marginLeft: 10, backgroundColor: '#722ed1' }}
          />
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
        </Space>
      </div>

      {/* Grid */}
      <Spin spinning={loading}>
        {items.length === 0 && !loading ? (
          <Empty description="暂无场景图数据，请在产品库中生成场景图" />
        ) : (
          <Row gutter={[16, 16]}>
            {items.map((item) => (
              <Col key={item.id} xs={24} sm={12} md={8} lg={6} xl={6}>
                <Card
                  hoverable
                  style={{ borderRadius: 10, overflow: 'hidden' }}
                  cover={
                    item.cover_url ? (
                      <img
                        src={item.cover_url}
                        alt={item.primary_product_name}
                        style={{
                          width: '100%',
                          height: 200,
                          objectFit: 'cover',
                          display: 'block',
                        }}
                      />
                    ) : (
                      <div
                        style={{
                          height: 200,
                          background: '#f5f5f5',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          color: '#bbb',
                        }}
                      >
                        <PictureOutlined style={{ fontSize: 40 }} />
                      </div>
                    )
                  }
                  onClick={() => openDetail(item)}
                  bodyStyle={{ padding: '10px 14px' }}
                >
                  <Text
                    strong
                    ellipsis={{ tooltip: item.primary_product_name }}
                    style={{ fontSize: 14, display: 'block', marginBottom: 6 }}
                  >
                    {item.primary_product_name || '—'}
                  </Text>
                  <Space size={4} wrap>
                    {item.scene_name && <Tag color="purple">{item.scene_name}</Tag>}
                    {item.primary_product_brand && (
                      <Tag color="blue">{item.primary_product_brand}</Tag>
                    )}
                    {item.style_hint && <Tag color={tagColor(item.style_hint)}>{item.style_hint}</Tag>}
                  </Space>
                  {item.related_products.length > 0 && (
                    <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                      <Text type="secondary" style={{ fontSize: 11 }}>搭配：</Text>
                      {item.related_products.map((rp) => (
                        <div
                          key={rp.id}
                          title={`${rp.brand ? `[${rp.brand}] ` : ''}${rp.product_name}`}
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: 4,
                            padding: '2px 6px 2px 2px',
                            borderRadius: 4,
                            background: '#fafafa',
                            border: '1px solid #f0f0f0',
                          }}
                        >
                          <div style={{
                            width: 28, height: 28, borderRadius: 3,
                            overflow: 'hidden', flexShrink: 0,
                          }}>
                            <img
                              src={`/api/products/${rp.id}/images/0`}
                              alt={rp.product_name}
                              style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
                              onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                            />
                          </div>
                          <span style={{ fontSize: 10, color: '#666', maxWidth: 60, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {rp.brand || rp.product_name}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </Card>
              </Col>
            ))}
          </Row>
        )}
      </Spin>

      {/* Detail Modal */}
      <Modal
        title={selected ? `场景详情 — ${selected.primary_product_name}` : '场景详情'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        footer={null}
        width={800}
        destroyOnClose
      >
        {selected && (
          <div>
            {/* All scene images */}
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

            {/* Product combination */}
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
                {/* Primary product card */}
                <div style={{ textAlign: 'center', width: 110 }}>
                  <div style={{
                    width: 110, height: 80, borderRadius: 6, overflow: 'hidden',
                    border: '2px solid #597ef7', marginBottom: 6,
                  }}>
                    <img
                      src={`/api/products/${selected.primary_product_id}/images/0`}
                      alt={selected.primary_product_name}
                      style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
                      onError={(e) => { (e.target as HTMLImageElement).src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg"/>'; }}
                    />
                  </div>
                  <Tag color="geekblue" style={{ fontSize: 11 }}>主产品</Tag>
                  <div style={{ fontSize: 12, marginTop: 2, lineHeight: '16px', wordBreak: 'break-all' }}>
                    {selected.primary_product_name}
                  </div>
                  <div style={{ marginTop: 2 }}>
                    {selected.primary_product_brand && <Tag style={{ fontSize: 10 }}>{selected.primary_product_brand}</Tag>}
                  </div>
                </div>

                {/* Related product cards */}
                {selected.related_products.map((rp) => (
                  <div key={rp.id} style={{ textAlign: 'center', width: 130 }}>
                    <div style={{
                      width: 130, height: 90, borderRadius: 6, overflow: 'hidden',
                      border: '2px solid #ffa940', marginBottom: 6,
                    }}>
                      <img
                        src={`/api/products/${rp.id}/images/0`}
                        alt={rp.product_name}
                        style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
                        onError={(e) => { (e.target as HTMLImageElement).src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg"/>'; }}
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

            {/* Meta info */}
            <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>场景</Text>
                <div><Tag color="purple">{selected.scene_name || '—'}</Tag></div>
              </div>
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>风格</Text>
                <div><Tag>{selected.style_hint || '—'}</Tag></div>
              </div>
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>生成耗时</Text>
                <div><Text>{(selected.duration_ms / 1000).toFixed(1)} 秒</Text></div>
              </div>
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>生成时间</Text>
                <div><Text>{new Date(selected.created_at).toLocaleString()}</Text></div>
              </div>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
