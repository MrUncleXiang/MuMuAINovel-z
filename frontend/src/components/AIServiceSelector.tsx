import { useEffect, useMemo, useState } from 'react';
import { Alert, Form, Select, Space, Typography } from 'antd';
import { aiProviderApi } from '../services/api';
import type { AIProviderConfig } from '../types';

const { Text } = Typography;

export interface AIServiceSelection {
  provider_config_id?: string;
  model?: string;
}

interface Props {
  usageType: string;
  value?: AIServiceSelection;
  onChange?: (value: AIServiceSelection) => void;
  disabled?: boolean;
}

/** 所有“本次生成”弹窗共用，避免各页面自己拼供应商和模型选择逻辑。 */
export default function AIServiceSelector({ usageType, value, onChange, disabled }: Props) {
  const [providers, setProviders] = useState<AIProviderConfig[]>([]);
  const [resolved, setResolved] = useState<{ provider_name: string; model: string }>();
  const selected = providers.find(item => item.id === value?.provider_config_id);
  // 默认服务商（未指定时展示其模型列表；无 is_default 时兑底到第一个启用的）
  const defaultProvider = providers.find(item => item.is_default) ?? providers[0];
  const sourceProvider = selected ?? defaultProvider;

  useEffect(() => {
    aiProviderApi.list().then(items => setProviders(items.filter(item => item.enabled))).catch(() => setProviders([]));
  }, []);

  useEffect(() => {
    aiProviderApi.resolve(usageType, value).then(setResolved).catch(() => setResolved(undefined));
  }, [usageType, value?.provider_config_id, value?.model]);

  const modelOptions = useMemo(() => {
    if (!sourceProvider) return [];
    return Array.from(new Set([sourceProvider.default_model, ...(sourceProvider.models || [])].filter(Boolean)))
      .map(model => ({ label: model as string, value: model as string }));
  }, [sourceProvider]);

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="small">
      <Form.Item label="本次使用的 AI 服务" style={{ marginBottom: 8 }}>
        <Select
          allowClear
          disabled={disabled}
          value={value?.provider_config_id}
          placeholder="不指定，使用该任务的默认配置"
          options={providers.map(item => ({
            value: item.id,
            label: `${item.name}${item.is_default ? '（默认）' : ''}${item.default_model ? ` · ${item.default_model}` : ''}`,
          }))}
          onChange={provider_config_id => onChange?.({ provider_config_id, model: undefined })}
        />
      </Form.Item>
      <Form.Item label="本次模型" style={{ marginBottom: 8 }}>
        <Select
          allowClear
          showSearch
          disabled={disabled}
          value={value?.model}
          placeholder={sourceProvider ? `默认服务商: ${sourceProvider.name}` : "不指定，使用服务默认模型"}
          options={modelOptions}
          onChange={model => onChange?.({ ...value, provider_config_id: value?.provider_config_id ?? defaultProvider?.id, model })}
        />
      </Form.Item>
      {resolved && (
        <Alert
          type="info"
          showIcon
          message={<Text>实际将使用：{resolved.provider_name} · {resolved.model}</Text>}
        />
      )}
    </Space>
  );
}
