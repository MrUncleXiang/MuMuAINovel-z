import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Alert, Button, Card, Col, Collapse, Descriptions, Divider, Empty, Form, InputNumber, Modal, Row,
  Select, Space, Steps, Switch, Tag, Typography, message,
} from 'antd';
import {
  CaretRightOutlined, CheckOutlined, FundOutlined, PauseOutlined, PlayCircleOutlined,
  ReloadOutlined, SettingOutlined, StopOutlined,
} from '@ant-design/icons';
import { aiProviderApi, pipelineApi } from '../services/api';
import type { AIProviderConfig, NovelPipeline, PipelineCheckpoint } from '../types';

const { Title, Text, Paragraph } = Typography;

const STAGE_LABELS: Record<string, string> = {
  idle: '未启动',
  book: '一键建书',
  chapter_loop: '章节循环',
  checkpoint: '检查点',
  volume_transition: '卷过渡',
  completed: '已完成',
};

const STATUS_MAP: Record<string, { color: string; label: string }> = {
  idle: { color: 'default', label: '未启动' },
  running: { color: 'processing', label: '运行中' },
  awaiting_review: { color: 'warning', label: '待审阅' },
  paused: { color: 'default', label: '已暂停' },
  completed: { color: 'success', label: '已完成' },
  stopped: { color: 'default', label: '已停止' },
  failed: { color: 'error', label: '失败' },
};

const POLL_INTERVAL = 5000;

