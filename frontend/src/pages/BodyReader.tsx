import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Button, Drawer, Empty, Spin, Tag, Tooltip, theme } from 'antd';
import {
  ArrowLeftOutlined,
  LeftOutlined,
  RightOutlined,
  MenuOutlined,
} from '@ant-design/icons';
import { chapterApi } from '../services/api';
import type { Chapter } from '../types';

const FONT_SIZE_KEY = 'body-reader:font-size';
const FONT_SIZE_MIN = 14;
const FONT_SIZE_MAX = 22;
const FONT_SIZE_DEFAULT = 16;

const progressKey = (projectId: string) => `body-reader:progress:${projectId}`;

interface TocGroup {
  outlineId: string | null;
  outlineTitle: string;
  outlineOrder: number;
  chapters: Chapter[];
}

/**
 * 目录面板（桌面右侧栏 + 移动端 Drawer 共用）
 */
const TocPanel: React.FC<{
  groups: TocGroup[];
  activeId: string | null;
  onSelect: (id: string) => void;
}> = ({ groups, activeId, onSelect }) => {
  const { token } = theme.useToken();
  return (
    <div style={{ padding: '12px 8px' }}>
      {groups.length === 0 ? (
        <div style={{ padding: 24, textAlign: 'center', color: token.colorTextTertiary, fontSize: 13 }}>
          暂无章节
        </div>
      ) : (
        groups.map(group => (
          <div key={group.outlineId ?? 'uncategorized'} style={{ marginBottom: 12 }}>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                fontWeight: 600,
                fontSize: 13,
                color: token.colorPrimary,
                padding: '4px 8px',
              }}
            >
              {group.outlineTitle}
              <Tag style={{ margin: 0, fontSize: 11 }}>{group.chapters.length} 章</Tag>
            </div>
            {group.chapters.map(ch => {
              const active = ch.id === activeId;
              return (
                <div
                  key={ch.id}
                  id={`toc-item-${ch.id}`}
                  onClick={() => onSelect(ch.id)}
                  style={{
                    cursor: 'pointer',
                    padding: '6px 8px',
                    borderRadius: token.borderRadius,
                    fontSize: 13,
                    marginBottom: 2,
                    background: active ? token.colorPrimaryBg : 'transparent',
                    color: active ? token.colorPrimary : token.colorText,
                    fontWeight: active ? 600 : 400,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                  title={ch.title}
                >
                  第{ch.chapter_number}章 {ch.title}
                </div>
              );
            })}
          </div>
        ))
      )}
    </div>
  );
};

/**
 * 正文阅读页（仿笔趣阁拆页式通读）
 * - 右侧目录按卷分组，点击跳转；单页显示一章全部正文
 * - 目录/正文分离：目录走轻量接口（include_content=false），正文按章懒加载 + 预加载下一章
 * - 默认纯阅读：无标注、无分析、无编辑入口
 */
