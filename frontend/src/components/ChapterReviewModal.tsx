import { useState } from 'react';
import { Modal, Tag, Button, Space, Alert, message, theme, Empty } from 'antd';
import { ThunderboltOutlined, CheckOutlined, EditOutlined } from '@ant-design/icons';
import ReactDiffViewer from 'react-diff-viewer-continued';
import { useNavigate } from 'react-router-dom';
import { ssePost } from '../utils/sseClient';
import { chapterApi } from '../services/api';
import { useThemeMode } from '../theme/useThemeMode';

export interface ReviewProblem {
  type: string;
  description: string;
  suggestion: string;
  level: 'minor' | 'major';
  step?: string;
}
export interface ChapterReviewRecord {
  chapter_id: string;
  chapter_number: number;
  problems: ReviewProblem[];
  major: boolean;
  rounds: number;
  source: string;
  created_at: string | null;
}

interface Props {
  record: ChapterReviewRecord | null; // null = 无记录（只读提示）
  chapterTitle?: string;
  projectId: string;
  onClose: () => void;
}

/** 章节审查报告弹窗：问题列表 + AI 根据建议修改（diff 确认） */
export default function ChapterReviewModal({ record, chapterTitle, projectId, onClose }: Props) {
  const { token } = theme.useToken();
  const { resolvedMode } = useThemeMode();
  const navigate = useNavigate();
  const [applying, setApplying] = useState(false);
  const [diff, setDiff] = useState<{ visible: boolean; original: string; generated: string } | null>(null);

  const runAiEdit = async (problems: ReviewProblem[]) => {
    if (!record) return;
    const instruction = problems
      .map(p => `【${p.type}${p.level === 'major' ? '/需重写' : ''}】${p.description}${p.suggestion ? `\n建议：${p.suggestion}` : ''}`)
      .join('\n');
    setApplying(true);
    try {
      const ch = (await chapterApi.getChapter(record.chapter_id)) as { content?: string };
      const original = ch.content || '';
      let acc = '';
      await ssePost(
        `/api/chapters/${record.chapter_id}/ai-edit-stream`,
        { instruction },
        {
          onChunk: (content: string) => { acc += content; },
          onResult: () => setDiff({ visible: true, original, generated: acc }),
          onError: (error: string) => message.error(`AI 修改失败：${error}`),
        },
      );
    } catch (e) {
      message.error(`AI 修改失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setApplying(false);
    }
  };

  const applyDiff = async () => {
    if (!diff || !record) return;
    setApplying(true);
    try {
      await chapterApi.updateChapter(record.chapter_id, { content: diff.generated });
      message.success('修改已应用到章节正文');
      setDiff({ ...diff, visible: false });
    } catch (e) {
      message.error(`应用失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setApplying(false);
    }
  };

  const goEdit = () => {
    if (!record) return;
    message.info('已跳转到章节列表，点击对应章节即可编辑');
    navigate(`/project/${projectId}/chapters`);
    onClose();
  };

  const problems = record?.problems || [];

  return (
    <Modal
      title={`🔍 审查报告：第${record?.chapter_number ?? ''}章${chapterTitle ? `《${chapterTitle}》` : ''}`}
      open={!!record}
      onCancel={onClose}
      footer={null}
      width="82%"
      centered
      styles={{ body: { maxHeight: '70vh', overflowY: 'auto', padding: 16 } }}
    >
      {!record && <Empty description="暂无审查记录（生成章节或运行卷检查后产生）" />}
      {record && (
        <>
          {problems.length === 0 ? (
            <Alert type="success" showIcon message="✅ 该次审查未发现问题" style={{ marginBottom: 12 }} />
          ) : (
            <>
              <Alert
                type={record.major ? 'warning' : 'info'}
                showIcon
                message={`共 ${problems.length} 个问题${record.major ? '（含需重写的结构级问题）' : ''}`}
                description={
                  <Space size={8} wrap>
                    <Tag color={record.source === 'volume' ? 'purple' : 'blue'}>
                      {record.source === 'volume' ? '卷检查' : '生成后自动审查'}
                    </Tag>
                    <Tag>审查 {record.rounds} 轮</Tag>
                    {record.created_at && <Tag>{record.created_at.replace('T', ' ').slice(0, 19)}</Tag>}
                  </Space>
                }
                style={{ marginBottom: 12 }}
              />
              {/* 一键全部修改 */}
              {problems.length > 1 && (
                <div style={{ marginBottom: 12, textAlign: 'right' }}>
                  <Button
                    type="primary"
                    ghost
                    icon={<ThunderboltOutlined />}
                    loading={applying}
                    onClick={() => runAiEdit(problems)}
                  >
                    一键合并修改全部 {problems.length} 处
                  </Button>
                </div>
              )}
              {problems.map((p, i) => (
                <div
                  key={i}
                  style={{
                    padding: '10px 12px', marginBottom: 8, borderRadius: 8,
                    border: `1px solid ${token.colorBorderSecondary}`,
                    background: token.colorBgContainer,
                  }}
                >
                  <Space wrap size={6} style={{ marginBottom: 4 }}>
                    <Tag color={p.level === 'major' ? 'red' : 'blue'}>
                      {p.level === 'major' ? '🔴 需重写' : '🟡 小问题'}
                    </Tag>
                    <Tag>{p.type}</Tag>
                    {p.step === 'continuity' && <Tag color="purple">跨章</Tag>}
                  </Space>
                  <div style={{ marginBottom: 6 }}>{p.description}</div>
                  {p.suggestion && (
                    <div style={{ color: token.colorTextSecondary, marginBottom: 8, fontSize: 13 }}>
                      💡 {p.suggestion}
                    </div>
                  )}
                  <Space size={8} wrap>
                    <Button size="small" icon={<ThunderboltOutlined />} loading={applying} onClick={() => runAiEdit([p])}>
                      🤖 AI 根据建议修改
                    </Button>
                    <Button size="small" icon={<EditOutlined />} onClick={goEdit}>
                      ✏️ 去章节编辑
                    </Button>
                  </Space>
                </div>
              ))}
            </>
          )}
        </>
      )}

      <Modal
        title="🤖 AI 修改对比"
        open={diff?.visible}
        width="92%"
        centered
        onCancel={() => setDiff(cur => (cur ? { ...cur, visible: false } : cur))}
        onOk={applyDiff}
        okText="应用修改"
        cancelText="关闭"
        okButtonProps={{ icon: <CheckOutlined />, loading: applying }}
        styles={{ body: { maxHeight: '70vh', overflowY: 'auto' } }}
      >
        <Alert type="info" showIcon message="红色=原文，绿色=修改后；其余内容应保持不变" style={{ marginBottom: 12 }} />
        {diff && (
          <ReactDiffViewer
            oldValue={diff.original}
            newValue={diff.generated}
            splitView={false}
            useDarkTheme={resolvedMode === 'dark'}
          />
        )}
      </Modal>
    </Modal>
  );
}
