import { useEffect, useState } from 'react';
import {
  Modal, Tabs, Tag, Button, Alert, Spin, Space, Typography, message, theme, Divider,
} from 'antd';
import {
  ThunderboltOutlined, EditOutlined, CheckOutlined, WarningOutlined, FileSearchOutlined,
} from '@ant-design/icons';
import ReactDiffViewer from 'react-diff-viewer-continued';
import { useNavigate } from 'react-router-dom';
import { ssePost } from '../utils/sseClient';
import api, { chapterApi } from '../services/api';
import { useThemeMode } from '../theme/useThemeMode';

const { Text } = Typography;

export interface ReviewProblem {
  type: string;
  description: string;
  suggestion: string;
  level: 'minor' | 'major';
  step?: string;
}
export interface ChapterReport {
  chapter_id: string;
  chapter_number: number;
  title: string;
  problems: ReviewProblem[];
  major: boolean;
  rounds: number;
  errors?: string[];
}
export interface VolumeReviewResult {
  outline_id: string;
  outline_title: string;
  chapters: ChapterReport[];
  volume_issues: ReviewProblem[];
}

const LEVEL_COLORS: Record<string, string> = { minor: 'blue', major: 'red' };

interface Props {
  open: boolean;
  onClose: () => void;
  projectId: string;
  outlineId: string;
  outlineTitle: string;
}

