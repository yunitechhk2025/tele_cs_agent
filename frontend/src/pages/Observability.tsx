import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Alert,
  Button,
  Col,
  Empty,
  Progress,
  Row,
  Segmented,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { CheckOutlined, DownloadOutlined, ReloadOutlined } from '@ant-design/icons';
import { botApi, observabilityApi } from '../api';
import StageTrendChart, { type StageTrendMetricKey } from '../components/StageTrendChart';
import type {
  ObservabilityAlert,
  ObservabilityFailureSample,
  ObservabilityIntentStageTrend,
  ObservabilityLLMMetric,
  ObservabilityStageMetric,
  ObservabilityStageTrendResponse,
  ObservabilitySummary,
  TelegramBot,
} from '../types';

const { Title, Text } = Typography;

const RANGE_OPTIONS = [
  { label: '最近 24 小时', value: '24h' },
  { label: '最近 7 天', value: '7d' },
  { label: '最近 30 天', value: '30d' },
] as const;

const LANGUAGE_OPTIONS = [
  { label: '全部语言', value: '' },
  { label: '简体中文', value: 'zh-Hans' },
  { label: '繁体中文', value: 'zh-Hant' },
  { label: '英文', value: 'en' },
  { label: '日语', value: 'ja' },
  { label: '韩语', value: 'ko' },
  { label: '西班牙语', value: 'es' },
  { label: '法语', value: 'fr' },
];

const INTENT_OPTIONS = [
  { label: '全部意图', value: '' },
  { label: '普通问答', value: 'general_question' },
  { label: '商品推荐', value: 'product_recommendation' },
  { label: '商品详情', value: 'product_intro' },
  { label: '场景图', value: 'scene_image_request' },
  { label: '文件请求', value: 'file_request' },
  { label: '转人工', value: 'human_handoff' },
  { label: '报价转人工', value: 'quote_handoff' },
  { label: '投诉', value: 'complaint' },
];

const RESPONSE_KIND_OPTIONS = [
  { label: '全部回复类型', value: '' },
  { label: '文本', value: 'text' },
  { label: '文本草稿', value: 'text_draft' },
  { label: '商品推荐', value: 'product_recommendation' },
  { label: '商品推荐草稿', value: 'product_recommendation_draft' },
  { label: '商品详情', value: 'product_detail' },
  { label: '场景图结果', value: 'scene_result' },
  { label: '场景图失败', value: 'scene_failed' },
  { label: '转人工', value: 'handoff' },
  { label: '需求解析转人工', value: 'profile_handoff' },
  { label: '错误', value: 'error' },
];

function formatLatency(value: number | null | undefined) {
  if (value == null) return '-';
  if (value >= 1000) return `${(value / 1000).toFixed(1)}s`;
  return `${value}ms`;
}

function formatRate(value: number | null | undefined) {
  return `${Math.round((value || 0) * 1000) / 10}%`;
}

function severityTag(severity: string) {
  if (severity === 'critical') return <Tag color="red">critical</Tag>;
  return <Tag color="orange">warning</Tag>;
}

function statusTag(status: string) {
  if (status === 'open') return <Tag color="red">open</Tag>;
  if (status === 'ack') return <Tag color="blue">ack</Tag>;
  return <Tag>{status}</Tag>;
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return '-';
  return value.replace('T', ' ').slice(0, 19);
}

function parseSampleConversationIds(raw: string | null | undefined) {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.map((item) => Number(item)).filter((item) => Number.isInteger(item) && item > 0);
  } catch {
    return [];
  }
}

function normalizeRange(value: string | null): '24h' | '7d' | '30d' {
  return value === '7d' || value === '30d' ? value : '24h';
}

const TREND_METRIC_OPTIONS = [
  { label: '平均', value: 'avg_ms' },
  { label: 'P50', value: 'p50_ms' },
  { label: 'P95', value: 'p95_ms' },
  { label: 'P99', value: 'p99_ms' },
] as const;