export default function PipelinePanel() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const [pipeline, setPipeline] = useState<NovelPipeline | null>(null);
  const [checkpoints, setCheckpoints] = useState<PipelineCheckpoint[]>([]);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [rollbackTarget, setRollbackTarget] = useState<PipelineCheckpoint | null>(null);
  const [configOpen, setConfigOpen] = useState(false);
  const [configForm] = Form.useForm();
  const [providers, setProviders] = useState<AIProviderConfig[]>([]);

  useEffect(() => {
    aiProviderApi.list().then(setProviders).catch(() => undefined);
  }, []);

  const openConfig = () => {
    if (!pipeline) return;
    const c = pipeline.config_snapshot ?? {};
    configForm.setFieldsValue({
      milestone_chapters: c.milestone_chapters ?? 30,
      checkpoint_every_n: c.checkpoint_every_n ?? 10,
      checkpoint_on_volume_end: c.checkpoint_on_volume_end ?? true,
      budget_cents: Math.round((c.budget?.max_amount_cents ?? 3000) / 100),
      chapter_provider: c.models?.chapter?.provider_config_id ?? '',
      chapter_model: c.models?.chapter?.model ?? '',
      chapter_target_words: c.params?.chapter?.target_word_count ?? 3000,
      chapter_temperature: c.params?.chapter?.temperature ?? 0.8,
      analysis_provider: c.models?.analysis?.provider_config_id ?? '',
      analysis_model: c.models?.analysis?.model ?? '',
    });
    setConfigOpen(true);
  };

  const saveConfig = async () => {
    if (!pipeline) return;
    const v = await configForm.validateFields();
    const payload = {
      milestone_chapters: v.milestone_chapters,
      checkpoint_every_n: v.checkpoint_every_n,
      checkpoint_on_volume_end: v.checkpoint_on_volume_end,
      budget: { max_amount_cents: Math.round((v.budget_cents ?? 30) * 100), max_tokens: 0 },
      models: {
        chapter: { provider_config_id: v.chapter_provider || null, model: v.chapter_model || null },
        analysis: { provider_config_id: v.analysis_provider || null, model: v.analysis_model || null },
      },
      params: {
        chapter: {
          target_word_count: v.chapter_target_words,
          temperature: v.chapter_temperature,
          max_tokens: Math.max(2000, (v.chapter_target_words ?? 3000) * 3),
        },
      },
    };
    setActionLoading('config');
    try {
      await pipelineApi.updateConfig(pipeline.id, payload);
      message.success('配置已保存');
      setConfigOpen(false);
      await refresh();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '保存失败');
    } finally {
      setActionLoading(null);
    }
  };

  const refresh = useCallback(async () => {
    if (!projectId) return;
    try {
      const res = await pipelineApi.list({ project_id: projectId });
      const pl = res.items?.[0] ?? null;
      setPipeline(pl);
      if (pl) {
        const cps = await pipelineApi.checkpoints(pl.id);
        setCheckpoints(cps);
      } else {
        setCheckpoints([]);
      }
    } catch {
      /* 轮询失败静默处理 */
    }
  }, [projectId]);

  useEffect(() => {
    refresh();
    const timer = setInterval(() => refresh(), POLL_INTERVAL);
    return () => clearInterval(timer);
  }, [refresh]);

  const cfg = useMemo(() => pipeline?.config_snapshot ?? {}, [pipeline]);
  const everyN = cfg.checkpoint_every_n ?? 10;
  const milestone = cfg.milestone_chapters ?? 0;
  const chapterCount = pipeline?.chapter_count ?? 0;

  // 下一个检查点提示
  const nextCheckpointHint = useMemo(() => {
    if (!pipeline || pipeline.status === 'idle') return null;
    const toEveryN = everyN > 0 ? everyN - (chapterCount % everyN) : null;
    const toMilestone = milestone > 0 ? Math.max(0, milestone - chapterCount) : null;
    const parts: string[] = [];
    if (toEveryN !== null && toEveryN !== 0) parts.push(`每 ${everyN} 章检查点还有 ${toEveryN} 章`);
    if (toMilestone !== null && toMilestone > 0) parts.push(`里程碑还有 ${toMilestone} 章`);
    if (toEveryN === 0 && toMilestone === 0) return '已到达检查点';
    return parts.join('；') || null;
  }, [pipeline, everyN, milestone, chapterCount]);

  const runAction = async (key: string, fn: () => Promise<unknown>) => {
    setActionLoading(key);
    try {
      await fn();
      message.success('操作成功');
      await refresh();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '操作失败');
    } finally {
      setActionLoading(null);
    }
  };

  const handleStart = () => {
    if (!projectId) return;
    Modal.confirm({
      title: '启动流水线',
      content: '将自动开始：建书 → 章节循环 → 检查点。默认每 10 章停一次、里程碑 30 章。',
      onOk: () => runAction('start', () => pipelineApi.start({ project_id: projectId })),
    });
  };

  const handleRollback = (cp: PipelineCheckpoint) => setRollbackTarget(cp);
  const confirmRollback = async () => {
    if (!pipeline || !rollbackTarget) return;
    setActionLoading('rollback');
    try {
      await pipelineApi.checkpointRollback(pipeline.id, rollbackTarget.id);
      message.success('已回滚，正在重新生成');
      setRollbackTarget(null);
      await refresh();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '回滚失败');
    } finally {
      setActionLoading(null);
    }
  };

  const statusMeta = pipeline ? (STATUS_MAP[pipeline.status] ?? STATUS_MAP.idle) : null;

  return (
    <div style={{ padding: 24 }}>
      <Title level={3}>
        流水线驾驶舱
        {pipeline && statusMeta && (
          <Tag color={statusMeta.color} style={{ marginLeft: 12 }}>{statusMeta.label}</Tag>
        )}
      </Title>

      {pipeline?.last_error && (
        <Alert type="error" showIcon message="流水线状态" description={pipeline.last_error} style={{ marginBottom: 16 }} />
      )}

      {!pipeline ? (
        <Card>
          <Empty description="这本书还没有启动流水线">
            <Button type="primary" icon={<PlayCircleOutlined />} onClick={handleStart} loading={actionLoading === 'start'}>
              启动流水线
            </Button>
          </Empty>
        </Card>
      ) : (
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          {/* 操作按钮 */}
          <Space wrap>
            {pipeline.status === 'idle' || pipeline.status === 'stopped' || pipeline.status === 'completed' ? (
              <Button type="primary" icon={<PlayCircleOutlined />} onClick={handleStart} loading={actionLoading === 'start'}>启动</Button>
            ) : null}
            {pipeline.status === 'running' ? (
              <Button icon={<PauseOutlined />} onClick={() => runAction('pause', () => pipelineApi.pause(pipeline.id))} loading={actionLoading === 'pause'}>暂停</Button>
            ) : null}
            {pipeline.status === 'paused' ? (
              <Button type="primary" icon={<CaretRightOutlined />} onClick={() => runAction('resume', () => pipelineApi.resume(pipeline.id))} loading={actionLoading === 'resume'}>继续</Button>
            ) : null}
            <Button danger icon={<StopOutlined />} onClick={() => runAction('stop', () => pipelineApi.stop(pipeline.id))} loading={actionLoading === 'stop'}>停止</Button>
            <Button icon={<SettingOutlined />} onClick={openConfig} loading={actionLoading === 'config'}>配置</Button>
          </Space>

          {/* 三层状态展示：阶段流程线 */}
          <Card title="运行状态">
            <Steps
              current={['book', 'chapter_loop', 'checkpoint', 'volume_transition'].indexOf(pipeline.current_stage)}
              items={[
                { title: STAGE_LABELS.book, description: '一键建书' },
                { title: STAGE_LABELS.chapter_loop, description: '逐章生成' },
                { title: STAGE_LABELS.checkpoint, description: '等你审阅' },
                { title: STAGE_LABELS.volume_transition, description: '下一卷' },
              ]}
            />
            <Divider />
            <Descriptions column={2} size="small">
              <Descriptions.Item label="当前阶段">{STAGE_LABELS[pipeline.current_stage] ?? pipeline.current_stage}</Descriptions.Item>
              <Descriptions.Item label="已生成章节">{chapterCount} 章</Descriptions.Item>
              <Descriptions.Item label="下一个检查点">{nextCheckpointHint ?? '—'}</Descriptions.Item>
              <Descriptions.Item label="配置">
                每 {everyN} 章 / 里程碑 {milestone || '无'} 章
              </Descriptions.Item>
              <Descriptions.Item label="预算">
                已用 ¥{(pipeline.budget_used_amount_cents / 100).toFixed(2)} / {((cfg.budget?.max_amount_cents ?? 0) / 100).toFixed(0)} · {pipeline.budget_used_tokens} tokens
              </Descriptions.Item>
            </Descriptions>
          </Card>

          {/* 检查点审阅 */}
          {pipeline.status === 'awaiting_review' && pipeline.current_checkpoint ? (
            <Card
              title={`检查点待审阅（${pipeline.current_checkpoint.chapter_from ?? 1}–${pipeline.current_checkpoint.chapter_to ?? chapterCount} 章）`}
              extra={<Tag color="warning">{pipeline.current_checkpoint.checkpoint_type}</Tag>}
            >
              <Paragraph type="secondary">
                请审阅以下章节内容与分析，然后选择"继续推进"或"回滚重写"。
              </Paragraph>
              <Space>
                <Button
                  type="primary" icon={<CheckOutlined />}
                  onClick={() => runAction('continue', () => pipelineApi.checkpointContinue(pipeline.id, pipeline.current_checkpoint!.id))}
                  loading={actionLoading === 'continue'}
                >
                  继续推进
                </Button>
                <Button
                  danger icon={<ReloadOutlined />}
                  onClick={() => handleRollback(pipeline.current_checkpoint!)}
                  loading={actionLoading === 'rollback'}
                >
                  回滚重写
                </Button>
                <Button icon={<FundOutlined />} onClick={() => navigate(`/project/${projectId}/chapter-analysis`)}>
                  剧情分析 / 多模型对比
                </Button>
              </Space>
              <Divider />
              <Text type="secondary">
                章节正文与多 LLM 对比审阅入口已预留（复用现有章节管理 / 剧情分析页面）。
              </Text>
            </Card>
          ) : null}

          {/* 检查点历史 */}
          {checkpoints.length > 0 ? (
            <Card title="检查点历史" size="small">
              {checkpoints.map((cp) => (
                <Row key={cp.id} style={{ padding: '8px 0', borderBottom: '1px solid #f0f0f0' }}>
                  <Col flex="auto">
                    <Tag>{cp.checkpoint_type}</Tag>
                    <Text>第 {cp.chapter_from ?? 1}–{cp.chapter_to ?? cp.trigger_chapter_number} 章</Text>
                  </Col>
                  <Col>
                    <Text type="secondary">{cp.status === 'pending' ? '待决策' : cp.decision ?? cp.status}</Text>
                    {cp.status === 'pending' && pipeline.status === 'awaiting_review' && (
                      <Button size="small" danger style={{ marginLeft: 8 }} onClick={() => handleRollback(cp)}>
                        回滚到此
                      </Button>
                    )}
                  </Col>
                </Row>
              ))}
            </Card>
          ) : null}
        </Space>
      )}

      <Modal
        open={!!rollbackTarget}
        title="确认回滚重写"
        onOk={confirmRollback}
        onCancel={() => setRollbackTarget(null)}
        okText="确认回滚"
        okButtonProps={{ danger: true }}
        confirmLoading={actionLoading === 'rollback'}
      >
        <Text>
          将回滚到第 {rollbackTarget?.trigger_chapter_number ?? 0} 章检查点，之后的章节内容将被清空并重新生成（纯删除，不留存）。
        </Text>
      </Modal>

      {/* 配置弹窗：里程碑与每N章分开罗列、放在一起 */}
      <Modal
        open={configOpen}
        title="流水线配置"
        onOk={saveConfig}
        onCancel={() => setConfigOpen(false)}
        okText="保存配置"
        confirmLoading={actionLoading === 'config'}
        width={560}
      >
        <Form form={configForm} layout="vertical">
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="milestone_chapters" label="里程碑（写完 N 章暂停提醒）">
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="checkpoint_every_n" label="每 N 章停一次审阅">
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="checkpoint_on_volume_end" label="每卷结束必停" valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="budget_cents" label="预算上限（元）">
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Collapse
            ghost
            items={[{
              key: 'models',
              label: '模型与参数（默认全部使用系统配置）',
              children: (
                <>
                  <Form.Item name="chapter_provider" label="章节写作 - AI 服务">
                    <Select allowClear placeholder="使用默认路由" options={providers.map(p => ({ value: p.id, label: p.name }))} />
                  </Form.Item>
                  <Form.Item name="chapter_model" label="章节写作 - 模型">
                    <Select allowClear placeholder="使用默认模型"
                      options={(providers.find(p => p.id === configForm.getFieldValue('chapter_provider'))?.models ?? []).map(m => ({ value: m, label: m }))} />
                  </Form.Item>
                  <Row gutter={16}>
                    <Col span={8}><Form.Item name="chapter_target_words" label="每章字数"><InputNumber min={200} style={{ width: '100%' }} /></Form.Item></Col>
                    <Col span={8}><Form.Item name="chapter_temperature" label="温度"><InputNumber min={0} max={2} step={0.1} style={{ width: '100%' }} /></Form.Item></Col>
                  </Row>
                  <Form.Item name="analysis_provider" label="章节分析 - AI 服务">
                    <Select allowClear placeholder="使用默认路由" options={providers.map(p => ({ value: p.id, label: p.name }))} />
                  </Form.Item>
                  <Form.Item name="analysis_model" label="章节分析 - 模型">
                    <Select allowClear placeholder="使用默认模型"
                      options={(providers.find(p => p.id === configForm.getFieldValue('analysis_provider'))?.models ?? []).map(m => ({ value: m, label: m }))} />
                  </Form.Item>
                </>
              ),
            }]}
          />
        </Form>
      </Modal>
    </div>
  );
}
