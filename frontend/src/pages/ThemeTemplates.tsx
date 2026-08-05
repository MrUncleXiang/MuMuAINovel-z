import { useCallback, useEffect, useState } from 'react';
import {
  Button, Card, Form, Input, List, Modal, Popconfirm, Select, Space, Tag, Typography, message,
} from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { themeTemplateApi } from '../services/api';
import type { ThemeTemplate } from '../types';

const { Title, Paragraph, Text } = Typography;

export default function ThemeTemplates() {
  const [templates, setTemplates] = useState<ThemeTemplate[]>([]);
  const [analyzeOpen, setAnalyzeOpen] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [draft, setDraft] = useState<Partial<ThemeTemplate> | null>(null);
  const [form] = Form.useForm();

  const refresh = useCallback(async () => {
    try {
      const list = await themeTemplateApi.list();
      setTemplates(list);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const handleAnalyze = async () => {
    const v = await form.validateFields();
    setAnalyzing(true);
    try {
      const t = await themeTemplateApi.analyze({ examples: v.examples, genre_hint: v.genre_hint });
      setDraft(t);
      message.success('分析完成，请确认模板内容');
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '分析失败');
    } finally {
      setAnalyzing(false);
    }
  };

  const handleSave = async () => {
    if (!draft) return;
    try {
      await themeTemplateApi.create(draft as ThemeTemplate);
      message.success('模板已保存');
      setAnalyzeOpen(false);
      setDraft(null);
      form.resetFields();
      refresh();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '保存失败');
    }
  };

  return (
    <div style={{ padding: 24, maxWidth: 900 }}>
      <Space style={{ width: '100%', justifyContent: 'space-between' }}>
        <Title level={3} style={{ marginBottom: 8 }}>题材模板库</Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setAnalyzeOpen(true)}>
          从示例提炼模板
        </Button>
      </Space>
      <Paragraph type="secondary">
        给几个你喜欢的示例（书名/链接/简介），AI 提炼出热门题材模板；之后在创建小说时可以直接选用，一键开书。
      </Paragraph>

      <List
        grid={{ gutter: 16, column: 2 }}
        dataSource={templates}
        locale={{ emptyText: '还没有模板——点击右上角"从示例提炼模板"开始' }}
        renderItem={(t) => (
          <List.Item>
            <Card
              title={t.title}
              size="small"
              extra={
                <Popconfirm title="确定删除该模板？" onConfirm={async () => { await themeTemplateApi.remove(t.id); refresh(); }}>
                  <a style={{ color: '#ff4d4f' }}>删除</a>
                </Popconfirm>
              }
            >
              <Space wrap size={4}>
                <Tag color="blue">{t.genre || '通用'}</Tag>
                {(t.tags || []).map(tag => <Tag key={tag}>{tag}</Tag>)}
                <Tag>已用 {t.usage_count || 0} 次</Tag>
              </Space>
              <Paragraph style={{ marginTop: 8 }} type="secondary" ellipsis={{ rows: 2 }}>{t.description}</Paragraph>
              {t.world_formula && <Text type="secondary" ellipsis style={{ display: 'block' }}>设定：{t.world_formula}</Text>}
            </Card>
          </List.Item>
        )}
      />

      <Modal
        open={analyzeOpen}
        title="从示例提炼题材模板"
        onCancel={() => { setAnalyzeOpen(false); setDraft(null); }}
        onOk={handleSave}
        okText="保存模板"
        confirmLoading={analyzing}
        width={640}
      >
        {!draft ? (
          <Form form={form} layout="vertical">
            <Form.Item name="examples" label="示例（每行一个：书名 / 链接 / 简介）" rules={[{ required: true, message: '请至少填一个示例' }]}>
              <Input.TextArea rows={4} placeholder={'例如：\n赘婿流小说：主角入赘受辱后崛起\n龙王归来：隐藏身份的主角保护家人'} />
            </Form.Item>
            <Form.Item name="genre_hint" label="题材类型提示（可选）">
              <Select allowClear placeholder="如：都市 / 玄幻 / 悬疑" options={['都市','玄幻','悬疑','科幻','历史','游戏'].map(g => ({ value: g, label: g }))} />
            </Form.Item>
            <Button type="primary" onClick={handleAnalyze} loading={analyzing} block>开始分析</Button>
          </Form>
        ) : (
          <div>
            <Paragraph><Text strong>模板名：</Text>{draft.title}</Paragraph>
            <Paragraph><Text strong>类型：</Text>{draft.genre}　<Text strong>标签：</Text>{(draft.tags || []).join('、')}</Paragraph>
            <Paragraph><Text strong>描述：</Text>{draft.description}</Paragraph>
            <Paragraph><Text strong>世界观公式：</Text>{draft.world_formula}</Paragraph>
            <Paragraph><Text strong>角色原型：</Text></Paragraph>
            {(draft.character_prototypes || []).map((cp: any, i: number) => (
              <Paragraph key={i} style={{ marginLeft: 16 }} type="secondary">
                {cp.name}（{cp.role}）：{cp.traits}
              </Paragraph>
            ))}
            <Paragraph><Text strong>卷结构：</Text>{draft.volume_structure}</Paragraph>
          </div>
        )}
      </Modal>
    </div>
  );
}
