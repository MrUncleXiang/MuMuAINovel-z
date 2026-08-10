import { useState } from 'react';
import { Input, Button, Space, Alert, Modal, Divider, message, theme } from 'antd';
import { ThunderboltOutlined, CheckOutlined } from '@ant-design/icons';
import ReactDiffViewer from 'react-diff-viewer-continued';
import { ssePost } from '../utils/sseClient';
import AIServiceSelector, { type AIServiceSelection } from './AIServiceSelector';
import SkillSelector, { SKILL_CATEGORIES } from './SkillSelector';
import { useThemeMode } from '../theme/useThemeMode';

const { TextArea } = Input;

interface Props {
  chapterId: string;
  originalContent: string;
  onApply: (newContent: string) => void; // 应用修改（回填表单）
}

/** 编辑弹窗内的 AI 对话式修改区：指令驱动最小修改 → diff 确认 → 应用/继续改 */
export default function ChapterAIChatEdit({ chapterId, originalContent, onApply }: Props) {
  const { token } = theme.useToken();
  const { resolvedMode } = useThemeMode();
  const [instruction, setInstruction] = useState('');
  const [selection, setSelection] = useState<AIServiceSelection | undefined>();
  const [skillKey, setSkillKey] = useState<string | undefined>();
  const [generating, setGenerating] = useState(false);
  const [diffVisible, setDiffVisible] = useState(false);
  const [generated, setGenerated] = useState('');

  const handleSend = async () => {
    const instr = instruction.trim();
    if (!instr) {
      message.info('请输入修改要求，例如：把第一句改得更紧张');
      return;
    }
    setGenerating(true);
    let acc = '';
    try {
      await ssePost(
        `/api/chapters/${chapterId}/ai-edit-stream`,
        {
          instruction: instr,
          provider_config_id: selection?.provider_config_id,
          model: selection?.model,
          skill_key: skillKey,
        },
        {
          onChunk: (content: string) => {
            acc += content;
          },
          onResult: () => {
            setGenerated(acc);
            setDiffVisible(true);
          },
          onError: (error: string) => {
            message.error(`AI 修改失败：${error}`);
          },
        },
      );
    } catch (error) {
      message.error(`AI 修改失败：${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setGenerating(false);
    }
  };

  const handleApply = () => {
    onApply(generated);
    setDiffVisible(false);
    setInstruction(''); // 应用后可再输入新的修改
    message.success('已回填修改后的内容，请核对后点击保存');
  };

  return (
    <>
      <Divider style={{ margin: '16px 0 8px' }}>🤖 AI 修改（说一句，AI 只改你要的地方）</Divider>
      <TextArea
        rows={2}
        placeholder="例如：把开头改得更紧张有画面感；删掉这段心理描写；这句对话改口语一点"
        value={instruction}
        onChange={e => setInstruction(e.target.value)}
        disabled={generating}
        style={{ marginBottom: 8 }}
      />
      <Space wrap size={8} style={{ marginBottom: 8, width: '100%' }}>
        <AIServiceSelector usageType="chapter_write" value={selection} onChange={setSelection} disabled={generating} />
        <SkillSelector value={skillKey} onChange={setSkillKey} disabled={generating} categories={SKILL_CATEGORIES.WRITING} />
      </Space>
      <Space direction="vertical" size={4} style={{ width: '100%' }}>
        {generating && (
          <Alert type="info" showIcon message="AI 正在按你的要求修改（通常 30-60 秒），完成后会弹出前后对比" />
        )}
        <Button
          type="primary"
          ghost
          icon={<ThunderboltOutlined />}
          loading={generating}
          onClick={handleSend}
        >
          AI 修改
        </Button>
      </Space>

      {/* 前后对比确认弹窗 */}
      <Modal
        title="🤖 AI 修改对比"
        open={diffVisible}
        width="92%"
        centered
        onCancel={() => setDiffVisible(false)}
        onOk={handleApply}
        okText="应用修改"
        cancelText="继续改"
        okButtonProps={{ icon: <CheckOutlined /> }}
        styles={{ body: { maxHeight: 'calc(80vh - 200px)', overflowY: 'auto', padding: 16 } }}
      >
        <Alert
          type="info"
          showIcon
          message="高亮处为 AI 的修改（红色=原文，绿色=修改后）；其余内容应保持不变，如有意外改动可点「继续改」重新下指令"
          style={{ marginBottom: 12 }}
        />
        <div style={{ border: `1px solid ${token.colorBorderSecondary}`, borderRadius: 6 }}>
          <ReactDiffViewer
            oldValue={originalContent || '（空）'}
            newValue={generated || '（空）'}
            leftTitle="原文"
            rightTitle="修改后"
            splitView
            useDarkTheme={resolvedMode === 'dark'}
            styles={{
              variables: {
                light: { diffViewerBackground: token.colorBgContainer, diffViewerColor: token.colorText },
                dark: { diffViewerBackground: token.colorBgContainer, diffViewerColor: token.colorText },
              },
              line: { whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: 13.5, lineHeight: 1.9 },
            }}
          />
        </div>
      </Modal>
    </>
  );
}
