import { Modal, Select, Space, Typography, theme } from 'antd';
import ReactDiffViewer from 'react-diff-viewer-continued';
import type { LLMComparisonCandidate } from '../types';
import { useThemeMode } from '../theme/useThemeMode';

const { Text } = Typography;

interface Props {
  open: boolean;
  candidates: LLMComparisonCandidate[];
  leftId?: string;
  rightId?: string;
  onSelectionChange: (leftId?: string, rightId?: string) => void;
  onClose: () => void;
}

/** 任意两个成功候选的逐行差异查看。 */
export default function LLMCandidateDiffModal({ open, candidates, leftId, rightId, onSelectionChange, onClose }: Props) {
  const { token } = theme.useToken();
  const { resolvedMode } = useThemeMode();
  const options = candidates.filter(item => item.status === 'success').map(item => ({
    value: item.id,
    label: `${item.provider_name} · ${item.model}`,
  }));
  const left = candidates.find(item => item.id === leftId);
  const right = candidates.find(item => item.id === rightId);

  return (
    <Modal title="两个候选的差异" open={open} onCancel={onClose} footer={null} width="95%">
      <Space wrap style={{ marginBottom: 16 }}>
        <Text>左侧：</Text>
        <Select style={{ width: 280 }} value={leftId} options={options} onChange={value => onSelectionChange(value, rightId)} />
        <Text>右侧：</Text>
        <Select style={{ width: 280 }} value={rightId} options={options} onChange={value => onSelectionChange(leftId, value)} />
      </Space>
      <ReactDiffViewer
        oldValue={left?.output_text || ''}
        newValue={right?.output_text || ''}
        leftTitle={left ? `${left.provider_name} · ${left.model}` : '候选 A'}
        rightTitle={right ? `${right.provider_name} · ${right.model}` : '候选 B'}
        splitView
        useDarkTheme={resolvedMode === 'dark'}
        styles={{
          variables: {
            light: { diffViewerBackground: token.colorBgContainer, diffViewerColor: token.colorText },
            dark: { diffViewerBackground: token.colorBgContainer, diffViewerColor: token.colorText },
          },
          line: { whiteSpace: 'pre-wrap', wordBreak: 'break-word' },
        }}
      />
    </Modal>
  );
}