export default function Observability() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [range, setRange] = useState<'24h' | '7d' | '30d'>(() =>
    normalizeRange(searchParams.get('range')),
  );
  const [botId, setBotId] = useState<number | undefined>(() => {
    const raw = searchParams.get('bot_id');
    const value = raw ? Number(raw) : undefined;
    return value && Number.isInteger(value) ? value : undefined;
  });
  const [language, setLanguage] = useState(() => searchParams.get('language') || '');
  const [intent, setIntent] = useState(() => searchParams.get('intent') || '');
  const [responseKind, setResponseKind] = useState(() => searchParams.get('response_kind') || '');
  const [trendMetric, setTrendMetric] = useState<StageTrendMetricKey>('p95_ms');
  const [bots, setBots] = useState<TelegramBot[]>([]);
  const [summary, setSummary] = useState<ObservabilitySummary | null>(null);
  const [trends, setTrends] = useState<ObservabilityStageTrendResponse | null>(null);
  const [stageSelections, setStageSelections] = useState<Record<string, string[]>>({});
  const [alerts, setAlerts] = useState<ObservabilityAlert[]>([]);
  const [loading, setLoading] = useState(false);
  const [alertLoading, setAlertLoading] = useState(false);
  const [exportLoading, setExportLoading] = useState(false);

  const params = useMemo(
    () => ({
      range,
      bot_id: botId,
      language: language || undefined,
      intent: intent || undefined,
      response_kind: responseKind || undefined,
    }),
    [range, botId, language, intent, responseKind],
  );

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [{ data: summaryData }, { data: alertData }, { data: trendData }] = await Promise.all([
        observabilityApi.getSummary(params),
        observabilityApi.listAlerts({ limit: 100 }),
        observabilityApi.getStageTrends(params),
      ]);
      setSummary(summaryData);
      setAlerts(alertData);
      setTrends(trendData);
      // 默认展开每个意图下最重的前 5 个阶段，避免大流量下趋势图一次性渲染过多曲线。
      setStageSelections(
        Object.fromEntries(
          trendData.intents.map((group) => [
            group.intent,
            group.stages.slice(0, 5).map((stage) => stage.stage_key),
          ]),
        ),
      );
    } catch (err) {
      console.error(err);
      message.error('监控数据加载失败');
    } finally {
      setLoading(false);
    }
  }, [params]);

  const loadBots = async () => {
    try {
      const { data } = await botApi.list();
      setBots(data);
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    loadBots();
  }, []);

  useEffect(() => {
    const next = new URLSearchParams();
    next.set('range', range);
    if (botId) next.set('bot_id', String(botId));
    if (language) next.set('language', language);
    if (intent) next.set('intent', intent);
    if (responseKind) next.set('response_kind', responseKind);
    // 监控筛选条件需要可分享和可刷新，所有核心过滤项都同步到 URL。
    setSearchParams(next, { replace: true });
  }, [botId, intent, language, range, responseKind, setSearchParams]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const ackAlert = async (id: number) => {
    setAlertLoading(true);
    try {
      await observabilityApi.ackAlert(id);
      message.success('告警已确认');
      await loadData();
    } catch (err) {
      console.error(err);
      message.error('告警确认失败');
    } finally {
      setAlertLoading(false);
    }
  };

  const exportData = async () => {
    setExportLoading(true);
    try {
      const response = await observabilityApi.exportData(params);
      const disposition = response.headers['content-disposition'] || '';
      const match = /filename="([^"]+)"/.exec(disposition);
      const filename = match?.[1] || `observability-${range}.zip`;
      const blob = new Blob([response.data], { type: 'application/zip' });
      const href = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = href;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(href);
      message.success('导出已开始');
    } catch (err) {
      console.error(err);
      message.error('导出失败');
    } finally {
      setExportLoading(false);
    }
  };

  const stageColumns: ColumnsType<ObservabilityStageMetric> = [
    {
      title: '阶段',
      dataIndex: 'stage_label',
      render: (value, row) => (
        <Space direction="vertical" size={2}>
          <Text strong>{value || row.stage_key}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {row.stage_key}
          </Text>
        </Space>
      ),
    },
    { title: '次数', dataIndex: 'count', width: 90 },
    { title: '平均', dataIndex: 'avg_ms', width: 100, render: formatLatency },
    { title: 'P50', dataIndex: 'p50_ms', width: 100, render: formatLatency },
    {
      title: 'P95',
      dataIndex: 'p95_ms',
      width: 100,
      render: formatLatency,
      sorter: (a, b) => (a.p95_ms || 0) - (b.p95_ms || 0),
    },
    { title: 'P99', dataIndex: 'p99_ms', width: 100, render: formatLatency },
    {
      title: '失败',
      dataIndex: 'failed_count',
      width: 90,
      render: (value: number) =>
        value ? <Tag color="red">{value}</Tag> : <Tag color="green">0</Tag>,
    },
  ];

  const llmColumns: ColumnsType<ObservabilityLLMMetric> = [
    { title: 'Operation', dataIndex: 'operation', width: 180 },
    { title: 'Model', dataIndex: 'model', ellipsis: true },
    { title: '次数', dataIndex: 'count', width: 80 },
    {
      title: '失败率',
      dataIndex: 'failure_rate',
      width: 120,
      render: (value) => <Tag color={value > 0 ? 'red' : 'green'}>{formatRate(value)}</Tag>,
    },
    { title: '平均', dataIndex: 'avg_ms', width: 100, render: formatLatency },
    { title: 'P95', dataIndex: 'p95_ms', width: 100, render: formatLatency },
    { title: 'P99', dataIndex: 'p99_ms', width: 100, render: formatLatency },
    { title: '最近错误', dataIndex: 'last_error', ellipsis: true, render: (value) => value || '-' },
  ];

  const alertColumns: ColumnsType<ObservabilityAlert> = [
    { title: '级别', dataIndex: 'severity', width: 100, render: severityTag },
    {
      title: '告警',
      dataIndex: 'title',
      render: (value, row) => (
        <Space direction="vertical" size={0}>
          <Text strong>{value}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {row.message}
          </Text>
        </Space>
      ),
    },
    { title: '指标', dataIndex: 'metric_key', width: 210 },
    {
      title: '观测值',
      dataIndex: 'observed_value',
      width: 100,
      render: (value) => value.toFixed(4),
    },
    {
      title: '阈值',
      dataIndex: 'threshold_value',
      width: 100,
      render: (value) => value.toFixed(4),
    },
    {
      title: '关联会话',
      dataIndex: 'sample_conversation_ids_json',
      width: 180,
      render: (value) => {
        const ids = parseSampleConversationIds(value);
        if (!ids.length) return '-';
        return (
          <Space size={4} wrap>
            {ids.slice(0, 5).map((id) => (
              <Button
                key={id}
                type="link"
                size="small"
                onClick={() => navigate(`/conversations/${id}`)}
              >
                #{id}
              </Button>
            ))}
          </Space>
        );
      },
    },
    { title: '状态', dataIndex: 'status', width: 100, render: statusTag },
    { title: '创建时间', dataIndex: 'created_at', width: 170, render: formatDateTime },
    {
      title: '操作',
      width: 110,
      render: (_, row) =>
        row.status === 'open' ? (
          <Button
            size="small"
            icon={<CheckOutlined />}
            loading={alertLoading}
            onClick={() => ackAlert(row.id)}
          >
            确认
          </Button>
        ) : null,
    },
  ];

  const failureColumns: ColumnsType<ObservabilityFailureSample> = [
    { title: '来源', dataIndex: 'source', width: 90, render: (value) => <Tag>{value}</Tag> },
    {
      title: '会话',
      dataIndex: 'conversation_id',
      width: 110,
      render: (value) =>
        value ? (
          <Button size="small" type="link" onClick={() => navigate(`/conversations/${value}`)}>
            #{value}
          </Button>
        ) : (
          '-'
        ),
    },
    { title: '语言', dataIndex: 'language', width: 100, render: (value) => value || '-' },
    { title: '意图', dataIndex: 'primary_intent', width: 180, render: (value) => value || '-' },
    { title: '回复类型', dataIndex: 'response_kind', width: 180, render: (value) => value || '-' },
    { title: '时间', dataIndex: 'created_at', width: 170, render: formatDateTime },
    { title: '错误', dataIndex: 'error_message', ellipsis: true, render: (value) => value || '-' },
  ];

  const kpis = summary?.kpis;
  const openAlertCount = alerts.filter((alert) => alert.status === 'open').length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          gap: 16,
          alignItems: 'center',
          flexWrap: 'wrap',
        }}
      >
        <div>
          <Title level={3} style={{ margin: 0 }}>
            监控看板
          </Title>
          <Text type="secondary">客服响应质量、链路耗时、模型调用和告警事件</Text>
        </div>
        <Space>
          <Button icon={<DownloadOutlined />} onClick={exportData} loading={exportLoading}>
            导出
          </Button>
          <Button icon={<ReloadOutlined />} onClick={loadData} loading={loading}>
            刷新
          </Button>
        </Space>
      </div>

      {openAlertCount > 0 ? (
        <Alert type="warning" showIcon message={`当前有 ${openAlertCount} 条未确认告警`} />
      ) : null}

      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        <Select
          value={range}
          onChange={setRange}
          options={[...RANGE_OPTIONS]}
          style={{ width: 150 }}
        />
        <Select
          value={botId}
          allowClear
          placeholder="全部 Bot"
          onChange={setBotId}
          style={{ width: 180 }}
          options={bots.map((bot) => ({ label: bot.name, value: bot.id }))}
        />
        <Select
          value={language}
          onChange={setLanguage}
          options={LANGUAGE_OPTIONS}
          style={{ width: 150 }}
        />
        <Select
          value={intent}
          onChange={setIntent}
          options={INTENT_OPTIONS}
          style={{ width: 180 }}
        />
        <Select
          value={responseKind}
          onChange={setResponseKind}
          options={RESPONSE_KIND_OPTIONS}
          style={{ width: 190 }}
        />
      </div>

      <Row gutter={[12, 12]}>
        <Col xs={24} sm={12} lg={6}>
          <div style={{ background: '#fff', borderRadius: 8, padding: 16 }}>
            <Statistic title="总轮次" value={kpis?.total_turns || 0} />
            <Text type="secondary">失败 {kpis?.failed_count || 0}</Text>
          </div>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <div style={{ background: '#fff', borderRadius: 8, padding: 16 }}>
            <Statistic title="成功率" value={formatRate(kpis?.success_rate)} />
            <Progress
              percent={Math.round((kpis?.success_rate || 0) * 100)}
              size="small"
              status={(kpis?.success_rate || 0) >= 0.95 ? 'success' : 'active'}
            />
          </div>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <div style={{ background: '#fff', borderRadius: 8, padding: 16 }}>
            <Statistic
              title="首响 P95 / P99"
              value={`${formatLatency(kpis?.first_response_p95_ms)} / ${formatLatency(kpis?.first_response_p99_ms)}`}
            />
            <Text type="secondary">文本 P95 {formatLatency(kpis?.text_first_response_p95_ms)}</Text>
          </div>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <div style={{ background: '#fff', borderRadius: 8, padding: 16 }}>
            <Statistic
              title="总耗时 P95 / P99"
              value={`${formatLatency(kpis?.total_p95_ms)} / ${formatLatency(kpis?.total_p99_ms)}`}
            />
            <Text type="secondary">P50 {formatLatency(kpis?.total_p50_ms)}</Text>
          </div>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <div style={{ background: '#fff', borderRadius: 8, padding: 16 }}>
            <Statistic title="转人工率" value={formatRate(kpis?.handoff_rate)} />
            <Text type="secondary">profile_handoff {formatRate(kpis?.profile_handoff_rate)}</Text>
          </div>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <div style={{ background: '#fff', borderRadius: 8, padding: 16 }}>
            <Statistic title="RAG 空命中率" value={formatRate(kpis?.rag_empty_rate)} />
            <Text type="secondary">
              {kpis?.rag_empty_count || 0}/{kpis?.rag_lookup_count || 0}
            </Text>
          </div>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <div style={{ background: '#fff', borderRadius: 8, padding: 16 }}>
            <Statistic title="LLM 失败率" value={formatRate(kpis?.llm_failure_rate)} />
            <Text type="secondary">
              {kpis?.llm_failure_count || 0}/{kpis?.llm_call_count || 0}
            </Text>
          </div>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <div style={{ background: '#fff', borderRadius: 8, padding: 16 }}>
            <Statistic title="场景图失败率" value={formatRate(kpis?.scene_failure_rate)} />
            <Text type="secondary">
              {kpis?.scene_failure_count || 0}/{kpis?.scene_generation_count || 0}
            </Text>
          </div>
        </Col>
      </Row>

      <div style={{ background: '#fff', borderRadius: 8, padding: 16 }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            gap: 12,
            alignItems: 'center',
            flexWrap: 'wrap',
            marginBottom: 12,
          }}
        >
          <div>
            <Title level={5} style={{ margin: 0 }}>
              阶段耗时趋势
            </Title>
            <Text type="secondary">按意图查看各阶段在当前时间范围内的耗时变化</Text>
          </div>
          <Segmented
            value={trendMetric}
            onChange={(value) => setTrendMetric(value as StageTrendMetricKey)}
            options={[...TREND_METRIC_OPTIONS]}
          />
        </div>
        {trends?.intents?.length ? (
          <Space direction="vertical" size={18} style={{ width: '100%' }}>
            {trends.intents.map((group: ObservabilityIntentStageTrend) => {
              const selectedKeys =
                stageSelections[group.intent] ||
                group.stages.slice(0, 5).map((stage) => stage.stage_key);
              return (
                <div key={group.intent} style={{ borderTop: '1px solid #f0f0f0', paddingTop: 14 }}>
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      gap: 12,
                      alignItems: 'center',
                      flexWrap: 'wrap',
                      marginBottom: 8,
                    }}
                  >
                    <Space direction="vertical" size={0}>
                      <Text strong>{group.intent_label}</Text>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        共 {group.stages.reduce((sum, stage) => sum + stage.count, 0)} 个阶段样本
                      </Text>
                    </Space>
                    <Select
                      mode="multiple"
                      maxTagCount="responsive"
                      value={selectedKeys}
                      onChange={(values) =>
                        setStageSelections((prev) => ({ ...prev, [group.intent]: values }))
                      }
                      options={group.stages.map((stage) => ({
                        label: stage.stage_label || stage.stage_key,
                        value: stage.stage_key,
                      }))}
                      style={{ minWidth: 280, maxWidth: 520 }}
                      placeholder="选择阶段"
                    />
                  </div>
                  {selectedKeys.length ? (
                    <StageTrendChart
                      stages={group.stages}
                      selectedStageKeys={selectedKeys}
                      metricKey={trendMetric}
                    />
                  ) : (
                    <Empty description="请选择至少一个阶段" />
                  )}
                </div>
              );
            })}
          </Space>
        ) : (
          <Empty description="暂无阶段趋势数据" />
        )}
      </div>

      <div style={{ background: '#fff', borderRadius: 8, padding: 16 }}>
        <Title level={5} style={{ marginTop: 0 }}>
          阶段耗时
        </Title>
        <Table
          rowKey="stage_key"
          size="small"
          loading={loading}
          columns={stageColumns}
          dataSource={summary?.stage_metrics || []}
          pagination={{ pageSize: 8 }}
          locale={{ emptyText: <Empty description="暂无阶段数据" /> }}
        />
      </div>

      <div style={{ background: '#fff', borderRadius: 8, padding: 16 }}>
        <Title level={5} style={{ marginTop: 0 }}>
          LLM 调用
        </Title>
        <Table
          rowKey={(row) => `${row.operation}-${row.model}`}
          size="small"
          loading={loading}
          columns={llmColumns}
          dataSource={summary?.llm_metrics || []}
          pagination={{ pageSize: 8 }}
          locale={{ emptyText: <Empty description="暂无 LLM 调用数据" /> }}
        />
      </div>

      <div style={{ background: '#fff', borderRadius: 8, padding: 16 }}>
        <Title level={5} style={{ marginTop: 0 }}>
          告警列表
        </Title>
        <Table
          rowKey="id"
          size="small"
          loading={loading}
          columns={alertColumns}
          dataSource={alerts}
          pagination={{ pageSize: 8 }}
          locale={{ emptyText: <Empty description="暂无告警" /> }}
        />
      </div>

      <div style={{ background: '#fff', borderRadius: 8, padding: 16 }}>
        <Title level={5} style={{ marginTop: 0 }}>
          最近失败样本
        </Title>
        <Table
          rowKey={(row, index) => `${row.source}-${row.conversation_id || 'none'}-${index}`}
          size="small"
          loading={loading}
          columns={failureColumns}
          dataSource={summary?.recent_failures || []}
          pagination={{ pageSize: 8 }}
          locale={{ emptyText: <Empty description="暂无失败样本" /> }}
        />
      </div>
    </div>
  );
}
