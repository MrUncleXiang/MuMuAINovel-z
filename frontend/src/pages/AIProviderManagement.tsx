import { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Card, Col, Form, Input, InputNumber, Modal, Popconfirm, Row, Select, Space, Switch, Table, Tag, Typography, message } from 'antd';
import { DeleteOutlined, EditOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import { aiProviderApi } from '../services/api';
import type { AIProviderConfig, AIProviderConfigInput, AIUsageRoute } from '../types';

const { Title, Text } = Typography;
const TASKS = [
  ['chapter_write', '章节写作'], ['chapter_analysis', '章节分析'], ['outline', '大纲生成'],
  ['polish', '文本润色'], ['regeneration', '章节重写'], ['character', '角色生成'],
  ['world_building', '世界观生成'],
] as const;

const PRESETS: Record<string, Pick<ProviderForm, 'protocol' | 'wire_api' | 'base_url' | 'default_model' | 'models'>> = {
  openai: { protocol: 'openai', wire_api: 'chat_completions', base_url: 'https://api.openai.com/v1', default_model: 'gpt-4.1-mini', models: 'gpt-4.1-mini\ngpt-4.1' },
  opencode: { protocol: 'openai', wire_api: 'chat_completions', base_url: 'https://opencode.ai/zen/go/v1', default_model: '', models: '' },
  anthropic: { protocol: 'anthropic', wire_api: 'chat_completions', base_url: 'https://api.anthropic.com', default_model: 'claude-sonnet-4-20250514', models: 'claude-sonnet-4-20250514' },
  gemini: { protocol: 'gemini', wire_api: 'chat_completions', base_url: 'https://generativelanguage.googleapis.com/v1beta', default_model: 'gemini-2.5-flash', models: 'gemini-2.5-flash' },
};

type ProviderForm = Omit<AIProviderConfigInput, 'models'> & { models?: string };

export default function AIProviderManagement() {
  const [providers, setProviders] = useState<AIProviderConfig[]>([]);
  const [routes, setRoutes] = useState<AIUsageRoute[]>([]);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<AIProviderConfig | null>(null);
  const [open, setOpen] = useState(false);
  const [actionId, setActionId] = useState<string>();
  const [form] = Form.useForm<ProviderForm>();
  const selectedProtocol = Form.useWatch('protocol', form);

  const load = async () => {
    setLoading(true);
    try {
      const [providerRows, routeRows] = await Promise.all([aiProviderApi.list(), aiProviderApi.listRoutes()]);
      setProviders(providerRows); setRoutes(routeRows);
    } catch { message.error('加载 AI 服务配置失败'); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, []);

  const routeMap = useMemo(() => new Map(routes.map(item => [item.usage_type, item])), [routes]);
  const openCreate = () => {
    setEditing(null); form.resetFields();
    form.setFieldsValue({ protocol: 'openai', wire_api: 'chat_completions', enabled: true, is_default: providers.length === 0, sort_order: 0 });
    setOpen(true);
  };
  const openEdit = (row: AIProviderConfig) => {
    setEditing(row);
    form.setFieldsValue({ ...row, api_key: undefined, models: row.models.join('\n') });
    setOpen(true);
  };
  const applyPreset = (key: keyof typeof PRESETS) => form.setFieldsValue(PRESETS[key]);
  const save = async () => {
    const value = await form.validateFields();
    const payload: AIProviderConfigInput = {
      ...value,
      models: (value.models || '').split(/[\n,]/).map(v => v.trim()).filter(Boolean),
      api_key: value.api_key || undefined,
    };
    try {
      if (editing) await aiProviderApi.update(editing.id, payload); else await aiProviderApi.create(payload);
      message.success(editing ? 'AI 服务已更新' : 'AI 服务已添加'); setOpen(false); await load();
    } catch { message.error('保存失败，请检查名称、地址和必填项'); }
  };
  const saveRoute = async (usageType: string, providerId?: string, model?: string) => {
    try {
      await aiProviderApi.saveRoute(usageType, { provider_config_id: providerId || undefined, model: model || undefined });
      await load(); message.success('任务默认服务已保存');
    } catch { message.error('保存任务默认服务失败'); }
  };

  return <div style={{ padding: 24, maxWidth: 1200, margin: '0 auto' }}>
    <Space direction="vertical" size={18} style={{ width: '100%' }}>
      <Row justify="space-between" align="middle" gutter={[12, 12]}>
        <Col><Title level={3} style={{ margin: 0 }}>AI 服务管理</Title><Text type="secondary">像通讯录一样保存多个供应商；每次创作仍可临时换一个。</Text></Col>
        <Col><Space><Button icon={<ReloadOutlined />} onClick={() => void load()}>刷新</Button><Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>添加服务</Button></Space></Col>
      </Row>
      <Alert type="info" showIcon message="原来的 API 设置仍然保留" description="未添加服务时继续使用旧设置；添加后可指定全局默认，也可为写作、分析等任务分别设默认值。API Key 只保存在后端，页面不会回显完整内容。" />
      <Card title="已添加的服务">
        <Table rowKey="id" loading={loading} pagination={false} dataSource={providers} locale={{ emptyText: '尚未添加服务，可先添加 OpenAI、OpenCode Go 或兼容接口' }} columns={[
          { title: '名称', dataIndex: 'name', render: (v, r) => <Space>{v}{r.is_default && <Tag color="blue">全局默认</Tag>}{!r.enabled && <Tag>已停用</Tag>}</Space> },
          { title: '接口', render: (_, r) => <Tag>{r.protocol === 'openai' ? (r.wire_api === 'responses' ? 'OPENAI RESPONSES' : 'OPENAI CHAT') : r.protocol.toUpperCase()}</Tag> },
          { title: '默认模型', dataIndex: 'default_model', render: v => v || '未填写' },
          { title: '地址', dataIndex: 'base_url', ellipsis: true },
          { title: '密钥', render: (_, r) => r.api_key_hint || '未配置' },
          { title: '操作', render: (_, r) => <Space wrap><Button size="small" loading={actionId === `test-${r.id}`} onClick={async () => { setActionId(`test-${r.id}`); try { const result = await aiProviderApi.test(r.id); message.success(result.message); } catch { message.error('连接测试失败，请检查地址、密钥和模型'); } finally { setActionId(undefined); } }}>测试</Button><Button size="small" loading={actionId === `sync-${r.id}`} onClick={async () => { setActionId(`sync-${r.id}`); try { const result = await aiProviderApi.syncModels(r.id); message.success(`已同步 ${result.count} 个模型`); await load(); } catch { message.error('供应商不支持模型列表时，可在编辑中手工填写'); } finally { setActionId(undefined); } }}>同步模型</Button><Button size="small" icon={<EditOutlined />} onClick={() => openEdit(r)}>编辑</Button><Popconfirm title="确定删除这个服务？" onConfirm={async () => { await aiProviderApi.remove(r.id); await load(); }}><Button size="small" danger icon={<DeleteOutlined />}>删除</Button></Popconfirm></Space> },
        ]} />
      </Card>
      <Card title="不同任务默认用哪个服务" extra={<Text type="secondary">不选择时使用全局默认/旧 API 设置</Text>}>
        <Row gutter={[16, 16]}>{TASKS.map(([key, label]) => {
          const route = routeMap.get(key); const provider = providers.find(p => p.id === route?.provider_config_id);
          return <Col xs={24} md={12} key={key}><Card size="small" title={label}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <Select allowClear placeholder="跟随全局默认" value={route?.provider_config_id} style={{ width: '100%' }} options={providers.filter(p => p.enabled).map(p => ({ value: p.id, label: `${p.name}（${p.protocol}）` }))} onChange={id => void saveRoute(key, id, undefined)} />
              <Select allowClear showSearch placeholder="使用该服务的默认模型" value={route?.model} disabled={!provider} style={{ width: '100%' }} options={(provider?.models || []).map(m => ({ value: m, label: m }))} onChange={model => void saveRoute(key, route?.provider_config_id, model)} />
            </Space>
          </Card></Col>;
        })}</Row>
      </Card>
    </Space>

    <Modal title={editing ? '编辑 AI 服务' : '添加 AI 服务'} open={open} onCancel={() => setOpen(false)} onOk={() => void save()} okText="保存" width={720}>
      <Space wrap style={{ marginBottom: 16 }}><Text>快速模板：</Text><Button size="small" onClick={() => applyPreset('openai')}>OpenAI</Button><Button size="small" onClick={() => applyPreset('opencode')}>OpenCode Go</Button><Button size="small" onClick={() => applyPreset('anthropic')}>Anthropic</Button><Button size="small" onClick={() => applyPreset('gemini')}>Gemini</Button></Space>
      <Form form={form} layout="vertical">
        <Row gutter={16}><Col span={12}><Form.Item name="name" label="服务名称" rules={[{ required: true }]}><Input placeholder="例如：我的 OpenCode Go" /></Form.Item></Col><Col span={12}><Form.Item name="protocol" label="接口协议" rules={[{ required: true }]}><Select options={[{value:'openai',label:'OpenAI 兼容'},{value:'anthropic',label:'Anthropic'},{value:'gemini',label:'Gemini'}]} /></Form.Item></Col></Row>
        {selectedProtocol === 'openai' && <Form.Item name="wire_api" label="OpenAI 接口类型" rules={[{ required: true }]}><Select options={[{ value: 'chat_completions', label: 'Chat Completions（/chat/completions）' }, { value: 'responses', label: 'Responses（/responses）' }]} /></Form.Item>}
        <Form.Item name="base_url" label="接口地址（Base URL）" rules={[{ required: true }, { type: 'url' }]}><Input placeholder="https://.../v1" /></Form.Item>
        <Form.Item name="api_key" label={editing ? `API Key（留空则保留原密钥：${editing.api_key_hint || '未配置'}）` : 'API Key'}><Input.Password autoComplete="new-password" /></Form.Item>
        <Row gutter={16}><Col span={12}><Form.Item name="default_model" label="默认模型"><Input placeholder="模型 ID" /></Form.Item></Col><Col span={12}><Form.Item name="sort_order" label="排序"><InputNumber style={{ width: '100%' }} /></Form.Item></Col></Row>
        <Form.Item name="models" label="可选模型（每行一个，也可用逗号分隔）"><Input.TextArea rows={4} placeholder="model-a\nmodel-b" /></Form.Item>
        <Form.Item name="notes" label="备注"><Input.TextArea rows={2} /></Form.Item>
        <Space size="large"><Form.Item name="enabled" label="启用" valuePropName="checked"><Switch /></Form.Item><Form.Item name="is_default" label="设为全局默认" valuePropName="checked"><Switch /></Form.Item></Space>
      </Form>
    </Modal>
  </div>;
}
