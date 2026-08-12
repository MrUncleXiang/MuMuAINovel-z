import { useState } from 'react';
import { Button, Card, Input, Spin, message, theme, Tag } from 'antd';
import {
  BulbOutlined, SendOutlined, CheckOutlined, ThunderboltOutlined,
  DownOutlined, UpOutlined, RestOutlined,
} from '@ant-design/icons';
import { outlineApi } from '../services/api';
import SkillSelector, { SKILL_CATEGORIES } from './SkillSelector';

interface AdviceOption {
  title: string;
  description: string;
  conflict?: string;
  plotline?: string;
}

interface AdviceMessage {
  prompt: string;
  options: AdviceOption[];
  /** 该轮选项是否已禁用（用户已选过一次） */
  disabled: boolean;
  /** 用户选中的选项索引 */
  selectedIndex?: number;
  /** 该轮选中的选项标题（用于选择链） */
  selectedTitle?: string;
}

interface OutlineContinueAdviceProps {
  projectId: string;
  isMobile: boolean;
  /** 从表单实时读取 AI 服务/Skill 选择（对话区本地 Skill 优先） */
  getAISelection: () => { skill_key?: string; provider_config_id?: string; model?: string };
  /** 确认方向后的回调（父组件填入表单，由用户点「开始续写」提交） */
  onConfirm: (direction: string) => void;
}

const MAX_ROUNDS = 5;

/**
 * 续写方向 AI 建议（灵感模式式对话流）
 * - 点选选项 = 选择并延深（AI 深入下一轮）；历史轮折叠
 * - 每轮仅反馈输入框；「确认此方向」只在当前轮底部（唯一）
 * - 顶部：Skill 选择器 + 当前选择链 + 轮数指示
 * - context 只传最近 2 轮选择；最多 MAX_ROUNDS 轮
 */