const BodyReader: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { token } = theme.useToken();

  // 初始 URL query 只读一次（避免 searchParams 变化触发目录重新加载）
  const initialChapterFromQuery = useRef(searchParams.get('chapter')).current;

  const [toc, setToc] = useState<Chapter[]>([]);
  const [loadingToc, setLoadingToc] = useState(true);
  const [loadingContent, setLoadingContent] = useState(false);
  const [currentChapterId, setCurrentChapterId] = useState<string | null>(null);
  const [content, setContent] = useState<string>('');
  const [tocError, setTocError] = useState<string | null>(null);
  const [fontSize, setFontSize] = useState<number>(() => {
    const saved = Number(localStorage.getItem(FONT_SIZE_KEY));
    return Number.isFinite(saved) && saved >= FONT_SIZE_MIN && saved <= FONT_SIZE_MAX
      ? saved
      : FONT_SIZE_DEFAULT;
  });
  const [isMobile, setIsMobile] = useState(window.innerWidth <= 768);
  const [drawerVisible, setDrawerVisible] = useState(false);

  // 正文缓存（章节 id → 全文）；activeChapterIdRef 防竞态：快速切章时丢弃过期响应
  const cacheRef = useRef<Map<string, string>>(new Map());
  const activeChapterIdRef = useRef<string | null>(null);
  const contentScrollRef = useRef<HTMLDivElement | null>(null);

  // 移动端检测
  useEffect(() => {
    const handleResize = () => setIsMobile(window.innerWidth <= 768);
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // 加载轻量目录（不含正文）
  useEffect(() => {
    if (!projectId) return;
    let mounted = true;
    setLoadingToc(true);
    setTocError(null);
    chapterApi
      .getChapters(projectId, { include_content: false })
      .then(items => {
        if (!mounted) return;
        setToc(items);
        // 初始章节优先级：URL query > localStorage 进度 > 第一章
        const candidates = [initialChapterFromQuery, localStorage.getItem(progressKey(projectId))];
        const first = [...items].sort((a, b) => a.chapter_number - b.chapter_number)[0];
        const initial =
          candidates.map(id => (id ? items.find(c => c.id === id) : undefined)).find(Boolean)?.id ??
          first?.id ??
          null;
        setCurrentChapterId(initial);
      })
      .catch(err => {
        console.error('加载目录失败:', err);
        if (mounted) {
          setTocError(err?.response?.data?.detail || err?.message || '加载目录失败');
        }
      })
      .finally(() => {
        if (mounted) setLoadingToc(false);
      });
    return () => {
      mounted = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  // 排序兜底（后端已按 chapter_number 排序，前端再排一次）
  const sortedToc = useMemo(
    () => [...toc].sort((a, b) => a.chapter_number - b.chapter_number),
    [toc],
  );

  // 按卷分组（复用 Chapters.tsx 同款逻辑：无大纲章节归「未分类章节」排最后）
  const groups = useMemo(() => {
    const map = new Map<string, TocGroup>();
    sortedToc.forEach(ch => {
      const key = ch.outline_id || 'uncategorized';
      if (!map.has(key)) {
        map.set(key, {
          outlineId: ch.outline_id || null,
          outlineTitle: ch.outline_title || '未分类章节',
          outlineOrder: ch.outline_order ?? 999,
          chapters: [],
        });
      }
      map.get(key)!.chapters.push(ch);
    });
    return [...map.values()].sort((a, b) => a.outlineOrder - b.outlineOrder);
  }, [sortedToc]);

  const currentChapter = useMemo(
    () => sortedToc.find(c => c.id === currentChapterId) ?? null,
    [sortedToc, currentChapterId],
  );
  const currentIndex = useMemo(
    () => sortedToc.findIndex(c => c.id === currentChapterId),
    [sortedToc, currentChapterId],
  );
  const prevChapter = currentIndex > 0 ? sortedToc[currentIndex - 1] : null;
  const nextChapter =
    currentIndex >= 0 && currentIndex < sortedToc.length - 1 ? sortedToc[currentIndex + 1] : null;

  // 加载单章正文（缓存命中直接返回）
  const loadChapter = useCallback(async (chapterId: string) => {
    const cached = cacheRef.current.get(chapterId);
    if (cached !== undefined) {
      setContent(cached);
      return;
    }
    activeChapterIdRef.current = chapterId;
    setLoadingContent(true);
    try {
      const chapter = await chapterApi.getChapter(chapterId);
      const text = chapter.content ?? '';
      cacheRef.current.set(chapterId, text);
      if (activeChapterIdRef.current === chapterId) {
        setContent(text);
        setLoadingContent(false);
      }
    } catch (err) {
      console.error('加载正文失败:', err);
      if (activeChapterIdRef.current === chapterId) {
        setContent('');
        setLoadingContent(false);
      }
    }
  }, []);

  // 切换章节：更新 URL query + 进度记忆，加载正文并预加载下一章
  const switchChapter = useCallback(
    (chapterId: string) => {
      if (!chapterId || chapterId === currentChapterId) return;
      setCurrentChapterId(chapterId);
      setSearchParams({ chapter: chapterId }, { replace: true });
      if (projectId) localStorage.setItem(progressKey(projectId), chapterId);
    },
    [currentChapterId, projectId, setSearchParams],
  );

  useEffect(() => {
    if (!currentChapterId) return;
    activeChapterIdRef.current = currentChapterId;
    void loadChapter(currentChapterId);
    // 预加载下一章（翻章无感）
    const idx = sortedToc.findIndex(c => c.id === currentChapterId);
    const next = idx >= 0 ? sortedToc[idx + 1] : undefined;
    if (next && !cacheRef.current.has(next.id)) {
      chapterApi
        .getChapter(next.id)
        .then(ch => {
          cacheRef.current.set(next.id, ch.content ?? '');
        })
        .catch(() => {
          /* 预加载失败静默，切章时再加载 */
        });
    }
    contentScrollRef.current?.scrollTo({ top: 0 });
  }, [currentChapterId, loadChapter, sortedToc]);

  // 目录当前章高亮 + 滚动到可见
  useEffect(() => {
    if (!currentChapterId) return;
    document
      .getElementById(`toc-item-${currentChapterId}`)
      ?.scrollIntoView({ block: 'nearest' });
  }, [currentChapterId]);

  const changeFontSize = (delta: number) => {
    const next = Math.min(FONT_SIZE_MAX, Math.max(FONT_SIZE_MIN, fontSize + delta));
    setFontSize(next);
    localStorage.setItem(FONT_SIZE_KEY, String(next));
  };

  const renderChapterContent = () => {
    if (loadingContent) {
      return (
        <div style={{ textAlign: 'center', padding: '60px 0' }}>
          <Spin tip="加载正文..." />
        </div>
      );
    }
    if (!content) {
      return (
        <Empty
          description="本章尚未生成，请到「章节管理」生成"
          style={{ padding: '60px 0' }}
        />
      );
    }
    return (
      <div
        style={{
          lineHeight: 2,
          fontSize,
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          color: token.colorText,
        }}
      >
        {content}
      </div>
    );
  };

  const renderBottomNav = () => (
    <div
      style={{
        marginTop: 48,
        paddingTop: 24,
        borderTop: `1px solid ${token.colorBorderSecondary}`,
        display: 'flex',
        justifyContent: 'space-between',
        gap: 8,
      }}
    >
      <Button
        icon={<LeftOutlined />}
        onClick={() => prevChapter && switchChapter(prevChapter.id)}
        disabled={!prevChapter}
      >
        {prevChapter ? `上一章：第${prevChapter.chapter_number}章 ${prevChapter.title}` : '已是第一章'}
      </Button>
      <Button
        type="primary"
        icon={<RightOutlined />}
        iconPosition="end"
        onClick={() => nextChapter && switchChapter(nextChapter.id)}
        disabled={!nextChapter}
      >
        {nextChapter ? `下一章：第${nextChapter.chapter_number}章 ${nextChapter.title}` : '已是最后一章'}
      </Button>
    </div>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* 顶部工具栏 */}
      <div
        style={{
          position: 'sticky',
          top: 0,
          zIndex: 10,
          backgroundColor: token.colorBgContainer,
          padding: isMobile ? '10px 12px' : '12px 16px',
          borderBottom: `1px solid ${token.colorBorderSecondary}`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 8,
          flexWrap: 'wrap',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', minWidth: 0 }}>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)}>
            返回
          </Button>
          <Tooltip title={prevChapter ? `上一章：第${prevChapter.chapter_number}章 ${prevChapter.title}` : '已是第一章'}>
            <Button icon={<LeftOutlined />} onClick={() => prevChapter && switchChapter(prevChapter.id)} disabled={!prevChapter}>
              上一章
            </Button>
          </Tooltip>
          <span
            style={{
              fontSize: isMobile ? 15 : 17,
              fontWeight: 600,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              maxWidth: isMobile ? 200 : 420,
            }}
          >
            {currentChapter
              ? `第${currentChapter.chapter_number}章 ${currentChapter.title}`
              : '正文阅读'}
            {currentChapter && currentChapter.word_count > 0 && (
              <span style={{ fontSize: 12, color: token.colorTextSecondary, marginLeft: 8, fontWeight: 400 }}>
                {currentChapter.word_count.toLocaleString()} 字
              </span>
            )}
          </span>
          <Tooltip title={nextChapter ? `下一章：第${nextChapter.chapter_number}章 ${nextChapter.title}` : '已是最后一章'}>
            <Button
              icon={<RightOutlined />}
              iconPosition="end"
              onClick={() => nextChapter && switchChapter(nextChapter.id)}
              disabled={!nextChapter}
            >
              下一章
            </Button>
          </Tooltip>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <Button size="small" onClick={() => changeFontSize(-1)} disabled={fontSize <= FONT_SIZE_MIN}>
            A-
          </Button>
          <span style={{ fontSize: 12, color: token.colorTextSecondary, minWidth: 38, textAlign: 'center' }}>
            {fontSize}px
          </span>
          <Button size="small" onClick={() => changeFontSize(1)} disabled={fontSize >= FONT_SIZE_MAX}>
            A+
          </Button>
          {isMobile && (
            <Button icon={<MenuOutlined />} onClick={() => setDrawerVisible(true)}>
              目录
            </Button>
          )}
        </div>
      </div>

      {/* 主区域 */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>
        {/* 正文区 */}
        <div
          ref={contentScrollRef}
          style={{
            flex: 1,
            overflowY: 'auto',
            padding: isMobile ? '16px 12px' : '32px 48px',
            minWidth: 0,
          }}
        >
          {loadingToc ? (
            <div style={{ display: 'flex', justifyContent: 'center', padding: '80px 0' }}>
              <Spin size="large" tip="加载目录..." />
            </div>
          ) : tocError ? (
            <div style={{ padding: 24 }}>
              <Empty description={tocError} />
              <div style={{ textAlign: 'center', marginTop: 12 }}>
                <Button onClick={() => window.location.reload()}>重试</Button>
              </div>
            </div>
          ) : !currentChapter ? (
            <Empty description="还没有章节，请先到「章节管理」创建或生成章节" style={{ padding: '80px 0' }} />
          ) : (
            <div style={{ maxWidth: 800, margin: '0 auto' }}>
              <h1
                style={{
                  fontSize: isMobile ? 20 : 24,
                  fontWeight: 700,
                  textAlign: 'center',
                  margin: 0,
                  padding: '8px 0 20px',
                  color: token.colorText,
                }}
              >
                第{currentChapter.chapter_number}章 {currentChapter.title}
              </h1>
              {renderChapterContent()}
              {renderBottomNav()}
            </div>
          )}
        </div>

        {/* 右侧目录（桌面端） */}
        {!isMobile && (
          <div
            style={{
              width: 280,
              flexShrink: 0,
              borderLeft: `1px solid ${token.colorBorderSecondary}`,
              overflowY: 'auto',
              background: token.colorBgLayout,
            }}
          >
            <div style={{ padding: '12px 16px 4px', fontWeight: 600, fontSize: 14 }}>
              目录
            </div>
            <TocPanel groups={groups} activeId={currentChapterId} onSelect={switchChapter} />
          </div>
        )}
      </div>

      {/* 移动端目录抽屉 */}
      <Drawer
        title="目录"
        placement="right"
        open={drawerVisible}
        onClose={() => setDrawerVisible(false)}
        width="80%"
      >
        <TocPanel
          groups={groups}
          activeId={currentChapterId}
          onSelect={id => {
            switchChapter(id);
            setDrawerVisible(false);
          }}
        />
      </Drawer>
    </div>
  );
};

export default BodyReader;
