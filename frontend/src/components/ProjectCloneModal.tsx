import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Descriptions,
  Form,
  Grid,
  Input,
  Modal,
  Radio,
  Select,
  Skeleton,
  Space,
  Tag,
  Typography,
  theme,
} from 'antd';
import { BookOutlined, CopyOutlined } from '@ant-design/icons';
import type { AxiosError } from 'axios';

import { projectApi } from '../services/api';
import type {
  Project,
  ProjectCloneMode,
  ProjectCloneRequest,
  ProjectCloneResponse,
  ProjectCreationConfigResponse,
  ProjectStateCheckpoint,
} from '../types';

const { Text } = Typography;

interface ProjectCloneModalProps {
  open: boolean;
  sourceProject: Project | null;
  onCancel: () => void;
  onCreated: (result: ProjectCloneResponse) => void | Promise<void>;
}

interface CloneFormValues {
  title: string;
  mode: ProjectCloneMode;
  checkpoint_id?: string;
}

const errorMessage = (error: unknown, fallback: string) => {
  const apiError = error as AxiosError<{ detail?: string }>;
  return apiError.response?.data?.detail || apiError.message || fallback;
};

const shortModelName = (model?: string | null) => {
  if (!model) return '副本';
  const value = model.split('/').pop()?.trim() || model.trim();
  return value.slice(0, 48) || '副本';
};

const defaultCloneTitle = (project: Project, config?: ProjectCreationConfigResponse | null) => {
  const label = shortModelName(config?.config.chapter.model);
  return `${project.title}-${label}`.slice(0, 200);
};

