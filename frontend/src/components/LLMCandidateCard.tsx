import { Button, Card, Descriptions, Empty, Space, Tag, Typography } from 'antd';
import type { LLMComparisonCandidate } from '../types';

const { Paragraph, Text } = Typography;

interface Props {
  candidate: LLMComparisonCandidate;
  adopted?: boolean;
  onRetry?: (candidate: LLMComparisonCandidate) => void;
  onAdopt?: (candidate: LLMComparisonCandidate) => void;
  actionsDisabled?: boolean;
}

const statusLabels: Record<LLMComparisonCandidate['status'], { color: string; text: string }> = {
  pending: { color: 'default', text: '等待中' },
  running: { color: 'processing', text: '生成中' },
  success: { color: 'success', text: '已完成' },
  failed: { color: 'error', text: '生成失败' },
};

/** 可在章节、大纲和分析页面复用的候选结果卡片。 */
export default function LLMCandidateCard({ candidate, adopted, onRetry, onAdopt, actionsDisabled }: Props) {
  const status = statusLabels[candidate.status];
  return (
    <Card
      title={<Space wrap><Text strong>{candidate.provider_name}</Text><Tag>{candidate.model}</Tag></Space>}
      extra={<Space><Tag color={status.color}>{status.text}</Tag>{adopted && <Tag color="blue">已采用</Tag>}</Space>}
      actions={[
        candidate.status === 'failed' ? (
          <Button type="link" disabled={actionsDisabled} onClick={() => onRetry?.(candidate)}>重试</Button>
        ) : null,
        candidate.status === 'success' && !adopted ? (
          <Button type="link" disabled={actionsDisabled} onClick={() => onAdopt?.(candidate)}>采用此版本</Button>
        ) : null,
      ].filter(Boolean)}
    >
      <Descriptions size="small" column={2}>
        <Descriptions.Item label="耗时">{candidate.duration_ms ? `${(candidate.duration_ms / 1000).toFixed(1)} 秒` : '-'}</Descriptions.Item>
        <Descriptions.Item label="Token">{candidate.total_tokens ?? '-'}</Descriptions.Item>
      </Descriptions>
      {candidate.status === 'failed' ? (
        <Paragraph type="danger">{candidate.error_message || '生成失败，可单独重试这个模型。'}</Paragraph>
      ) : candidate.output_text ? (
        <Paragraph style={{ whiteSpace: 'pre-wrap' }} ellipsis={{ rows: 12, expandable: true, symbol: '展开全文' }}>
          {candidate.output_text}
        </Paragraph>
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={candidate.status === 'running' ? '正在生成…' : '暂无结果'} />
      )}
    </Card>
  );
}
