import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Card,
  Form,
  Input,
  Button,
  Typography,
  message,
  Space,
  theme,
} from 'antd';
import { UserOutlined, LockOutlined, RobotOutlined } from '@ant-design/icons';
import { authApi } from '../api';
import type { AxiosError } from 'axios';

const { Title, Text } = Typography;

type LoginForm = {
  username: string;
  password: string;
};

export default function Login() {
  const navigate = useNavigate();
  const { token } = theme.useToken();
  const [loading, setLoading] = useState(false);

  const onFinish = async (values: LoginForm) => {
    setLoading(true);
    try {
      const { data } = await authApi.login(values.username, values.password);
      localStorage.setItem('token', data.access_token);
      message.success('登录成功');
      navigate('/', { replace: true });
    } catch (err) {
      const ax = err as AxiosError<{ detail?: string; message?: string }>;
      const detail =
        ax.response?.data?.detail ??
        ax.response?.data?.message ??
        ax.message ??
        '登录失败，请检查您的凭据。';
      message.error(typeof detail === 'string' ? detail : '登录失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '24px 16px',
        background:
          'linear-gradient(135deg, #229ED9 0%, #5B4FCF 45%, #7C3AED 100%)',
        boxSizing: 'border-box',
      }}
    >
      <Card
        style={{
          width: '100%',
          maxWidth: 420,
          borderRadius: 16,
          boxShadow: '0 24px 48px rgba(15, 23, 42, 0.25)',
          border: 'none',
        }}
        styles={{ body: { padding: '40px 32px 36px' } }}
      >
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          <div style={{ textAlign: 'center' }}>
            <RobotOutlined
              style={{
                fontSize: 48,
                color: token.colorPrimary,
                marginBottom: 8,
                display: 'block',
              }}
            />
            <Title level={3} style={{ margin: 0, marginBottom: 4 }}>
              Telegram 智能客服
            </Title>
            <Text type="secondary">管理后台 — 请登录以继续</Text>
          </div>

          <Form<LoginForm>
            layout="vertical"
            requiredMark={false}
            onFinish={onFinish}
            size="large"
            autoComplete="off"
          >
            <Form.Item
              name="username"
              label="用户名"
              rules={[{ required: true, message: '请输入用户名' }]}
            >
              <Input
                prefix={<UserOutlined style={{ color: token.colorTextTertiary }} />}
                placeholder="用户名"
                autoComplete="username"
              />
            </Form.Item>
            <Form.Item
              name="password"
              label="密码"
              rules={[{ required: true, message: '请输入密码' }]}
            >
              <Input.Password
                prefix={<LockOutlined style={{ color: token.colorTextTertiary }} />}
                placeholder="密码"
                autoComplete="current-password"
              />
            </Form.Item>
            <Form.Item style={{ marginBottom: 0, marginTop: 8 }}>
              <Button type="primary" htmlType="submit" block loading={loading}>
                登 录
              </Button>
            </Form.Item>
          </Form>
        </Space>
      </Card>
    </div>
  );
}