export default function OutlineContinueAdvice({ projectId, isMobile, getAISelection, onConfirm }: OutlineContinueAdviceProps) {
  const { token } = theme.useToken();
  const [expanded, setExpanded] = useState(false);
  const [messages, setMessages] = useState<AdviceMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [confirming, setConfirming] = useState(false);
  const [skillKey, setSkillKey] = useState<string | undefined>(undefined);
  const [historyCollapsed, setHistoryCollapsed] = useState(true);
  /** 最近一次用户选定/反馈的方向（用于确认） */
  const [latestDirection, setLatestDirection] = useState('');

  // 选择链（各轮选中的标题）
  const chain = messages.filter(m => m.selectedTitle).map(m => m.selectedTitle!);
  const round = messages.length;

  const requestAdvice = async (context?: string, fb?: string) => {
    setLoading(true);
    try {
      const base = getAISelection();
      const res = await outlineApi.continueAdvice({
        project_id: projectId,
        context,
        feedback: fb,
        skill_key: skillKey ?? base.skill_key,
        provider_config_id: base.provider_config_id,
        model: base.model,
      });
      const msg: AdviceMessage = { prompt: res.prompt, options: res.options, disabled: false };
      setMessages(prev => [...prev, msg]);
    } catch (error) {
      message.error('获取续写方向建议失败，请重试');
    } finally {
      setLoading(false);
    }
  };

  const handleStart = () => {
    setExpanded(true);
    if (messages.length === 0) void requestAdvice();
  };

  const handleSelectOption = (msgIndex: number, option: AdviceOption) => {
    if (messages[msgIndex]?.disabled || loading) return;
    const direction = `【${option.title}】${option.description}`;
    setLatestDirection(direction);
    setMessages(prev => prev.map((m, i) =>
      i === msgIndex ? { ...m, disabled: true, selectedIndex: m.options.indexOf(option), selectedTitle: option.title } : m
    ));
    // 达到轮数上限：不再延深，提示确认或重新开始
    if (messages.length >= MAX_ROUNDS) {
      message.info(`已达 ${MAX_ROUNDS} 轮，可确认当前方向，或点「重新开始」换方向`);
      return;
    }
    // context 只传最近 2 轮选择链
    const nextChain = [...chain, option.title].slice(-2);
    void requestAdvice(nextChain.join(' → '));
  };

  const handleFeedbackSend = () => {
    const text = feedback.trim();
    if (!text || loading) return;
    setLatestDirection(text);
    setFeedback('');
    void requestAdvice(undefined, text);
  };

  const handleConfirm = async () => {
    if (!latestDirection || confirming) return;
    setConfirming(true);
    try {
      await onConfirm(latestDirection);
    } catch {
      // 确认失败恢复按钮，由父组件提示
    } finally {
      setConfirming(false);
    }
  };

  const handleRestart = () => {
    setMessages([]);
    setLatestDirection('');
    setFeedback('');
    setHistoryCollapsed(true);
    void requestAdvice();
  };

  // 当前轮 = 最后一条消息；其余为历史
  const historyMsgs = messages.slice(0, -1);
  const currentMsg = messages.length > 0 ? messages[messages.length - 1] : null;

  // 选项卡片
  const renderOptionCard = (opt: AdviceOption, msg: AdviceMessage, optIndex: number, clickable: boolean) => {
    const isSelected = msg.selectedIndex === optIndex;
    return (
      <Card
        key={optIndex}
        size="small"
        hoverable={clickable}
        onClick={() => clickable && handleSelectOption(messages.indexOf(msg), opt)}
        style={{
          cursor: clickable ? 'pointer' : 'not-allowed',
          border: isSelected ? `2px solid ${token.colorPrimary}` : `1px solid ${token.colorBorder}`,
          background: isSelected ? token.colorPrimaryBg : token.colorBgContainer,
          opacity: msg.disabled && !isSelected ? 0.55 : 1,
          transition: 'all 0.3s ease',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
          <span style={{ fontSize: isMobile ? 13 : 14, fontWeight: 600, color: token.colorText }}>
            {opt.title}
          </span>
          {isSelected && <CheckOutlined style={{ color: token.colorPrimary }} />}
        </div>
        <div style={{ marginTop: 2, fontSize: isMobile ? 12 : 13, color: token.colorText, lineHeight: '1.6' }}>
          {opt.description}
        </div>
        <div style={{ display: 'flex', gap: 6, marginTop: 4, flexWrap: 'wrap' }}>
          {opt.conflict && <Tag color="orange" style={{ fontSize: isMobile ? 11 : 12, margin: 0 }}>⚔️ {opt.conflict}</Tag>}
          {opt.plotline && <Tag color="blue" style={{ fontSize: isMobile ? 11 : 12, margin: 0 }}>🧵 {opt.plotline}</Tag>}
        </div>
      </Card>
    );
  };

  return (
    <div style={{ marginTop: 12 }}>
      {!expanded ? (
        <Button
          block={isMobile}
          icon={<BulbOutlined />}
          onClick={handleStart}
          style={{ width: isMobile ? '100%' : undefined }}
        >
          ✨ AI 建议发展方向
        </Button>
      ) : (
        <div style={{
          border: `1px solid ${token.colorBorderSecondary}`,
          borderRadius: token.borderRadius,
          padding: isMobile ? 10 : 14,
          background: token.colorFillQuaternary,
        }}>
          {/* 顶部工具栏：Skill 选择 + 选择链 + 轮数 */}
          <div style={{
            display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
            marginBottom: 10, paddingBottom: 8, borderBottom: `1px dashed ${token.colorBorderSecondary}`,
          }}>
            <span style={{ fontSize: isMobile ? 12 : 13, color: token.colorTextSecondary }}>应用 Skill</span>
            <SkillSelector
              value={skillKey}
              onChange={setSkillKey}
              disabled={loading || confirming}
              categories={SKILL_CATEGORIES.OUTLINE}
            />
          </div>
          {chain.length > 0 && (
            <div style={{
              marginBottom: 10, fontSize: isMobile ? 12 : 13, color: token.colorTextSecondary,
              background: token.colorPrimaryBg, borderRadius: token.borderRadius, padding: '6px 10px',
            }}>
              📍 当前选择链：{chain.join(' → ')}
              <Tag style={{ marginLeft: 8 }} color="default">第 {round}/{MAX_ROUNDS} 轮</Tag>
            </div>
          )}

          {/* 历史轮（折叠为一行，可展开） */}
          {historyMsgs.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <Button
                type="text"
                size="small"
                icon={historyCollapsed ? <DownOutlined /> : <UpOutlined />}
                onClick={() => setHistoryCollapsed(v => !v)}
                style={{ fontSize: isMobile ? 12 : 13, padding: 0, height: 'auto' }}
              >
                历史对话（{historyMsgs.length} 轮）
              </Button>
              {!historyCollapsed && historyMsgs.map((m, idx) => (
                <div key={idx} style={{
                  marginTop: 6, padding: '6px 10px', background: token.colorBgContainer,
                  border: `1px solid ${token.colorBorder}`, borderRadius: token.borderRadiusSM,
                  fontSize: isMobile ? 12 : 13, color: token.colorTextSecondary,
                }}>
                  <span style={{ fontWeight: 600, color: token.colorText }}>{m.selectedTitle || `第${idx + 1}轮`}</span>
                  {' — '}{m.prompt.length > 60 ? m.prompt.slice(0, 60) + '...' : m.prompt}
                </div>
              ))}
            </div>
          )}

          {/* 当前轮 */}
          {currentMsg && (
            <div>
              <div style={{
                padding: '8px 12px', background: token.colorBgContainer,
                border: `1px solid ${token.colorBorder}`, borderRadius: token.borderRadius,
                fontSize: isMobile ? 12 : 13, color: token.colorText, lineHeight: '1.7', whiteSpace: 'pre-wrap',
              }}>
                {currentMsg.prompt}
              </div>

              {currentMsg.options.length > 0 && (
                <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {currentMsg.options.map((opt, optIndex) =>
                    renderOptionCard(opt, currentMsg, optIndex, !currentMsg.disabled && !loading && !confirming)
                  )}
                </div>
              )}

              {/* 当前轮底部：反馈输入 + 唯一确认按钮 */}
              {!confirming && (
                <div style={{ marginTop: 8 }}>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <Input.TextArea
                      value={feedback}
                      onChange={(e) => setFeedback(e.target.value)}
                      placeholder="对方向不满意？打字告诉 AI 调整（如：不要新角色，专注推理线）"
                      autoSize={{ minRows: 1, maxRows: 3 }}
                      disabled={loading || confirming}
                      style={{ fontSize: isMobile ? 12 : 13 }}
                    />
                    <Button
                      icon={<SendOutlined />}
                      onClick={handleFeedbackSend}
                      loading={loading}
                      disabled={confirming || !feedback.trim()}
                      title="发送反馈，AI 按你的话重新给方向"
                    />
                  </div>
                  <Button
                    type="primary"
                    block
                    icon={<ThunderboltOutlined />}
                    onClick={handleConfirm}
                    disabled={!latestDirection || confirming}
                    style={{ marginTop: 8 }}
                  >
                    ✅ 确认此方向
                  </Button>
                  {latestDirection && !confirming && (
                    <div style={{ marginTop: 6, fontSize: isMobile ? 12 : 13, color: token.colorTextSecondary }}>
                      确认后方向将填入「故事发展方向」，点击弹窗底部「开始续写」提交。
                    </div>
                  )}
                </div>
              )}
              {confirming && (
                <div style={{ marginTop: 8, fontSize: isMobile ? 12 : 13, color: token.colorSuccess }}>
                  ✓ 方向已确认，已填入「故事发展方向」，点击弹窗底部「开始续写」即可提交。
                </div>
              )}
            </div>
          )}

          {/* 加载中 */}
          {loading && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: token.colorTextSecondary, fontSize: 12, marginTop: 8 }}>
              <Spin size="small" />
              AI 正在分析故事走向…
            </div>
          )}

          {/* 重新开始（对话中显示） */}
          {messages.length > 0 && !loading && !confirming && (
            <Button
              size="small"
              icon={<RestOutlined />}
              onClick={handleRestart}
              style={{ marginTop: 10, fontSize: isMobile ? 12 : 13 }}
            >
              重新开始
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
