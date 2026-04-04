import { useCallback, useEffect, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  Col,
  Descriptions,
  Divider,
  Drawer,
  Empty,
  Image,
  Input,
  Row,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  ReloadOutlined,
  SearchOutlined,
  ShoppingCartOutlined,
  PictureOutlined,
} from '@ant-design/icons';
import { productApi } from '../api';
import type { ProductEntry, SceneGenerationRecord } from '../types';

const { Text, Title, Link } = Typography;
const { Option } = Select;
const { TextArea } = Input;

function tagColor(label: string) {
  const map: Record<string, string> = {
    客厅: 'blue', 餐厅: 'green', 卧室: 'purple', 书房: 'cyan',
    儿童房: 'orange', 玄关: 'geekblue', 其他: 'default',
    现代: 'blue', 简约: 'cyan', 北欧: 'green', 新中式: 'gold',
    欧式: 'purple', 美式: 'orange', 轻奢: 'magenta',
  };
  return map[label] || 'default';
}

export default function Products() {
  const [loading, setLoading] = useState(false);
  const [products, setProducts] = useState<ProductEntry[]>([]);
  const [keyword, setKeyword] = useState('');
  const [brandFilter, setBrandFilter] = useState<string | undefined>();
  const [spaceFilter, setSpaceFilter] = useState<string | undefined>();
  const [styleFilter, setStyleFilter] = useState<string | undefined>();
  const [seriesFilter, setSeriesFilter] = useState<string | undefined>();
  const [metaBrands, setMetaBrands] = useState<string[]>([]);
  const [metaSpaces, setMetaSpaces] = useState<string[]>([]);
  const [metaStyles, setMetaStyles] = useState<string[]>([]);
  const [metaSeries, setMetaSeries] = useState<string[]>([]);
  const [selected, setSelected] = useState<ProductEntry | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerLoading, setDrawerLoading] = useState(false);
  const [importing, setImporting] = useState(false);
  const [imgErrors, setImgErrors] = useState<Record<string, boolean>>({});
  const [sceneName, setSceneName] = useState('');
  const [sceneStyleHint, setSceneStyleHint] = useState('');
  const [sceneRequest, setSceneRequest] = useState('');
  const [sceneGenerating, setSceneGenerating] = useState(false);
  const [sceneRecords, setSceneRecords] = useState<SceneGenerationRecord[]>([]);

  // Load filter options once on mount
  useEffect(() => {
    productApi.meta().then((res) => {
      setMetaBrands(res.data.brands ?? []);
      setMetaSpaces(res.data.spaces);
      setMetaStyles(res.data.styles);
      setMetaSeries(res.data.series);
    }).catch(() => {});
  }, []);

  const fetchProducts = useCallback(async () => {
    setLoading(true);
    try {
      const res = await productApi.list({
        keyword: keyword || undefined,
        brand: brandFilter,
        space: spaceFilter,
        style: styleFilter,
        series: seriesFilter,
        limit: 200,
      });
      setProducts(res.data);
    } catch {
      message.error('加载产品列表失败');
    } finally {
      setLoading(false);
    }
  }, [keyword, brandFilter, spaceFilter, styleFilter, seriesFilter]);

  useEffect(() => {
    const t = setTimeout(fetchProducts, 300);
    return () => clearTimeout(t);
  }, [fetchProducts]);

  const handleImport = async () => {
    setImporting(true);
    try {
      await productApi.triggerImport();
      message.success('导入成功');
      fetchProducts();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail ? `导入失败: ${detail.slice(0, 200)}` : '导入失败');
    } finally {
      setImporting(false);
    }
  };

  const openDetail = async (p: ProductEntry) => {
    setDrawerOpen(true);
    setSelected(p);
    setSceneName(p.space || '客厅');
    setSceneStyleHint(p.style || '');
    setSceneRequest('');
    setDrawerLoading(true);
    try {
      const [detailRes, sceneRes] = await Promise.all([
        productApi.get(p.id),
        productApi.listSceneImages(p.id),
      ]);
      setSelected(detailRes.data);
      setSceneRecords(sceneRes.data);
    } catch {
      message.error('加载产品详情失败');
    } finally {
      setDrawerLoading(false);
    }
  };

  const handleGenerateScene = async () => {
    if (!selected) return;
    setSceneGenerating(true);
    try {
      const res = await productApi.generateSceneImages(selected.id, {
        scene_name: sceneName || selected.space,
        style_hint: sceneStyleHint || selected.style,
        user_request: sceneRequest || `请生成 ${selected.product_name} 在 ${sceneName || selected.space || '客厅'} 的真实搭配效果图`,
      });
      setSceneRecords((prev) => [res.data, ...prev]);
      message.success(`场景图已生成，耗时 ${res.data.duration_ms} ms`);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail ? `场景图生成失败: ${detail.slice(0, 160)}` : '场景图生成失败');
    } finally {
      setSceneGenerating(false);
    }
  };

  const getImageSrc = (p: ProductEntry, order = 0) =>
    `/api/products/${p.id}/images/${order}`;

  return (
    <div style={{ padding: 0 }}>
      {/* Header bar */}
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
          产品库
          <Badge
            count={products.length}
            overflowCount={9999}
            style={{ marginLeft: 10, backgroundColor: '#1890ff' }}
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
            {metaBrands.map((b) => (
              <Option key={b} value={b}>{b}</Option>
            ))}
          </Select>
          <Input
            prefix={<SearchOutlined />}
            placeholder="搜索产品名 / 系列"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            style={{ width: 200 }}
            allowClear
          />
          <Select
            placeholder="空间"
            allowClear
            style={{ width: 120 }}
            value={spaceFilter}
            onChange={setSpaceFilter}
            showSearch
            optionFilterProp="children"
          >
            {metaSpaces.map((s) => (
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
            {metaStyles.map((s) => (
              <Option key={s} value={s}>{s}</Option>
            ))}
          </Select>
          <Select
            placeholder="系列"
            allowClear
            style={{ width: 180 }}
            value={seriesFilter}
            onChange={setSeriesFilter}
            showSearch
            optionFilterProp="children"
          >
            {metaSeries.map((s) => (
              <Option key={s} value={s}>{s}</Option>
            ))}
          </Select>
          <Button
            icon={<ReloadOutlined />}
            loading={importing}
            onClick={handleImport}
          >
            重新导入
          </Button>
        </Space>
      </div>

      {/* Grid */}
      <Spin spinning={loading}>
        {products.length === 0 && !loading ? (
          <Empty description="暂无产品数据，请先点击「重新导入」" />
        ) : (
          <Row gutter={[16, 16]}>
            {products.map((p) => {
              const imgKey = `${p.id}-0`;
              const imgFailed = imgErrors[imgKey];
              return (
                <Col key={p.id} xs={24} sm={12} md={8} lg={6} xl={6}>
                  <Card
                    hoverable
                    style={{ borderRadius: 10, overflow: 'hidden' }}
                    cover={
                      imgFailed ? (
                        <div
                          style={{
                            height: 180,
                            background: '#f5f5f5',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            color: '#bbb',
                            fontSize: 13,
                          }}
                        >
                          暂无图片
                        </div>
                      ) : (
                        <img
                          src={getImageSrc(p, 0)}
                          alt={p.product_name}
                          onError={() => setImgErrors((prev) => ({ ...prev, [imgKey]: true }))}
                          style={{
                            width: '100%',
                            height: 180,
                            objectFit: 'cover',
                            display: 'block',
                          }}
                        />
                      )
                    }
                    onClick={() => openDetail(p)}
                    bodyStyle={{ padding: '12px 14px' }}
                  >
                    <Text
                      strong
                      ellipsis={{ tooltip: p.product_name }}
                      style={{ fontSize: 14, display: 'block', marginBottom: 6 }}
                    >
                      {p.product_name || '—'}
                    </Text>
                    <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
                      {p.series_name || ''}
                    </Text>
                    <Space size={4} wrap style={{ marginBottom: 6 }}>
                      {p.space && <Tag color={tagColor(p.space)}>{p.space}</Tag>}
                      {p.style && <Tag color={tagColor(p.style)}>{p.style}</Tag>}
                      {p.color && <Tag>{p.color}</Tag>}
                    </Space>
                    <Text style={{ fontSize: 13, color: '#f50', fontWeight: 600 }}>
                      {p.price_display || '价格面议'}
                    </Text>
                  </Card>
                </Col>
              );
            })}
          </Row>
        )}
      </Spin>

      {/* Detail Drawer */}
      <Drawer
        title={selected?.product_name || '产品详情'}
        placement="right"
        width={680}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        destroyOnClose
      >
        {selected && drawerLoading && (
          <div style={{ textAlign: 'center', padding: 40 }}>
            <Spin tip="加载中..." />
          </div>
        )}
        {selected && !drawerLoading && (
          <div>
            {/* Image gallery */}
            <Image.PreviewGroup>
              <Space wrap style={{ marginBottom: 16 }}>
                {selected.images && selected.images.length > 0 ? (
                  selected.images.map((img) => (
                    <Image
                      key={img.id}
                      src={`/api/products/${selected.id}/images/${img.display_order}`}
                      width={160}
                      height={120}
                      style={{ objectFit: 'cover', borderRadius: 6 }}
                      fallback="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mN8/+F9PQAI8wNPvd7POQAAAABJRU5ErkJggg=="
                    />
                  ))
                ) : (
                  <Text type="secondary">暂无展示图</Text>
                )}
              </Space>
            </Image.PreviewGroup>

            <Descriptions column={2} bordered size="small" style={{ marginBottom: 16 }}>
              <Descriptions.Item label="品牌">{selected.brand}</Descriptions.Item>
              <Descriptions.Item label="官网 ID">{selected.product_id_ext}</Descriptions.Item>
              <Descriptions.Item label="产品名" span={2}>{selected.product_name}</Descriptions.Item>
              <Descriptions.Item label="系列" span={2}>{selected.series_name}</Descriptions.Item>
              <Descriptions.Item label="空间">{selected.space}</Descriptions.Item>
              <Descriptions.Item label="风格">{selected.style}</Descriptions.Item>
              <Descriptions.Item label="颜色">{selected.color}</Descriptions.Item>
              <Descriptions.Item label="材质">{selected.material}</Descriptions.Item>
              <Descriptions.Item label="尺寸" span={2}>{selected.size}</Descriptions.Item>
              <Descriptions.Item label="展示价">{selected.price_display}</Descriptions.Item>
              <Descriptions.Item label="原价">{selected.original_price}</Descriptions.Item>
              <Descriptions.Item label="型号">{selected.serial_number}</Descriptions.Item>
              <Descriptions.Item label="购买链接">
                {selected.buy_url ? (
                  <Link href={selected.buy_url} target="_blank">
                    <ShoppingCartOutlined /> 立即购买
                  </Link>
                ) : '—'}
              </Descriptions.Item>
              <Descriptions.Item label="详情页" span={2}>
                {selected.detail_url ? (
                  <Link href={selected.detail_url} target="_blank">{selected.detail_url}</Link>
                ) : '—'}
              </Descriptions.Item>
            </Descriptions>

            {selected.description_text && (
              <div style={{ marginBottom: 12 }}>
                <Text strong>简介</Text>
                <div
                  style={{
                    marginTop: 6,
                    padding: '8px 12px',
                    background: '#f9f9f9',
                    borderRadius: 6,
                    fontSize: 13,
                    whiteSpace: 'pre-wrap',
                  }}
                >
                  {selected.description_text}
                </div>
              </div>
            )}

            {selected.detail_content_text && (
              <div>
                <Text strong>详情正文</Text>
                <div
                  style={{
                    marginTop: 6,
                    padding: '8px 12px',
                    background: '#f9f9f9',
                    borderRadius: 6,
                    fontSize: 12,
                    maxHeight: 300,
                    overflowY: 'auto',
                    whiteSpace: 'pre-wrap',
                    color: '#555',
                  }}
                >
                  {selected.detail_content_text}
                </div>
              </div>
            )}

            <Divider />

            <div style={{ marginBottom: 16 }}>
              <Text strong>场景图推荐 / 效果图生成</Text>
              <div style={{ marginTop: 10 }}>
                <Space direction="vertical" style={{ width: '100%' }} size={10}>
                  <Space wrap style={{ width: '100%' }}>
                    <Input
                      value={sceneName}
                      onChange={(e) => setSceneName(e.target.value)}
                      placeholder="场景，如：中式客厅 / 高端样板间 / 餐厅"
                      style={{ width: 220 }}
                    />
                    <Input
                      value={sceneStyleHint}
                      onChange={(e) => setSceneStyleHint(e.target.value)}
                      placeholder="风格提示，如：新中式 / 轻奢 / 现代"
                      style={{ width: 220 }}
                    />
                    <Button
                      type="primary"
                      icon={<PictureOutlined />}
                      loading={sceneGenerating}
                      onClick={handleGenerateScene}
                    >
                      生成 3 张场景图
                    </Button>
                  </Space>
                  <TextArea
                    value={sceneRequest}
                    onChange={(e) => setSceneRequest(e.target.value)}
                    rows={3}
                    placeholder="可补充给模型的场景要求，例如：保留真皮纹理、放在中式客厅、搭配茶几和边柜、不要改动外观比例。"
                  />
                </Space>
              </div>
            </div>

            <div>
              <Text strong>最近场景图生成记录</Text>
              <div style={{ marginTop: 10, display: 'grid', gap: 12 }}>
                {sceneRecords.length === 0 ? (
                  <Text type="secondary">暂无记录</Text>
                ) : (
                  sceneRecords.map((record) => (
                    <Card key={record.id} size="small" bodyStyle={{ padding: 12 }}>
                      <Space direction="vertical" style={{ width: '100%' }} size={8}>
                        <Space wrap>
                          <Tag color={record.status === 'completed' ? 'green' : 'red'}>
                            {record.status}
                          </Tag>
                          <Tag>{record.scene_name || '未指定场景'}</Tag>
                          {record.style_hint && <Tag>{record.style_hint}</Tag>}
                          <Text type="secondary">耗时 {record.duration_ms} ms</Text>
                        </Space>

                        {record.request_text && (
                          <div style={{ whiteSpace: 'pre-wrap', fontSize: 12, color: '#666' }}>
                            {record.request_text}
                          </div>
                        )}

                        {record.image_urls.length > 0 && (
                          <Image.PreviewGroup>
                            <Space wrap>
                              {record.image_urls.map((url) => (
                                <Image
                                  key={url}
                                  src={url}
                                  width={120}
                                  height={90}
                                  style={{ objectFit: 'cover', borderRadius: 6 }}
                                />
                              ))}
                            </Space>
                          </Image.PreviewGroup>
                        )}

                        {record.related_products.length > 0 && (
                          <div style={{ fontSize: 12 }}>
                            <Text type="secondary">搭配商品：</Text>
                            <Space wrap style={{ marginTop: 4 }}>
                              {record.related_products.map((item) => (
                                <Link
                                  key={item.id}
                                  href={item.buy_url || item.detail_url}
                                  target="_blank"
                                >
                                  {item.product_name}
                                </Link>
                              ))}
                            </Space>
                          </div>
                        )}

                        {record.error_message && (
                          <Text type="danger">{record.error_message}</Text>
                        )}
                      </Space>
                    </Card>
                  ))
                )}
              </div>
            </div>
          </div>
        )}
      </Drawer>
    </div>
  );
}
