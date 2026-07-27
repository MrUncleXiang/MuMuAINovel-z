import { useEffect, useMemo, useState } from 'react';
import { Alert, Form, Select, Space, Typography } from 'antd';
import { aiProviderApi } from '../services/api';
import type { AIProviderConfig, LLMComparisonSelection } from '../types';

const { Text } = Typography;

interface Props {
  value?: LLMComparisonSelection[];
  onChange?: (value: LLMComparisonSelection[]) => void;
  disabled?: boolean;
  min?: number;
  max?: number;
}

/** 比较任务共用的 2～4 个“服务 + 模型”多选器。 */
export default function LLMMultiSelector({ value = [], onChange, disabled, min = 2, max = 4 }: Props) {
  const [providers, setProviders] = useState<AIProviderConfig[]>([]);

  useEffect(() => {
    aiProviderApi.list()
      .then(items => setProviders(items.filter(item => item.enabled)))
      .catch(() => setProviders([]));
  }, []);

  const options = useMemo(() => providers.flatMap(provider => {
    const models = Array.from(new Set([provider.default_model, ...(provider.models || [])].filter(Boolean))) as string[];
    return models.map(model => ({
      value: `${provider.id}\u0000${model}`,
      label: `${provider.name} · ${model}`,
      selection: { provider_config_id: provider.id, model },
    }));
  }), [providers]);

  const selectedKeys = value.map(item => `${item.provider_config_id}\u0000${item.model}`);
  const costHint = value.length >= min
    ? `本次会调用 ${value.length} 个模型，Token 消耗大约是单模型的 ${value.length} 倍。系统最多同时运行 2 个，避免 VPS 负担过重。`
    : `请至少选择 ${min} 个不同的服务/模型，最多 ${max} 个。`;

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="small">
      <Form.Item label="参与比较的 AI 服务和模型" style={{ marginBottom: 8 }}>
        <Select
          mode="multiple"
          showSearch
          disabled={disabled}
          value={selectedKeys}
          maxCount={max}
          placeholder={`请选择 ${min}～${max} 个服务/模型`}
          options={options.map(({ value: optionValue, label }) => ({ value: optionValue, label }))}
          onChange={(keys: string[]) => {
            const next = keys
              .map(key => options.find(option => option.value === key)?.selection)
              .filter((item): item is LLMComparisonSelection => Boolean(item));
            onChange?.(next);
          }}
        />
      </Form.Item>
      <Alert type={value.length >= min ? 'warning' : 'info'} showIcon message={<Text>{costHint}</Text>} />
    </Space>
  );
}
