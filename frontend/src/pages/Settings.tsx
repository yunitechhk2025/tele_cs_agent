import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  Divider,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Slider,
  Space,
  Spin,
  Typography,
  message,
} from 'antd';
import {
  ApiOutlined,
  SaveOutlined,
  SettingOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { settingsApi } from '../api';
import type { LLMSettings } from '../types';

const { Title, Text } = Typography;

const PROVIDER_OPTIONS = [
  { value: 'openai', label: 'OpenAI' },
  { value: 'anthropic', label: 'Anthropic Claude' },
  { value: 'google', label: 'Google Gemini' },
  { value: 'qwen', label: '通义千问 (Qwen)' },
  { value: 'custom', label: '自定义（OpenAI 兼容）' },
] as const;

const BASE_URL_HINTS: Record<string, string> = {
  openai: 'https://api.openai.com/v1',
  anthropic: 'https://api.anthropic.com',
  google: 'https://generativelanguage.googleapis.com/v1beta/openai',
  qwen: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  custom: '输入你的 OpenAI 兼容 API 端点',
};

const MODEL_PLACEHOLDERS: Record<string, string> = {
  openai: 'gpt-4o, gpt-4o-mini, gpt-3.5-turbo',
  anthropic: 'claude-sonnet-4-20250514, claude-3-haiku-20240307',
  google: 'gemini-2.0-flash, gemini-1.5-pro',
  qwen: 'qwen-max, qwen-plus, qwen-turbo, qwen-long',
  custom: '你的模型名称',
};

function buildLLMPayload(values: LLMSettings): Partial<LLMSettings> {
  const payload: Partial<LLMSettings> = {
    provider: values.provider,
    base_url: values.base_url,
    model: values.model,
    embedding_model: values.embedding_model,
    embedding_base_url: values.embedding_base_url,
    image_model: values.image_model,
    image_base_url: values.image_base_url,
    image_size: values.image_size,
    image_quality: values.image_quality,
    image_style: values.image_style,
    temperature: values.temperature,
    max_tokens: values.max_tokens,
  };
  if (values.api_key && !values.api_key.includes('****')) {
    payload.api_key = values.api_key;
  }
  if (values.embedding_api_key && !values.embedding_api_key.includes('****')) {
    payload.embedding_api_key = values.embedding_api_key;
  }
  if (values.image_api_key && !values.image_api_key.includes('****')) {
    payload.image_api_key = values.image_api_key;
  }
  return payload;
}

export default function Settings() {
  const [form] = Form.useForm<LLMSettings>();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{
    open: boolean;
    ok: boolean;
    text: string;
  }>({ open: false, ok: false, text: '' });

  const provider = Form.useWatch('provider', form) as string | undefined;
  const temperature = Form.useWatch('temperature', form) as number | undefined;

  const baseUrlHint = useMemo(
    () => (provider ? BASE_URL_HINTS[provider] ?? BASE_URL_HINTS.custom : ''),
    [provider],
  );

  const modelPlaceholder = useMemo(
    () => (provider ? MODEL_PLACEHOLDERS[provider] ?? MODEL_PLACEHOLDERS.custom : ''),
    [provider],
  );

  const loadSettings = useCallback(async () => {
    setLoading(true);
    try {
      const res = await settingsApi.getLLM();
      form.setFieldsValue(res.data);
    } catch {
      message.error('加载 LLM 设置失败');
    } finally {
      setLoading(false);
    }
  }, [form]);

  useEffect(() => {
    void loadSettings();
  }, [loadSettings]);

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      await settingsApi.updateLLM(buildLLMPayload(values));
      message.success('设置已保存');
      await loadSettings();
    } catch (e) {
      if (e && typeof e === 'object' && 'errorFields' in e) return;
      message.error('保存设置失败');
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    try {
      const values = await form.validateFields();
      setTesting(true);
      const res = await settingsApi.testLLM(buildLLMPayload(values));
      const { ok, message: msg } = res.data;
      setTestResult({ open: true, ok, text: msg });
    } catch (e) {
      if (e && typeof e === 'object' && 'errorFields' in e) return;
      message.error('连接测试失败');
    } finally {
      setTesting(false);
    }
  };

  return (
    <div style={{ maxWidth: 960, margin: '0 auto' }}>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <Space align="center" size="middle">
          <SettingOutlined style={{ fontSize: 28, color: '#1677ff' }} />
          <Title level={2} style={{ margin: 0 }}>
            系统设置
          </Title>
        </Space>

        <Alert
          type="info"
          showIcon
          message="服务器返回的 API 密钥可能已脱敏显示。保持不变即可保留已存储的密钥，输入新密钥将替换原有密钥。"
        />

        <Spin spinning={loading}>
          <Card
            title={
              <Space>
                <ApiOutlined />
                <span>大模型（LLM）配置</span>
              </Space>
            }
            styles={{ body: { paddingTop: 24 } }}
          >
            <Form<LLMSettings>
              form={form}
              layout="horizontal"
              labelCol={{ span: 6 }}
              wrapperCol={{ span: 14 }}
              disabled={loading}
              initialValues={{
                provider: 'openai',
                temperature: 0.7,
                max_tokens: 2048,
              }}
            >
              <Form.Item
                label="服务商"
                name="provider"
                rules={[{ required: true, message: '请选择服务商' }]}
              >
                <Select options={[...PROVIDER_OPTIONS]} placeholder="选择服务商" />
              </Form.Item>

              <Form.Item
                label="API 密钥"
                name="api_key"
                rules={[{ required: true, message: 'API 密钥为必填项' }]}
              >
                <Input.Password placeholder="sk-..." autoComplete="off" />
              </Form.Item>

              <Form.Item
                label="接口地址"
                name="base_url"
                extra={
                  provider === 'anthropic' ? (
                    <Text type="secondary">
                      仅供参考 — Anthropic 集成不使用此字段。
                      建议值：{BASE_URL_HINTS.anthropic}
                    </Text>
                  ) : (
                    <Text type="secondary">提示：{baseUrlHint}</Text>
                  )
                }
              >
                <Input placeholder={baseUrlHint} />
              </Form.Item>

              <Form.Item
                label="模型名称"
                name="model"
                rules={[{ required: true, message: '模型名称为必填项' }]}
              >
                <Input placeholder={modelPlaceholder} />
              </Form.Item>

              <Divider orientation="left" plain>
                向量嵌入设置
              </Divider>

              <Form.Item label="嵌入模型" name="embedding_model">
                <Input placeholder="text-embedding-3-small" />
              </Form.Item>

              <Form.Item
                label="嵌入接口地址"
                name="embedding_base_url"
                extra={
                  <Text type="secondary">
                    当嵌入模型使用与主模型不同的端点时设置此项。
                  </Text>
                }
              >
                <Input placeholder="https://..." />
              </Form.Item>

              <Form.Item label="嵌入 API 密钥" name="embedding_api_key">
                <Input.Password
                  placeholder="可选 — 仅在与主 API 密钥不同时填写"
                  autoComplete="off"
                />
              </Form.Item>

              <Divider orientation="left" plain>
                生成设置
              </Divider>

              <Form.Item label="生图模型" name="image_model">
                <Input placeholder="gpt-image-1 / qwen-image / 你的图片模型名" />
              </Form.Item>

              <Form.Item
                label="生图接口地址"
                name="image_base_url"
                extra={
                  <Text type="secondary">
                    默认可与主模型接口一致；如图片能力走单独端点，请在此填写。
                  </Text>
                }
              >
                <Input placeholder="https://..." />
              </Form.Item>

              <Form.Item label="生图 API 密钥" name="image_api_key">
                <Input.Password
                  placeholder="可选 — 不填则复用主 API 密钥"
                  autoComplete="off"
                />
              </Form.Item>

              <Form.Item label="图片尺寸" name="image_size">
                <Select
                  options={[
                    { value: '1024x1024', label: '1024 x 1024' },
                    { value: '1536x1024', label: '1536 x 1024' },
                    { value: '1024x1536', label: '1024 x 1536' },
                  ]}
                />
              </Form.Item>

              <Form.Item label="图片质量" name="image_quality">
                <Select
                  options={[
                    { value: 'high', label: 'High' },
                    { value: 'medium', label: 'Medium' },
                    { value: 'low', label: 'Low' },
                  ]}
                />
              </Form.Item>

              <Form.Item label="图片风格" name="image_style">
                <Select
                  options={[
                    { value: 'natural', label: 'Natural' },
                    { value: 'vivid', label: 'Vivid' },
                  ]}
                />
              </Form.Item>

              <Form.Item
                label="温度"
                name="temperature"
                rules={[{ required: true, message: '请设置温度值' }]}
              >
                <Row gutter={16} align="middle" wrap={false}>
                  <Col flex="auto">
                    <Slider min={0} max={1} step={0.1} tooltip={{ formatter: (v) => `${v}` }} />
                  </Col>
                  <Col flex="none">
                    <Text strong style={{ minWidth: 36, display: 'inline-block' }}>
                      {temperature !== undefined && temperature !== null
                        ? Number(temperature).toFixed(1)
                        : '—'}
                    </Text>
                  </Col>
                </Row>
              </Form.Item>

              <Form.Item
                label="最大令牌数"
                name="max_tokens"
                rules={[{ required: true, message: '请设置最大令牌数' }]}
              >
                <InputNumber min={100} max={8000} style={{ width: '100%', maxWidth: 320 }} />
              </Form.Item>

              <Form.Item wrapperCol={{ offset: 6, span: 14 }} style={{ marginBottom: 0 }}>
                <Space size="middle" wrap>
                  <Button
                    icon={<ThunderboltOutlined />}
                    onClick={() => void handleTest()}
                    loading={testing}
                    disabled={loading}
                  >
                    测试连接
                  </Button>
                  <Button
                    type="primary"
                    icon={<SaveOutlined />}
                    onClick={() => void handleSave()}
                    loading={saving}
                    disabled={loading}
                  >
                    保存设置
                  </Button>
                </Space>
              </Form.Item>
            </Form>
          </Card>
        </Spin>
      </Space>

      <Modal
        title={testResult.ok ? '连接成功' : '连接测试'}
        open={testResult.open}
        onCancel={() => setTestResult((s) => ({ ...s, open: false }))}
        footer={[
          <Button key="close" type="primary" onClick={() => setTestResult((s) => ({ ...s, open: false }))}>
            确定
          </Button>,
        ]}
      >
        <Alert type={testResult.ok ? 'success' : 'error'} message={testResult.text} showIcon />
      </Modal>
    </div>
  );
}
