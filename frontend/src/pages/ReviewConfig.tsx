import { useEffect, useState } from 'react';
import {
  Card, Switch, Segmented, Select, Button, Space, Alert, Descriptions, message, Typography, Divider,
} from 'antd';
import { SaveOutlined } from '@ant-design/icons';
import api from '../services/api';

const { Text, Title, Paragraph } = Typography;

interface ReviewConfig {
  enabled: boolean;
  steps: number;
  max_rounds: number;
}

const STEP_DESC: Record<number, string> = {
  1: '只查错别字/标点/敏感词（proofread）',
  2: '错别字 + 表达/细节/AI 味（proofread + aidetect/human）',
  3: '错别字 + 表达/AI 味 + 剧情/伏笔/人设（完整 3 步，推荐）',
};

/** 本书审查配置：整书级正文审查开关与强度 */
export default function ReviewConfig() {
  const [projectId, setProjectId] = useState('');
  const [config, setConfig] = useState<ReviewConfig>({ enabled: true, steps: 3, max_rounds: 2 });
  const [saving, setSaving] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    // 从 URL 解析 projectId（/project/:projectId/review-config）
    const m = window.location.pathname.match(/\/project\/([^/]+)\//);
    if (m) {
      setProjectId(m[1]);
      (async () => {
        try {
          const r = (await api.get(`/projects/${m[1]}/review-config`)) as { config: ReviewConfig };
          setConfig(r.config || { enabled: true, steps: 3, max_rounds: 2 });
        } catch {
          // 默认值
        } finally {
          setLoaded(true);
        }
      })();
    }
  }, []);

  const save = async () => {
    setSaving(true);
    try {
      await api.put(`/projects/${projectId}/review-config`, { config });
      message.success('本书审查配置已保存，下次生成生效');
    } catch (e) {
      message.error(`保存失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ maxWidth: 860, margin: '0 auto', padding: '24px 16px' }}>
      <Title level={4} style={{ marginBottom: 4 }}>📖 本书审查配置</Title>
      <Paragraph type="secondary" style={{ marginTop: 0 }}>
        配置"写这卷正文/生成"后自动执行的正文审查：每章生成后先审查再分析，发现问题自动小修或打回重写。
      </Paragraph>

      {!loaded && <Alert type="info" showIcon message="加载配置..." />}

      <Card style={{ marginTop: 16 }}>
        <Descriptions column={1} size="middle" labelStyle={{ width: 220 }} contentStyle={{}}>
          <Descriptions.Item label="生成后自动审查">
            <Switch
              checked={config.enabled}
              onChange={enabled => setConfig(c => ({ ...c, enabled }))}
              checkedChildren="开启"
              unCheckedChildren="关闭"
            />
            <Text type="secondary" style={{ marginLeft: 12 }}>
              {config.enabled ? '每章生成后自动审查（默认推荐）' : '跳过自动审查（仅手动卷检查）'}
            </Text>
          </Descriptions.Item>

          <Descriptions.Item label="审查强度（流水线步数）">
            <Segmented
              options={[1, 2, 3].map(n => ({ label: `${n} 步`, value: n }))}
              value={config.steps}
              onChange={steps => setConfig(c => ({ ...c, steps: steps as number }))}
            />
            <div style={{ marginTop: 6 }}>
              <Text type="secondary">{STEP_DESC[config.steps]}</Text>
            </div>
          </Descriptions.Item>

          <Descriptions.Item label="每章最多修改轮数">
            <Select
              value={config.max_rounds}
              onChange={max_rounds => setConfig(c => ({ ...c, max_rounds }))}
              style={{ width: 160 }}
              options={[1, 2, 3].map(n => ({ label: `${n} 轮`, value: n }))}
            />
            <Text type="secondary" style={{ marginLeft: 12 }}>
              仍不达标自动停下，避免死循环烧 token
            </Text>
          </Descriptions.Item>
        </Descriptions>

        <Divider />

        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <Text strong>📌 说明</Text>
          <Text type="secondary">
            • 审查三步：①错别字/标点/敏感词 → ②表达/细节/AI 味（含"缺上下文"检查，如"递给老板一张硬币"会提示补金额物价）→ ③剧情/伏笔/人设/爽点；
          </Text>
          <Text type="secondary">
            • 小问题（minor）自动原地修改；结构问题（major）打回重写（带问题清单，配置同正文生成）；
          </Text>
          <Text type="secondary">
            • 卷卡片「🔍 卷检查」可对整卷手动体检（逐章审查 + 跨章逻辑检查），结果按章节 Tab 展示、可单条或合并 AI 修改；
          </Text>
          <Text type="secondary">
            • 本页保存后对后续"写这卷正文"生效，不影响已生成章节。
          </Text>
        </Space>

        <Button
          type="primary"
          icon={<SaveOutlined />}
          loading={saving}
          onClick={save}
          style={{ marginTop: 20 }}
        >
          保存配置
        </Button>
      </Card>
    </div>
  );
}
