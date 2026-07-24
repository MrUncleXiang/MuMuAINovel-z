import { useEffect, useState } from 'react';
import { Card, Col, Row, Select, Space, Statistic, Table, Tag, Typography } from 'antd';
import { useParams } from 'react-router-dom';
import dayjs from 'dayjs';
import { aiProviderApi } from '../services/api';
import type { AICallLog } from '../types';

const { Title, Text } = Typography;
const usageLabels: Record<string, string> = {
  chapter_write: '章节写作', chapter_analysis: '章节分析', outline: '大纲', polish: '润色', default: '其他',
};

export default function AIUsageLogs() {
  const { projectId } = useParams<{ projectId: string }>();
  const [rows, setRows] = useState<AICallLog[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [usageType, setUsageType] = useState<string>();
  const [summary, setSummary] = useState<{ total_calls: number; success_calls: number; failed_calls: number; total_tokens: number; average_duration_ms?: number }>({ total_calls: 0, success_calls: 0, failed_calls: 0, total_tokens: 0 });

  const load = async () => {
    setLoading(true);
    try {
      const [logs, stats] = await Promise.all([
        aiProviderApi.logs({ project_id: projectId, usage_type: usageType, limit: 100 }),
        aiProviderApi.summary(projectId),
      ]);
      setRows(logs.items); setTotal(logs.total); setSummary(stats);
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [projectId, usageType]);

  return <Space direction="vertical" size="large" style={{ width: '100%' }}>
    <div><Title level={3}>AI 使用记录</Title><Text type="secondary">记录真实调用的供应商、模型、Token、耗时和错误，不记录 API Key 与小说正文。</Text></div>
    <Row gutter={[12, 12]}>
      <Col xs={12} md={6}><Card><Statistic title="调用次数" value={summary.total_calls} /></Card></Col>
      <Col xs={12} md={6}><Card><Statistic title="成功" value={summary.success_calls} /></Card></Col>
      <Col xs={12} md={6}><Card><Statistic title="失败" value={summary.failed_calls} /></Card></Col>
      <Col xs={12} md={6}><Card><Statistic title="总 Token" value={summary.total_tokens} /></Card></Col>
    </Row>
    <Card title={`调用明细（${total}）`} extra={<Select allowClear placeholder="按任务筛选" style={{ width: 150 }} value={usageType} onChange={setUsageType} options={Object.entries(usageLabels).map(([value,label]) => ({value,label}))} />}>
      <Table rowKey="request_id" loading={loading} dataSource={rows} pagination={{ pageSize: 20 }} scroll={{ x: 900 }} columns={[
        { title: '时间', dataIndex: 'created_at', width: 170, render: value => dayjs(value).format('YYYY-MM-DD HH:mm:ss') },
        { title: '任务', dataIndex: 'usage_type', width: 110, render: value => usageLabels[value] || value },
        { title: 'AI 服务', dataIndex: 'provider_name', width: 180, render: value => value || '旧版默认配置' },
        { title: '模型', dataIndex: 'actual_model', width: 190 },
        { title: '结果', dataIndex: 'status', width: 80, render: value => <Tag color={value === 'success' ? 'success' : 'error'}>{value === 'success' ? '成功' : '失败'}</Tag> },
        { title: 'Token', dataIndex: 'total_tokens', width: 100, render: value => value ?? '-' },
        { title: '耗时', dataIndex: 'duration_ms', width: 100, render: value => value == null ? '-' : `${(value / 1000).toFixed(1)}秒` },
        { title: '错误', dataIndex: 'error_message', ellipsis: true },
      ]} />
    </Card>
  </Space>;
}
