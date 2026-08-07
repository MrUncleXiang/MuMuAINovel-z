import { useCallback, useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Alert, Button, Card, Col, Collapse, Descriptions, Divider, Empty, Form, InputNumber, Modal, Row,
  Select, Space, Steps, Switch, Tag, Typography, message,
} from 'antd';
import {
  CaretRightOutlined, CheckOutlined, FundOutlined, PauseOutlined, PlayCircleOutlined,
  ReloadOutlined, SettingOutlined, StopOutlined,
} from '@ant-design/icons';
import {
  aiProviderApi, mcpPluginApi, pipelineApi, projectApi, skillApi, writingStyleApi,
} from '../services/api';
import type {
  AIProviderConfig, MCPPlugin, NovelPipeline, PipelineCheckpoint,
  ProjectCreationConfigData, ProjectCreationConfigResponse, SkillSummary, WritingStyle,
} from '../types';

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

const apiErrorMessage = (error: unknown, fallback: string) => {
  if (axios.isAxiosError<{ detail?: string }>(error)) {
    return error.response?.data?.detail || fallback;
  }
  return fallback;
};

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
  const [styles, setStyles] = useState<WritingStyle[]>([]);
  const [skills, setSkills] = useState<SkillSummary[]>([]);
  const [plugins, setPlugins] = useState<MCPPlugin[]>([]);
  const [creationConfig, setCreationConfig] = useState<ProjectCreationConfigResponse | null>(null);
  const chapterProviderId = Form.useWatch('chapter_provider', configForm);
  const analysisProviderId = Form.useWatch('analysis_provider', configForm);
  const mcpEnabled = Form.useWatch('mcp_enabled', configForm);

  useEffect(() => {
    if (!projectId) return;
    Promise.all([
      aiProviderApi.list(),
      writingStyleApi.getProjectStyles(projectId),
      skillApi.list(),
      mcpPluginApi.getPlugins(),
    ]).then(([providerRows, styleResponse, skillRows, pluginRows]) => {
      setProviders(providerRows);
      setStyles(styleResponse.styles);
      setSkills(skillRows);
      setPlugins(pluginRows);
    }).catch(() => message.error('加载创作配置选项失败'));
  }, [projectId]);

  const openConfig = async () => {
    if (!projectId) return;
    if (pipeline?.status === 'running') {
      message.warning('请先暂停流水线，再修改创作配置');
      return;
    }
    setActionLoading('config-load');
    try {
      const response = await projectApi.getCreationConfig(projectId);
      const c = response.config;
      setCreationConfig(response);
      configForm.setFieldsValue({
        chapter_provider: c.chapter.provider_config_id ?? undefined,
        chapter_model: c.chapter.model ?? undefined,
        analysis_provider: c.analysis.provider_config_id ?? undefined,
        analysis_model: c.analysis.model ?? undefined,
        skill_key: c.skill_key ?? undefined,
        writing_style_id: c.writing_style_id ?? undefined,
        mcp_enabled: c.mcp.enabled,
        mcp_plugin_ids: c.mcp.plugin_ids,
        narrative_perspective: c.narrative_perspective ?? undefined,
        target_word_count: c.target_word_count,
        temperature: c.temperature,
        max_tokens: c.max_tokens ?? undefined,
        budget_limit: c.pipeline.budget_limit ?? undefined,
        checkpoint_every_n_chapters: c.pipeline.checkpoint_every_n_chapters,
        milestone_chapters: c.pipeline.milestone_chapters,
        checkpoint_on_volume_end: c.pipeline.checkpoint_on_volume_end,
      });
      setConfigOpen(true);
    } catch (error: unknown) {
      message.error(apiErrorMessage(error, '加载创作配置失败'));
    } finally {
      setActionLoading(null);
    }
  };

  const saveConfig = async () => {
    if (!projectId) return;
    const v = await configForm.validateFields();
    const payload: ProjectCreationConfigData = {
      chapter: { provider_config_id: v.chapter_provider || null, model: v.chapter_model || null },
      analysis: { provider_config_id: v.analysis_provider || null, model: v.analysis_model || null },
      skill_key: v.skill_key || null,
      writing_style_id: v.writing_style_id ?? null,
      mcp: {
        enabled: Boolean(v.mcp_enabled),
        plugin_ids: v.mcp_enabled ? (v.mcp_plugin_ids ?? []) : [],
      },
      narrative_perspective: v.narrative_perspective || null,
      target_word_count: v.target_word_count,
      temperature: v.temperature,
      max_tokens: v.max_tokens ?? null,
      pipeline: {
        budget_limit: v.budget_limit ?? null,
        checkpoint_every_n_chapters: v.checkpoint_every_n_chapters,
        milestone_chapters: v.milestone_chapters,
        checkpoint_on_volume_end: Boolean(v.checkpoint_on_volume_end),
        auto_advance: false,
      },
    };
    setActionLoading('config');
    try {
      const response = await projectApi.saveCreationConfig(projectId, payload);
      setCreationConfig(response);
      const appliedToPipeline = Boolean(
        pipeline && ['paused', 'awaiting_review'].includes(pipeline.status),
      );
      if (pipeline && appliedToPipeline) {
        await pipelineApi.updateConfig(pipeline.id, {});
      }
      message.success(appliedToPipeline ? '配置已保存并应用到流水线' : '创作配置已保存');
      setConfigOpen(false);
      await refresh();
    } catch (error: unknown) {
      message.error(apiErrorMessage(error, '保存失败'));
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
    } catch (error: unknown) {
      message.error(apiErrorMessage(error, '操作失败'));
    } finally {
      setActionLoading(null);
    }
  };

  const handleStart = () => {
    if (!projectId) return;
    Modal.confirm({
      title: '启动流水线',
      content: '将按这本书已保存的模型、Skill、写作风格和 MCP 配置开始推进。',
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
    } catch (error: unknown) {
      message.error(apiErrorMessage(error, '回滚失败'));
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
            <Space>
              <Button icon={<SettingOutlined />} onClick={openConfig} loading={actionLoading === 'config-load'}>创作配置</Button>
              <Button type="primary" icon={<PlayCircleOutlined />} onClick={handleStart} loading={actionLoading === 'start'}>
                启动流水线
              </Button>
            </Space>
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
            <Button
              icon={<SettingOutlined />}
              onClick={openConfig}
              loading={actionLoading === 'config-load' || actionLoading === 'config'}
            >创作配置</Button>
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

      <Modal
        open={configOpen}
        title="本书创作配置"
        onOk={saveConfig}
        onCancel={() => setConfigOpen(false)}
        okText="保存配置"
        confirmLoading={actionLoading === 'config'}
        width={640}
      >
        {creationConfig?.validation_errors.length ? (
          <Alert
            type="error"
            showIcon
            message="当前配置包含已失效资源"
            description={creationConfig.validation_errors.join('；')}
            style={{ marginBottom: 16 }}
          />
        ) : null}
        <Form form={configForm} layout="vertical">
          <Collapse
            ghost
            items={[{
              key: 'models',
              label: '模型与正文参数',
              children: (
                <>
                  <Form.Item name="chapter_provider" label="章节写作 - AI 服务">
                    <Select allowClear placeholder="使用默认路由" options={providers.map(p => ({ value: p.id, label: p.name }))} />
                  </Form.Item>
                  <Form.Item name="chapter_model" label="章节写作 - 模型">
                    <Select allowClear placeholder="使用默认模型"
                      options={(providers.find(p => p.id === chapterProviderId)?.models ?? []).map(m => ({ value: m, label: m }))} />
                  </Form.Item>
                  <Form.Item name="analysis_provider" label="章节分析 - AI 服务">
                    <Select allowClear placeholder="使用默认路由" options={providers.map(p => ({ value: p.id, label: p.name }))} />
                  </Form.Item>
                  <Form.Item name="analysis_model" label="章节分析 - 模型">
                    <Select allowClear placeholder="使用默认模型"
                      options={(providers.find(p => p.id === analysisProviderId)?.models ?? []).map(m => ({ value: m, label: m }))} />
                  </Form.Item>
                  <Row gutter={16}>
                    <Col span={8}><Form.Item name="target_word_count" label="每章字数" rules={[{ required: true }]}><InputNumber min={500} max={10000} style={{ width: '100%' }} /></Form.Item></Col>
                    <Col span={8}><Form.Item name="temperature" label="温度" rules={[{ required: true }]}><InputNumber min={0} max={2} step={0.1} style={{ width: '100%' }} /></Form.Item></Col>
                    <Col span={8}><Form.Item name="max_tokens" label="最大 Tokens"><InputNumber min={256} max={100000} style={{ width: '100%' }} /></Form.Item></Col>
                  </Row>
                </>
              ),
            }, {
              key: 'resources',
              label: '创作能力',
              children: (
                <>
                  <Form.Item name="skill_key" label="创作 Skill">
                    <Select allowClear placeholder="不使用 Skill" options={skills.map(skill => ({
                      value: skill.template_key,
                      label: `${skill.template_name} · ${skill.category}`,
                    }))} />
                  </Form.Item>
                  <Form.Item name="writing_style_id" label="写作风格">
                    <Select allowClear placeholder="不指定风格" options={styles.map(style => ({ value: style.id, label: style.name }))} />
                  </Form.Item>
                  <Form.Item name="narrative_perspective" label="叙事视角">
                    <Select allowClear options={['第一人称', '第三人称', '多视角'].map(value => ({ value, label: value }))} />
                  </Form.Item>
                  <Form.Item name="mcp_enabled" label="启用 MCP 工具" valuePropName="checked">
                    <Switch />
                  </Form.Item>
                  <Form.Item name="mcp_plugin_ids" label="允许使用的 MCP 插件">
                    <Select
                      mode="multiple"
                      disabled={!mcpEnabled}
                      placeholder="选择本书可使用的插件"
                      options={plugins.map(plugin => ({
                        value: plugin.id,
                        label: plugin.display_name,
                        disabled: !plugin.enabled,
                      }))}
                    />
                  </Form.Item>
                </>
              ),
            }, {
              key: 'pipeline',
              label: '推进与检查点',
              children: (
                <>
                  <Row gutter={16}>
                    <Col span={12}><Form.Item name="checkpoint_every_n_chapters" label="每 N 章停一次审阅" rules={[{ required: true }]}><InputNumber min={1} max={100} style={{ width: '100%' }} /></Form.Item></Col>
                    <Col span={12}><Form.Item name="milestone_chapters" label="里程碑章节数" rules={[{ required: true }]}><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
                  </Row>
                  <Row gutter={16}>
                    <Col span={12}><Form.Item name="checkpoint_on_volume_end" label="每卷结束必停" valuePropName="checked"><Switch /></Form.Item></Col>
                    <Col span={12}><Form.Item name="budget_limit" label="预算上限（元）"><InputNumber min={0} precision={2} style={{ width: '100%' }} /></Form.Item></Col>
                  </Row>
                </>
              ),
            }]}
          />
        </Form>
      </Modal>
    </div>
  );
}
