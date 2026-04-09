import { useCallback, useEffect, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  Col,
  Descriptions,
  Drawer,
  Empty,
  Image,
  Input,
  Modal,
  Result,
  Row,
  Select,
  Space,
  Spin,
  Steps,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  CheckCircleOutlined,
  CloseOutlined,
  ReloadOutlined,
  SearchOutlined,
  ShoppingCartOutlined,
  PictureOutlined,
  StarOutlined,
  StarFilled,
} from '@ant-design/icons';
import { productApi, sceneGeneratorApi } from '../api';
import type { ProductEntry, SceneGenerationRecord, ProductImageRef } from '../types';

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

  // Scene Generator modal state
  const [genModalOpen, setGenModalOpen] = useState(false);
  const [genStep, setGenStep] = useState(0);
  const [genProducts, setGenProducts] = useState<ProductEntry[]>([]);
  const [genBrowseList, setGenBrowseList] = useState<ProductEntry[]>([]);
  const [genBrowseLoading, setGenBrowseLoading] = useState(false);
  const [genBrowseKw, setGenBrowseKw] = useState('');
  const [genBrowseBrand, setGenBrowseBrand] = useState<string | undefined>();
  const [genSelectedImages, setGenSelectedImages] = useState<ProductImageRef[]>([]);
  const [genSceneName, setGenSceneName] = useState('');
  const [genStyleHint, setGenStyleHint] = useState('');
  const [genUserRequest, setGenUserRequest] = useState('');
  const [genGenerating, setGenGenerating] = useState(false);
  const [genResult, setGenResult] = useState<SceneGenerationRecord | null>(null);

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
    setDrawerLoading(true);
    try {
      const detailRes = await productApi.get(p.id);
      setSelected(detailRes.data);
    } catch {
      message.error('加载产品详情失败');
    } finally {
      setDrawerLoading(false);
    }
  };

  const getImageSrc = (p: ProductEntry, order = 0) =>
    `/api/products/${p.id}/images/${order}`;

  // --- Scene Generator helpers ---
  const fetchGenBrowse = useCallback(async (kw?: string, brand?: string) => {
    setGenBrowseLoading(true);
    try {
      const res = await productApi.list({ keyword: kw || undefined, brand, limit: 100 });
      setGenBrowseList(res.data);
    } catch { /* ignore */ } finally {
      setGenBrowseLoading(false);
    }
  }, []);

  const openGenModal = () => {
    setGenStep(0);
    setGenProducts([]);
    setGenBrowseKw('');
    setGenBrowseBrand(undefined);
    setGenSelectedImages([]);
    setGenSceneName('');
    setGenStyleHint('');
    setGenUserRequest('');
    setGenResult(null);
    setGenGenerating(false);
    setGenModalOpen(true);
    fetchGenBrowse();
  };

  const toggleGenProduct = async (p: ProductEntry) => {
    if (genProducts.find((x) => x.id === p.id)) {
      setGenProducts((prev) => prev.filter((x) => x.id !== p.id));
      setGenSelectedImages((prev) => prev.filter((r) => r.product_id !== p.id));
      return;
    }
    try {
      const res = await productApi.get(p.id);
      setGenProducts((prev) => [...prev, res.data]);
    } catch {
      setGenProducts((prev) => [...prev, p]);
    }
  };

  const isGenProductAdded = (pid: number) => genProducts.some((p) => p.id === pid);

  const toggleGenImage = (ref: ProductImageRef) => {
    setGenSelectedImages((prev) => {
      const exists = prev.find((r) => r.product_id === ref.product_id && r.image_order === ref.image_order);
      if (exists) return prev.filter((r) => !(r.product_id === ref.product_id && r.image_order === ref.image_order));
      if (prev.length >= 4) { message.warning('最多选择 4 张图片'); return prev; }
      return [...prev, ref];
    });
  };

  const isGenImageSelected = (pid: number, order: number) =>
    genSelectedImages.some((r) => r.product_id === pid && r.image_order === order);

  const handleGenGenerate = async () => {
    if (genSelectedImages.length === 0) { message.warning('请至少选择 1 张产品图片'); return; }
    setGenGenerating(true);
    setGenStep(2);
    try {
      const res = await sceneGeneratorApi.generate({
        product_image_refs: genSelectedImages,
        scene_name: genSceneName || undefined,
        style_hint: genStyleHint || undefined,
        user_request: genUserRequest || undefined,
      });
      setGenResult(res.data);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail ? `生成失败: ${detail.slice(0, 200)}` : '场景生成失败');
      setGenStep(1);
    } finally {
      setGenGenerating(false);
    }
  };

  const handleToggleLibrary = async (recordId: number) => {
    try {
      const res = await sceneGeneratorApi.toggleLibrary(recordId);
      if (genResult && genResult.id === recordId) {
        setGenResult({ ...genResult, in_library: res.data.in_library });
      }
      message.success(res.data.in_library ? '已加入场景库' : '已从场景库移除');
    } catch {
      message.error('操作失败');
    }
  };

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
            type="primary"
            icon={<PictureOutlined />}
            onClick={openGenModal}
          >
            场景生成器
          </Button>
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

          </div>
        )}
      </Drawer>

      {/* Scene Generator Modal */}
      <Modal
        title="场景生成器"
        open={genModalOpen}
        onCancel={() => { if (!genGenerating) setGenModalOpen(false); }}
        footer={null}
        width={900}
        destroyOnClose
        maskClosable={!genGenerating}
      >
        <Steps
          current={genStep}
          size="small"
          style={{ marginBottom: 20 }}
          items={[
            { title: '选择产品图片' },
            { title: '配置生成参数' },
            { title: '生成结果' },
          ]}
        />

        {/* Step 0: select products & images */}
        {genStep === 0 && (
          <div>
            {/* Search / filter bar */}
            <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
              <Input
                prefix={<SearchOutlined />}
                placeholder="搜索产品名 / 系列"
                value={genBrowseKw}
                onChange={(e) => setGenBrowseKw(e.target.value)}
                onPressEnter={() => fetchGenBrowse(genBrowseKw, genBrowseBrand)}
                allowClear
                onClear={() => fetchGenBrowse('', genBrowseBrand)}
                style={{ width: 220 }}
              />
              <Select
                placeholder="品牌"
                allowClear
                style={{ width: 130 }}
                value={genBrowseBrand}
                onChange={(v) => { setGenBrowseBrand(v); fetchGenBrowse(genBrowseKw, v); }}
                showSearch
                optionFilterProp="children"
              >
                {metaBrands.map((b) => (
                  <Option key={b} value={b}>{b}</Option>
                ))}
              </Select>
              <Button
                icon={<SearchOutlined />}
                onClick={() => fetchGenBrowse(genBrowseKw, genBrowseBrand)}
              >
                搜索
              </Button>
              {genProducts.length > 0 && (
                <Tag color="blue" style={{ lineHeight: '30px', fontSize: 13 }}>
                  已添加 {genProducts.length} 个产品
                </Tag>
              )}
            </div>

            {/* Scrollable product grid */}
            <Spin spinning={genBrowseLoading}>
              <div style={{
                maxHeight: 320, overflowY: 'auto',
                border: '1px solid #f0f0f0', borderRadius: 8,
                padding: 8, background: '#fafafa',
              }}>
                {genBrowseList.length === 0 && !genBrowseLoading ? (
                  <Empty description="暂无产品" style={{ padding: 20 }} />
                ) : (
                  <Row gutter={[10, 10]}>
                    {genBrowseList.map((p) => {
                      const added = isGenProductAdded(p.id);
                      return (
                        <Col key={p.id} span={6}>
                          <div
                            onClick={() => toggleGenProduct(p)}
                            style={{
                              position: 'relative',
                              borderRadius: 8,
                              overflow: 'hidden',
                              border: added ? '3px solid #1890ff' : '2px solid #f0f0f0',
                              cursor: 'pointer',
                              background: '#fff',
                              transition: 'border-color 0.2s',
                            }}
                          >
                            <img
                              src={`/api/products/${p.id}/images/0`}
                              alt={p.product_name}
                              style={{ width: '100%', height: 100, objectFit: 'cover', display: 'block' }}
                              onError={(e) => { (e.target as HTMLImageElement).style.opacity = '0.15'; }}
                            />
                            {added && (
                              <div style={{
                                position: 'absolute', top: 4, right: 4,
                                background: '#1890ff', borderRadius: '50%',
                                width: 22, height: 22, display: 'flex',
                                alignItems: 'center', justifyContent: 'center',
                              }}>
                                <CheckCircleOutlined style={{ color: '#fff', fontSize: 14 }} />
                              </div>
                            )}
                            <div style={{ padding: '4px 6px' }}>
                              <div style={{
                                fontSize: 11, fontWeight: 600,
                                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                              }}>
                                {p.product_name || '—'}
                              </div>
                              <div style={{ fontSize: 10, color: '#999', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                {[p.brand, p.space, p.style].filter(Boolean).join(' · ')}
                              </div>
                            </div>
                          </div>
                        </Col>
                      );
                    })}
                  </Row>
                )}
              </div>
            </Spin>

            {/* Selected products - pick images */}
            {genProducts.length > 0 && (
              <div style={{ marginTop: 14 }}>
                <Text strong style={{ fontSize: 13 }}>
                  选择图片（已选 {genSelectedImages.length}/4，点击图片选择/取消）
                </Text>
                <div style={{
                  marginTop: 8, maxHeight: 200, overflowY: 'auto',
                  display: 'flex', flexDirection: 'column', gap: 10,
                }}>
                  {genProducts.map((p) => (
                    <div key={p.id} style={{
                      display: 'flex', alignItems: 'center', gap: 8,
                      padding: '6px 10px', background: '#f7f9fc', borderRadius: 6,
                      border: '1px solid #e8ecf1',
                    }}>
                      <div style={{ minWidth: 100, fontSize: 12, fontWeight: 600 }}>
                        <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 100 }}>
                          {p.product_name}
                        </div>
                        {p.brand && <Tag color="blue" style={{ fontSize: 10, marginTop: 2 }}>{p.brand}</Tag>}
                      </div>
                      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', flex: 1 }}>
                        {p.images && p.images.length > 0 ? (
                          p.images.map((img) => {
                            const sel = isGenImageSelected(p.id, img.display_order);
                            return (
                              <div
                                key={img.id}
                                onClick={() => toggleGenImage({ product_id: p.id, image_order: img.display_order })}
                                style={{
                                  position: 'relative',
                                  width: 64, height: 50,
                                  borderRadius: 5, overflow: 'hidden',
                                  border: sel ? '3px solid #1890ff' : '2px solid #eee',
                                  cursor: 'pointer',
                                  opacity: !sel && genSelectedImages.length >= 4 ? 0.35 : 1,
                                  flexShrink: 0,
                                }}
                              >
                                <img
                                  src={`/api/products/${p.id}/images/${img.display_order}`}
                                  alt=""
                                  style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
                                />
                                {sel && (
                                  <div style={{
                                    position: 'absolute', top: 1, right: 1,
                                    background: '#1890ff', borderRadius: '50%',
                                    width: 16, height: 16, display: 'flex',
                                    alignItems: 'center', justifyContent: 'center',
                                  }}>
                                    <CheckCircleOutlined style={{ color: '#fff', fontSize: 10 }} />
                                  </div>
                                )}
                              </div>
                            );
                          })
                        ) : (
                          <Text type="secondary" style={{ fontSize: 11 }}>暂无图片</Text>
                        )}
                      </div>
                      <Button
                        size="small"
                        type="text"
                        danger
                        icon={<CloseOutlined />}
                        onClick={() => {
                          setGenProducts((prev) => prev.filter((x) => x.id !== p.id));
                          setGenSelectedImages((prev) => prev.filter((r) => r.product_id !== p.id));
                        }}
                      />
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div style={{ marginTop: 16, textAlign: 'right' }}>
              <Button
                type="primary"
                disabled={genSelectedImages.length === 0}
                onClick={() => setGenStep(1)}
              >
                下一步：配置参数
              </Button>
            </div>
          </div>
        )}

        {/* Step 1: configure parameters */}
        {genStep === 1 && (
          <div>
            <div style={{ marginBottom: 12 }}>
              <Text strong style={{ display: 'block', marginBottom: 4 }}>已选图片预览</Text>
              <Space wrap>
                {genSelectedImages.map((ref, idx) => (
                  <div key={idx} style={{ position: 'relative', width: 80, height: 60, borderRadius: 6, overflow: 'hidden', border: '2px solid #1890ff' }}>
                    <img
                      src={`/api/products/${ref.product_id}/images/${ref.image_order}`}
                      alt=""
                      style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                    />
                  </div>
                ))}
              </Space>
            </div>

            <Space direction="vertical" style={{ width: '100%' }} size={12}>
              <div>
                <Text style={{ display: 'block', marginBottom: 4 }}>场景名称</Text>
                <Input
                  value={genSceneName}
                  onChange={(e) => setGenSceneName(e.target.value)}
                  placeholder="如：中式客厅 / 高端卧室 / 现代书房"
                />
              </div>
              <div>
                <Text style={{ display: 'block', marginBottom: 4 }}>风格提示</Text>
                <Input
                  value={genStyleHint}
                  onChange={(e) => setGenStyleHint(e.target.value)}
                  placeholder="如：新中式 / 轻奢 / 现代简约"
                />
              </div>
              <div>
                <Text style={{ display: 'block', marginBottom: 4 }}>补充要求（可选）</Text>
                <TextArea
                  value={genUserRequest}
                  onChange={(e) => setGenUserRequest(e.target.value)}
                  rows={3}
                  placeholder="例如：保留真皮纹理、放在中式客厅、不要改动外观比例"
                />
              </div>
            </Space>

            <div style={{ marginTop: 16, display: 'flex', justifyContent: 'space-between' }}>
              <Button onClick={() => setGenStep(0)}>上一步</Button>
              <Button type="primary" onClick={handleGenGenerate} loading={genGenerating}>
                开始生成
              </Button>
            </div>
          </div>
        )}

        {/* Step 2: results */}
        {genStep === 2 && (
          <div>
            {genGenerating ? (
              <div style={{ textAlign: 'center', padding: 60 }}>
                <Spin size="large" />
                <div style={{ marginTop: 16, color: '#666' }}>场景图生成中，请耐心等待...</div>
                <div style={{ marginTop: 8, color: '#999', fontSize: 12 }}>通常需要 30~120 秒</div>
              </div>
            ) : genResult ? (
              <div>
                {genResult.status === 'completed' ? (
                  <>
                    <Result
                      status="success"
                      title="场景图生成成功"
                      subTitle={`耗时 ${(genResult.duration_ms / 1000).toFixed(1)} 秒`}
                      style={{ padding: '12px 0' }}
                    />
                    <Image.PreviewGroup>
                      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', justifyContent: 'center', marginBottom: 16 }}>
                        {genResult.image_urls.map((url, idx) => (
                          <Image
                            key={idx}
                            src={url}
                            width={240}
                            height={170}
                            style={{ objectFit: 'cover', borderRadius: 8 }}
                          />
                        ))}
                      </div>
                    </Image.PreviewGroup>

                    {genResult.related_products.length > 0 && (
                      <div style={{ marginBottom: 16 }}>
                        <Text type="secondary" style={{ fontSize: 12 }}>搭配产品：</Text>
                        <Space wrap style={{ marginTop: 4 }}>
                          {genResult.related_products.map((rp) => (
                            <Tag key={rp.id}>{rp.brand ? `[${rp.brand}] ` : ''}{rp.product_name}</Tag>
                          ))}
                        </Space>
                      </div>
                    )}

                    <div style={{ textAlign: 'center', marginTop: 8 }}>
                      <Space size={16}>
                        <Button
                          type={genResult.in_library ? 'default' : 'primary'}
                          icon={genResult.in_library ? <StarFilled style={{ color: '#faad14' }} /> : <StarOutlined />}
                          onClick={() => handleToggleLibrary(genResult.id)}
                        >
                          {genResult.in_library ? '已在场景库' : '加入场景库'}
                        </Button>
                        <Button onClick={openGenModal}>重新生成</Button>
                        <Button onClick={() => setGenModalOpen(false)}>关闭</Button>
                      </Space>
                    </div>
                  </>
                ) : (
                  <Result
                    status="error"
                    title="生成失败"
                    subTitle={genResult.error_message || '未知错误'}
                    extra={[
                      <Button key="retry" onClick={() => setGenStep(1)}>返回重试</Button>,
                    ]}
                  />
                )}
              </div>
            ) : null}
          </div>
        )}
      </Modal>
    </div>
  );
}
