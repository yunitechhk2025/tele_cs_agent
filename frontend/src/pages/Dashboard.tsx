import { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Card,
  Row,
  Col,
  Statistic,
  Table,
  Tag,
  Typography,
  Spin,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { MessageOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { dashboardApi } from '../api';
import type { Conversation, DashboardStats } from '../types';

const { Title, Text } = Typography;

function formatCustomerName(c: Conversation): string {
  const parts = [c.first_name, c.last_name].filter(Boolean);
  if (parts.length) return parts.join(' ');
  if (c.username) return `@${c.username}`;
  return '未知用户';
}

function statusTag(status: Conversation['status']) {
  const map: Record<
    Conversation['status'],
    { color: string; label: string }
  > = {
    active: { color: 'green', label: '进行中' },
    pending_human: { color: 'orange', label: '待人工' },
    human_handling: { color: 'blue', label: '处理中' },
    closed: { color: 'default', label: '已关闭' },
  };
  const m = map[status];
  return <Tag color={m.color}>{m.label}</Tag>;
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState<DashboardStats | null>(null);

  const loadStats = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await dashboardApi.getStats();
      setStats(data);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadStats();
  }, [loadStats]);

  const s = stats;

  const columns: ColumnsType<Conversation> = [
    {
      title: '客户',
      key: 'customer',
      ellipsis: true,
      render: (_, record) => <Text strong>{formatCustomerName(record)}</Text>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 110,
      render: (st: Conversation['status']) => statusTag(st),
    },
    {
      title: '更新',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 160,
      render: (iso: string) => dayjs(iso).format('MM-DD HH:mm'),
    },
  ];

  return (
    <Spin spinning={loading}>
      <div style={{ maxWidth: 1100 }}>
        <Title level={4} style={{ marginTop: 0, marginBottom: 4 }}>
          工作台
        </Title>
        <Text type="secondary" style={{ display: 'block', marginBottom: 20 }}>
          数据概览
        </Text>

        <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
          <Col xs={12} sm={6}>
            <Card size="small" bordered={false} style={{ borderRadius: 8 }}>
              <Statistic title="总对话" value={s?.total_conversations ?? 0} />
            </Card>
          </Col>
          <Col xs={12} sm={6}>
            <Card size="small" bordered={false} style={{ borderRadius: 8 }}>
              <Statistic
                title="待人工"
                value={s?.pending_human ?? 0}
                valueStyle={{ color: (s?.pending_human ?? 0) > 0 ? '#fa8c16' : undefined }}
              />
            </Card>
          </Col>
          <Col xs={12} sm={6}>
            <Card size="small" bordered={false} style={{ borderRadius: 8 }}>
              <Statistic title="合同" value={s?.total_contracts ?? 0} />
            </Card>
          </Col>
          <Col xs={12} sm={6}>
            <Card size="small" bordered={false} style={{ borderRadius: 8 }}>
              <Statistic
                title="Bot 在线"
                value={`${s?.active_bots ?? 0}/${s?.total_bots ?? 0}`}
              />
            </Card>
          </Col>
        </Row>

        <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
          知识 {s?.total_knowledge_entries ?? 0} · 文件 {s?.total_files ?? 0} · 消息{' '}
          {s?.total_messages ?? 0}
        </Text>

        <Card
          size="small"
          title={
            <span>
              <MessageOutlined style={{ marginRight: 8 }} />
              最近对话
            </span>
          }
          bordered={false}
          style={{ borderRadius: 8 }}
        >
          <Table<Conversation>
            rowKey="id"
            columns={columns}
            dataSource={s?.recent_conversations ?? []}
            pagination={false}
            size="small"
            locale={{ emptyText: '暂无对话' }}
            onRow={(record) => ({
              onClick: () => navigate(`/conversations/${record.id}`),
              style: { cursor: 'pointer' },
            })}
          />
        </Card>
      </div>
    </Spin>
  );
}