/** 卷检查结果弹窗：每章一个选项卡，问题按类型分组，支持单条/合并 AI 修改（diff 确认） */
export default function VolumeReviewModal({ open, onClose, projectId, outlineId, outlineTitle }: Props) {
  const { token } = theme.useToken();
  const { resolvedMode } = useThemeMode();
  const navigate = useNavigate();
  const [status, setStatus] = useState<'idle' | 'running' | 'done' | 'error'>('idle');
  const [progress, setProgress] = useState('');
  const [result, setResult] = useState<VolumeReviewResult | null>(null);
  const [applying, setApplying] = useState(false);
  const [diff, setDiff] = useState<{ visible: boolean; original: string; generated: string; chapterId: string } | null>(null);
  const [diffTitle, setDiffTitle] = useState('');

  useEffect(() => {
    if (!open || !outlineId) return;
    let cancelled = false;
    (async () => {
      setStatus('running');
      setResult(null);
      setProgress('提交任务...');
      try {
        const r = (await api.post(`/chapters/project/${projectId}/volume-review`, { outline_id: outlineId })) as { task_id: string };
        // 轮询任务（后台逐章审查 + 跨章检查，视章数 1-10 分钟）
        for (;;) {
          await new Promise(res => setTimeout(res, 6000));
          if (cancelled) return;
          const t = (await api.get(`/tasks/${r.task_id}`)) as { status: string; progress_message?: string; task_result?: VolumeReviewResult };
          if (t.status === 'completed') {
            setResult(t.task_result || null);
            setStatus('done');
            return;
          }
          if (t.status === 'failed' || t.status === 'cancelled') {
            setStatus('error');
            setProgress(t.progress_message || t.status);
            return;
          }
          setProgress(t.progress_message || '');
        }
      } catch (e) {
        if (!cancelled) {
          setStatus('error');
          setProgress(e instanceof Error ? e.message : String(e));
        }
      }
    })();
    return () => { cancelled = true; };
  }, [open, outlineId, projectId]);

  const buildInstruction = (problems: ReviewProblem[]) =>
    problems
      .map(p => `【${p.type}${p.level === 'major' ? '/需重写' : ''}】${p.description}${p.suggestion ? `\n建议：${p.suggestion}` : ''}`)
      .join('\n');

  /** 单条或合并 AI 修改：流式修改 → diff 确认 → 应用 */
  const runAiEdit = async (chapter: ChapterReport, problems: ReviewProblem[], label: string) => {
    const instruction = buildInstruction(problems);
    setApplying(true);
    try {
      const ch = (await chapterApi.getChapter(chapter.chapter_id)) as { content?: string };
      const original = ch.content || '';
      let acc = '';
      await ssePost(
        `/api/chapters/${chapter.chapter_id}/ai-edit-stream`,
        { instruction },
        {
          onChunk: (content: string) => { acc += content; },
          onResult: () => {
            setDiffTitle(`${label}（第${chapter.chapter_number}章《${chapter.title}》）`);
            setDiff({ visible: true, original, generated: acc, chapterId: chapter.chapter_id });
          },
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
    if (!diff) return;
    setApplying(true);
    try {
      await chapterApi.updateChapter(diff.chapterId, { content: diff.generated });
      message.success('修改已应用到章节正文');
      setDiff({ ...diff, visible: false });
    } catch (e) {
      message.error(`应用失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setApplying(false);
    }
  };

  const goEdit = () => {
    message.info('已跳转到章节列表，点击对应章节即可编辑');
    navigate(`/project/${projectId}/chapters`);
    onClose();
  };

  const totalProblems = (result?.chapters || []).reduce((n, c) => n + (c.problems?.length || 0), 0);
  const volumeIssues = result?.volume_issues || [];

  const renderProblem = (p: ReviewProblem, chapter: ChapterReport) => (
    <div
      key={`${p.type}-${p.description.slice(0, 30)}-${Math.random()}`}
      style={{
        padding: '10px 12px',
        marginBottom: 8,
        borderRadius: 8,
        border: `1px solid ${token.colorBorderSecondary}`,
        background: token.colorBgContainer,
      }}
    >
      <Space wrap size={6} style={{ marginBottom: 4 }}>
        <Tag color={LEVEL_COLORS[p.level] || 'default'}>{p.level === 'major' ? '🔴 需重写' : '🟡 小问题'}</Tag>
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
        <Button size="small" icon={<ThunderboltOutlined />} loading={applying} onClick={() => runAiEdit(chapter, [p], '按建议修改')}>
          🤖 AI 根据建议修改
        </Button>
        <Button size="small" icon={<EditOutlined />} onClick={() => goEdit()}>
          ✏️ 去章节编辑
        </Button>
      </Space>
    </div>
  );

  const renderChapterTab = (chapter: ChapterReport) => {
    if (!chapter.problems || chapter.problems.length === 0) {
      return <Alert type="success" showIcon message="✅ 本章未发现问题" style={{ marginTop: 12 }} />;
    }
    // 按类型分组（保持顺序），同类型可一键合并
    const groups = new Map<string, ReviewProblem[]>();
    for (const p of chapter.problems) {
      const list = groups.get(p.type) || [];
      list.push(p);
      groups.set(p.type, list);
    }
    const groupEntries = Array.from(groups.entries());
    return (
      <div style={{ marginTop: 12 }}>
        <Alert
          type={chapter.major ? 'warning' : 'info'}
          showIcon
          icon={<WarningOutlined />}
          message={`本章共 ${chapter.problems.length} 个问题${chapter.major ? '（含需重写的结构级问题）' : ''}${chapter.rounds ? `，审查 ${chapter.rounds} 轮` : ''}`}
          style={{ marginBottom: 12 }}
        />
        {groupEntries.map(([type, problems]) => (
          <div key={type} style={{ marginBottom: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <Text strong>{type}（{problems.length}）</Text>
              {problems.length > 1 && (
                <Button
                  size="small"
                  type="primary"
                  ghost
                  icon={<ThunderboltOutlined />}
                  loading={applying}
                  onClick={() => runAiEdit(chapter, problems, `合并修改 ${type} ${problems.length} 处`)}
                >
                  一键合并修改 {problems.length} 处
                </Button>
              )}
            </div>
            {problems.map(p => renderProblem(p, chapter))}
          </div>
        ))}
      </div>
    );
  };

  const items = [
    ...(result?.chapters || []).map(c => ({
      key: String(c.chapter_number),
      label: `第${c.chapter_number}章${c.problems?.length ? `（${c.problems.length}）` : ''}`,
      children: renderChapterTab(c),
    })),
    ...(volumeIssues.length > 0
      ? [{
          key: '__volume__',
          label: `📎 跨章问题（${volumeIssues.length}）`,
          children: (
            <div style={{ marginTop: 12 }}>
              <Alert type="warning" showIcon message="跨章逻辑问题（时间线/人物行为/资源/伤势/战力/伏笔等），建议优先处理" style={{ marginBottom: 12 }} />
              {volumeIssues.map((p, i) => (
                <div
                  key={`vol-${i}`}
                  style={{
                    padding: '10px 12px', marginBottom: 8, borderRadius: 8,
                    border: `1px solid ${token.colorBorderSecondary}`,
                  }}
                >
                  <Space wrap size={6} style={{ marginBottom: 4 }}>
                    <Tag color={LEVEL_COLORS[p.level] || 'default'}>{p.level === 'major' ? '🔴 需重写' : '🟡 小问题'}</Tag>
                    <Tag color="purple">跨章</Tag>
                    <Tag>{p.type}</Tag>
                  </Space>
                  <div style={{ marginBottom: 6 }}>{p.description}</div>
                  {p.suggestion && <div style={{ color: token.colorTextSecondary, fontSize: 13 }}>💡 {p.suggestion}</div>}
                </div>
              ))}
            </div>
          ),
        }]
      : []),
  ];

  return (
    <Modal
      title={`🔍 卷检查：${outlineTitle}`}
      open={open}
      onCancel={onClose}
      footer={
        status === 'done' ? [
          <Button key="close" onClick={onClose}>关闭</Button>,
        ] : null
      }
      width="88%"
      centered
      styles={{ body: { maxHeight: '75vh', overflowY: 'auto', padding: 16 } }}
    >
      {status === 'running' && (
        <div style={{ textAlign: 'center', padding: '48px 0' }}>
          <Spin size="large" />
          <div style={{ marginTop: 16, color: token.colorTextSecondary }}>
            <FileSearchOutlined /> {progress || '审查进行中（每章约 1-2 分钟）...'}
          </div>
        </div>
      )}
      {status === 'error' && (
        <Alert type="error" showIcon message="卷检查失败" description={progress} action={<Button size="small" onClick={onClose}>关闭</Button>} />
      )}
      {status === 'done' && result && (
        <>
          <Alert
            type="success"
            showIcon
            message={`检查完成：${result.chapters.length} 章，共 ${totalProblems} 个问题${volumeIssues.length ? `，跨章问题 ${volumeIssues.length} 个` : ''}`}
            style={{ marginBottom: 12 }}
          />
          <Divider style={{ margin: '0 0 12px' }} />
          <Tabs items={items} size="small" />

          {/* diff 确认弹窗 */}
          <Modal
            title={`🤖 ${diffTitle}`}
            open={diff?.visible}
            width="92%"
            centered
            onCancel={() => setDiff(diff ? { ...diff, visible: false } : null)}
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
        </>
      )}
    </Modal>
  );
}
