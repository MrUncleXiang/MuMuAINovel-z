import { useState, useEffect } from 'react';
import { Empty, Tag, Spin, theme } from 'antd';
import { ReadOutlined } from '@ant-design/icons';
import { useStore } from '../store';
import { useOutlineSync } from '../store/hooks';

/**
 * 大纲总览页（通读视图）
 * 将所有卷大纲按顺序连续铺开，纯阅读，无操作按钮。
 * 用于作者从头通读一遍大纲，检查故事逻辑与伏笔衔接。
 */
export default function OutlineOverview() {
  const { currentProject, outlines } = useStore();
  const { refreshOutlines } = useOutlineSync();
  const { token } = theme.useToken();
  const [isMobile, setIsMobile] = useState(window.innerWidth <= 768);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const handleResize = () => setIsMobile(window.innerWidth <= 768);
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        await refreshOutlines(currentProject?.id);
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentProject?.id]);

  // 按卷序号排序（后端已按 order_index 排序，这里兜底再排一次）
  const sortedOutlines = [...outlines].sort((a, b) => (a.order_index ?? 0) - (b.order_index ?? 0));
  const isOneToOne = currentProject?.outline_mode === 'one-to-one';

  const volumeLabel = (outline: { order_index?: number }) =>
    isOneToOne ? `第${outline.order_index || '?'}章` : `第${outline.order_index || '?'}卷`;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* 固定头部 */}
      <div style={{
        position: 'sticky',
        top: 0,
        zIndex: 10,
        backgroundColor: token.colorBgContainer,
        padding: isMobile ? '12px 0' : '16px 0',
        marginBottom: isMobile ? 12 : 16,
        borderBottom: `1px solid ${token.colorBorderSecondary}`,
      }}>
        <h2 style={{ margin: 0, fontSize: isMobile ? 18 : 24 }}>
          <ReadOutlined style={{ marginRight: 8 }} />
          大纲总览
        </h2>
        <div style={{
          marginTop: 4,
          fontSize: isMobile ? 12 : 13,
          color: token.colorTextSecondary,
        }}>
          按卷顺序连续通读全部大纲，仅阅读视图；修改请到「大纲管理」。
        </div>
      </div>

      {/* 可滚动内容区域 */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {loading ? (
          <div style={{ display: 'flex', justifyContent: 'center', padding: '80px 0' }}>
            <Spin size="large" />
          </div>
        ) : sortedOutlines.length === 0 ? (
          <Empty description="还没有大纲，请先到「大纲管理」创建或生成大纲" />
        ) : (
          <div>
            {sortedOutlines.map((outline, idx) => (
              <div key={outline.id}>
                {idx > 0 && (
                  <div style={{
                    height: 1,
                    margin: isMobile ? '20px 0' : '28px 0',
                    background: token.colorBorderSecondary,
                  }} />
                )}
                {/* 卷标题行 */}
                <div style={{
                  display: 'flex',
                  alignItems: 'baseline',
                  justifyContent: 'space-between',
                  gap: 8,
                  flexWrap: 'wrap',
                  marginBottom: isMobile ? 8 : 12,
                }}>
                  <div style={{
                    fontSize: isMobile ? 16 : 19,
                    fontWeight: 600,
                    color: token.colorPrimary,
                    lineHeight: '1.4',
                  }}>
                    {volumeLabel(outline)}
                    <span style={{ marginLeft: 8, color: token.colorText }}>
                      {outline.title || '未命名'}
                    </span>
                  </div>
                  {(outline.chapter_count ?? 0) > 0 ? (
                    <Tag
                      color="success"
                      style={{ margin: 0, fontSize: isMobile ? 11 : 12 }}
                    >
                      已展开 · {outline.chapter_count} 章
                    </Tag>
                  ) : (
                    <Tag
                      color="default"
                      style={{ margin: 0, fontSize: isMobile ? 11 : 12 }}
                    >
                      未展开
                    </Tag>
                  )}
                </div>
                {/* 大纲正文 */}
                <div style={{
                  padding: isMobile ? '10px 12px' : '12px 16px',
                  background: token.colorFillQuaternary,
                  borderLeft: `3px solid ${token.colorBorderSecondary}`,
                  borderRadius: token.borderRadius,
                  fontSize: isMobile ? 13 : 14,
                  color: token.colorText,
                  lineHeight: '1.9',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                }}>
                  {outline.content || '暂无内容'}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