export default function ProjectCloneModal({
  open,
  sourceProject,
  onCancel,
  onCreated,
}: ProjectCloneModalProps) {
  const [form] = Form.useForm<CloneFormValues>();
  const { token } = theme.useToken();
  const screens = Grid.useBreakpoint();
  const compact = !screens.sm;
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [checkpoints, setCheckpoints] = useState<ProjectStateCheckpoint[]>([]);
  const [creationConfig, setCreationConfig] = useState<ProjectCreationConfigResponse | null>(null);
  const mode = Form.useWatch('mode', form) ?? 'settings_only';
  const selectedCheckpointId = Form.useWatch('checkpoint_id', form);

  useEffect(() => {
    if (!open || !sourceProject) return;
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    setSubmitError(null);
    setCheckpoints([]);
    setCreationConfig(null);
    form.setFieldsValue({
      title: `${sourceProject.title}-副本`.slice(0, 200),
      mode: 'settings_only',
      checkpoint_id: undefined,
    });

    Promise.all([
      projectApi.getStateCheckpoints(sourceProject.id),
      projectApi.getCreationConfig(sourceProject.id),
    ]).then(([checkpointRows, config]) => {
      if (cancelled) return;
      setCheckpoints(checkpointRows);
      setCreationConfig(config);
      form.setFieldValue('title', defaultCloneTitle(sourceProject, config));
    }).catch((error: unknown) => {
      if (!cancelled) setLoadError(errorMessage(error, '加载副本信息失败'));
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });

    return () => {
      cancelled = true;
    };
  }, [form, open, sourceProject]);

  const selectedCheckpoint = useMemo(
    () => checkpoints.find(item => item.id === selectedCheckpointId) ?? null,
    [checkpoints, selectedCheckpointId],
  );

  const submit = async () => {
    if (!sourceProject || submitting || loading || loadError) return;
    const values = await form.validateFields();
    const payload: ProjectCloneRequest = {
      title: values.title.trim(),
      mode: values.mode,
      checkpoint_id: values.mode === 'inherit_checkpoint' ? values.checkpoint_id : undefined,
    };
    setSubmitting(true);
    setSubmitError(null);
    try {
      const result = await projectApi.cloneProject(sourceProject.id, payload);
      await onCreated(result);
    } catch (error: unknown) {
      setSubmitError(errorMessage(error, '创建副本失败'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      title={
        <Space size={8}>
          <CopyOutlined />
          <span>创建独立书籍副本</span>
        </Space>
      }
      width={compact ? 'calc(100vw - 24px)' : 640}
      centered={compact}
      styles={{ body: { maxHeight: compact ? 'calc(100vh - 180px)' : undefined, overflowY: 'auto' } }}
      okText="创建副本"
      cancelText="取消"
      confirmLoading={submitting}
      okButtonProps={{ disabled: loading || Boolean(loadError) }}
      onOk={() => void submit()}
      onCancel={submitting ? undefined : onCancel}
      maskClosable={!submitting}
      keyboard={!submitting}
      destroyOnHidden
    >
      {loading ? (
        <Skeleton active paragraph={{ rows: 7 }} />
      ) : (
        <Form form={form} layout="vertical" requiredMark={false}>
          {loadError && (
            <Alert type="error" showIcon message="无法读取源书信息" description={loadError} style={{ marginBottom: 16 }} />
          )}
          {submitError && (
            <Alert type="error" showIcon message="副本未创建" description={submitError} style={{ marginBottom: 16 }} />
          )}

          <Form.Item
            name="title"
            label="新书名称"
            rules={[
              { required: true, whitespace: true, message: '请输入新书名称' },
              { max: 200, message: '书名不能超过 200 个字符' },
            ]}
          >
            <Input prefix={<BookOutlined />} maxLength={200} showCount disabled={Boolean(loadError)} />
          </Form.Item>

          <Form.Item name="mode" label="复制范围">
            <Radio.Group style={{ width: '100%', display: 'grid', gridTemplateColumns: '1fr', gap: 8 }}>
              <Radio.Button
                value="settings_only"
                style={{ width: '100%', height: 'auto', minHeight: 64, padding: '10px 14px', whiteSpace: 'normal' }}
              >
                <Space direction="vertical" size={0} style={{ width: '100%' }}>
                  <Text strong>从头开始</Text>
                  <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'normal' }}>复制设定和章节结构，正文与创作进度为空</Text>
                </Space>
              </Radio.Button>
              <Radio.Button
                value="inherit_checkpoint"
                disabled={checkpoints.length === 0}
                style={{ width: '100%', height: 'auto', minHeight: 64, padding: '10px 14px', whiteSpace: 'normal' }}
              >
                <Space direction="vertical" size={0} style={{ width: '100%' }}>
                  <Text strong>继承已有进度</Text>
                  <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'normal' }}>复制到可靠章节，并带入对应分析和人物状态</Text>
                </Space>
              </Radio.Button>
            </Radio.Group>
          </Form.Item>

          {mode === 'inherit_checkpoint' && (
            <Form.Item
              name="checkpoint_id"
              label="继承到哪一章"
              rules={[{ required: true, message: '请选择可靠章节' }]}
            >
              <Select
                placeholder="选择可继承章节"
                options={checkpoints.map(item => ({
                  value: item.id,
                  label: `第 ${item.chapter_number} 章`,
                }))}
              />
            </Form.Item>
          )}

          {checkpoints.length === 0 && (
            <Alert
              type="info"
              showIcon
              message="当前没有可继承章节"
              description="仍可选择“从头开始”。已有正文需要先完成正式分析并形成可靠状态节点，才能连同进度一起复制。"
              style={{ marginBottom: 16 }}
            />
          )}

          {mode === 'inherit_checkpoint' && selectedCheckpoint && (
            <Alert
              type="warning"
              showIcon
              message={`将继承至第 ${selectedCheckpoint.chapter_number} 章`}
              description="第 1 章到该章的正文、分析、记忆、伏笔、人物关系、组织和职业进度会作为一个整体复制；后续章节只保留空白结构。"
              style={{ marginBottom: 16 }}
            />
          )}

          {creationConfig && (
            <div style={{ borderTop: `1px solid ${token.colorBorderSecondary}`, paddingTop: 14 }}>
              <Descriptions size="small" column={compact ? 1 : 2}>
                <Descriptions.Item label="章节模型">
                  <Tag style={{ maxWidth: '100%', whiteSpace: 'normal', overflowWrap: 'anywhere' }}>
                    {creationConfig.config.chapter.model || '默认路由'}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="分析模型">
                  <Tag style={{ maxWidth: '100%', whiteSpace: 'normal', overflowWrap: 'anywhere' }}>
                    {creationConfig.config.analysis.model || '默认路由'}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="Skill">
                  {creationConfig.config.skill_key || '未选择'}
                </Descriptions.Item>
                <Descriptions.Item label="MCP">
                  {creationConfig.config.mcp.enabled
                    ? `已启用，${creationConfig.config.mcp.plugin_ids.length} 个插件`
                    : '未启用'}
                </Descriptions.Item>
              </Descriptions>
              <Text type="secondary" style={{ fontSize: 12 }}>
                这些配置会默认带入。副本创建后可在其“流水线”页面单独修改，不会自动启动。
              </Text>
              {creationConfig.validation_errors.length > 0 && (
                <Alert
                  type="warning"
                  showIcon
                  message="源书部分配置当前不可用"
                  description={creationConfig.validation_errors.join('；')}
                  style={{ marginTop: 12 }}
                />
              )}
            </div>
          )}
        </Form>
      )}
    </Modal>
  );
}
