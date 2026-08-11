import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { List, Button, Modal, Form, Input, Select, message, Empty, Space, Badge, Tag, Card, InputNumber, Alert, Radio, Descriptions, Collapse, Popconfirm, Pagination, Segmented, Row, Col, Checkbox, theme, Tabs } from 'antd';
import { EditOutlined, FileTextOutlined, ThunderboltOutlined, LockOutlined, DownloadOutlined, SettingOutlined, FundOutlined, SyncOutlined, CheckCircleOutlined, CloseCircleOutlined, RocketOutlined, StopOutlined, InfoCircleOutlined, CaretRightOutlined, DeleteOutlined, BookOutlined, FormOutlined, PlusOutlined, ReadOutlined, ExclamationCircleOutlined, SearchOutlined } from '@ant-design/icons';
import { useStore } from '../store';
import { eventBus } from '../store/eventBus';
import { useChapterSync } from '../store/hooks';
import { generateChapterBackground } from '../services/backgroundTaskService';
import AIServiceSelector, { type AIServiceSelection } from '../components/AIServiceSelector';
import SkillSelector, { SKILL_CATEGORIES } from '../components/SkillSelector';
import LLMMultiSelector from '../components/LLMMultiSelector';
import LLMCandidateCard from '../components/LLMCandidateCard';
import LLMCandidateDiffModal from '../components/LLMCandidateDiffModal';
import { projectApi, writingStyleApi, chapterApi, llmComparisonApi, aiProviderApi } from '../services/api';
import api from '../services/api';
import type { Chapter, ChapterUpdate, ApiError, WritingStyle, AnalysisTask, ExpansionPlanData, LLMComparisonBatch, LLMComparisonCandidate, LLMComparisonSelection , AIProviderConfig} from '../types';
import type { TextAreaRef } from 'antd/es/input/TextArea';
import ChapterAnalysis from '../components/ChapterAnalysis';
import ChapterAIChatEdit from '../components/ChapterAIChatEdit';
import ExpansionPlanEditor from '../components/ExpansionPlanEditor';
import ChapterReviewModal, { type ChapterReviewRecord } from '../components/ChapterReviewModal';
import { SSELoadingOverlay } from '../components/SSELoadingOverlay';
import ChapterReader from '../components/ChapterReader';
import PartialRegenerateToolbar from '../components/PartialRegenerateToolbar';
import PartialRegenerateModal from '../components/PartialRegenerateModal';

const { TextArea } = Input;

// localStorage 缓存键名
const WORD_COUNT_CACHE_KEY = 'chapter_default_word_count';
const DEFAULT_WORD_COUNT = 3000;

// 从 localStorage 读取缓存的字数
const getCachedWordCount = (): number => {
  try {
    const cached = localStorage.getItem(WORD_COUNT_CACHE_KEY);
    if (cached) {
      const value = parseInt(cached, 10);
      if (!isNaN(value) && value >= 500 && value <= 10000) {
        return value;
      }
    }
  } catch (error) {
    console.warn('读取字数缓存失败:', error);
  }
  return DEFAULT_WORD_COUNT;
};

// 保存字数到 localStorage
const setCachedWordCount = (value: number): void => {
  try {
    localStorage.setItem(WORD_COUNT_CACHE_KEY, String(value));
  } catch (error) {
    console.warn('保存字数缓存失败:', error);
  }
};

export default function Chapters() {
  const { currentProject, chapters, outlines, setCurrentChapter, setCurrentProject } = useStore();
  const [modal, contextHolder] = Modal.useModal();
  const { token } = theme.useToken();
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isEditorOpen, setIsEditorOpen] = useState(false);
  const [editorActiveTab, setEditorActiveTab] = useState('edit');
  const [isContinuing, setIsContinuing] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form] = Form.useForm();
  const [editorForm] = Form.useForm();
  const [isMobile, setIsMobile] = useState(window.innerWidth <= 768);
  const contentTextAreaRef = useRef<TextAreaRef>(null);
  const [writingStyles, setWritingStyles] = useState<WritingStyle[]>([]);
  const [selectedStyleId, setSelectedStyleId] = useState<number | undefined>();
  const [targetWordCount, setTargetWordCount] = useState<number>(getCachedWordCount);
  const [selectedModel, setSelectedModel] = useState<string | undefined>();
  const [aiServiceSelection, setAIServiceSelection] = useState<AIServiceSelection>({});
  const [generationMode, setGenerationMode] = useState<'single' | 'compare'>('single');
  const [comparisonSelections, setComparisonSelections] = useState<LLMComparisonSelection[]>([]);
  const [comparisonBatch, setComparisonBatch] = useState<LLMComparisonBatch | null>(null);
  const [comparisonVisible, setComparisonVisible] = useState(false);
  const [comparisonBusy, setComparisonBusy] = useState(false);
  const comparisonPollingRef = useRef<number | null>(null);
  const [candidateDiffVisible, setCandidateDiffVisible] = useState(false);
  const [candidateDiffIds, setCandidateDiffIds] = useState<[string | undefined, string | undefined]>([undefined, undefined]);
  // 批量生成的 AI 服务+模型选择（统一用 AIServiceSelector）
  const [batchAIState, setBatchAIState] = useState<AIServiceSelection>({});
  const [providers, setProviders] = useState<AIProviderConfig[]>([]);
  const [batchMode, setBatchMode] = useState<'single' | 'compare'>('single'); // 批量生成方式
  const [batchComparisonSelections, setBatchComparisonSelections] = useState<LLMComparisonSelection[]>([]); // 批量多模型选择
  const [batchSelectedSkillKey, setBatchSelectedSkillKey] = useState<string | undefined>(); // 批量生成的Skill选择
  const [temporaryNarrativePerspective, setTemporaryNarrativePerspective] = useState<string | undefined>(); // 临时人称选择
  const [availableSkills, setAvailableSkills] = useState<Array<{ template_key: string; template_name: string; description: string; category: string }>>([]);
  const [selectedSkillKey, setSelectedSkillKey] = useState<string | undefined>();
  // 正文写作场景只提供“正文写作”类 Skill，避免把审稿/人设/大纲等混进来
  const writingSkills = useMemo(
    () => availableSkills.filter(skill => skill.category === 'Skill·正文写作'),
    [availableSkills],
  );
  const [analysisVisible, setAnalysisVisible] = useState(false);
  const [analysisChapterId, setAnalysisChapterId] = useState<string | null>(null);
  // 分析任务状态管理
  const [analysisTasksMap, setAnalysisTasksMap] = useState<Record<string, AnalysisTask>>({});
  const analysisPollingIntervalRef = useRef<number | null>(null);
  const activeAnalysisPollingIdsRef = useRef<Set<string>>(new Set());
  const analysisPollingInFlightRef = useRef(false);
  const analysisPollingRequestIdRef = useRef(0);
  const currentProjectIdRef = useRef<string | undefined>(currentProject?.id);
  currentProjectIdRef.current = currentProject?.id;
  // ── 章节审查记录（最近一次）──
  const [reviewRecords, setReviewRecords] = useState<Record<string, ChapterReviewRecord>>({});
  const [reviewModal, setReviewModal] = useState<ChapterReviewRecord | null>(null);
  const [reviewModalTitle, setReviewModalTitle] = useState('');

  // 列表查询与分页状态
  const [chapterSearchKeyword, setChapterSearchKeyword] = useState('');
  const [chapterPage, setChapterPage] = useState(1);
  const [chapterPageSize, setChapterPageSize] = useState(20);

  // 阅读器状态
  const [readerVisible, setReaderVisible] = useState(false);
  const [readingChapter, setReadingChapter] = useState<Chapter | null>(null);

  // 规划编辑状态
  const [planEditorVisible, setPlanEditorVisible] = useState(false);
  const [editingPlanChapter, setEditingPlanChapter] = useState<Chapter | null>(null);

  // 局部重写状态
  const [partialRegenerateToolbarVisible, setPartialRegenerateToolbarVisible] = useState(false);
  const [partialRegenerateToolbarPosition, setPartialRegenerateToolbarPosition] = useState({ top: 0, left: 0 });
  const [selectedTextForRegenerate, setSelectedTextForRegenerate] = useState('');
  const [selectionStartPosition, setSelectionStartPosition] = useState(0);
  const [selectionEndPosition, setSelectionEndPosition] = useState(0);
  const [partialRegenerateModalVisible, setPartialRegenerateModalVisible] = useState(false);

  // 单章节生成进度状态
  const [singleChapterProgress, setSingleChapterProgress] = useState(0);
  const [singleChapterProgressMessage, setSingleChapterProgressMessage] = useState('');


  // 批量生成相关状态
  const [batchGenerateVisible, setBatchGenerateVisible] = useState(false);
  const [batchGenerating, setBatchGenerating] = useState(false);
  const [batchAnalyzingUnanalyzed, setBatchAnalyzingUnanalyzed] = useState(false);
  const [batchTaskId, setBatchTaskId] = useState<string | null>(null);
  const [batchForm] = Form.useForm();
  const [manualCreateForm] = Form.useForm();
  const [batchProgress, setBatchProgress] = useState<{
    status: string;
    total: number;
    completed: number;
    current_chapter_number: number | null;
    estimated_time_minutes?: number;
  } | null>(null);
  const batchPollingIntervalRef = useRef<number | null>(null);

  useEffect(() => {
    const handleResize = () => {
      setIsMobile(window.innerWidth <= 768);
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // 处理文本选中 - 检测选中文本并显示浮动工具栏
  const handleTextSelection = useCallback(() => {
    // 只在编辑器打开时处理选中
    if (!isEditorOpen || isGenerating) {
      setPartialRegenerateToolbarVisible(false);
      return;
    }

    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0) {
      setPartialRegenerateToolbarVisible(false);
      return;
    }

    const selectedText = selection.toString().trim();
    
    // 至少选中10个字符才显示工具栏
    if (selectedText.length < 10) {
      setPartialRegenerateToolbarVisible(false);
      return;
    }

    // 检查选中是否在 TextArea 内
    const textArea = contentTextAreaRef.current?.resizableTextArea?.textArea;
    if (!textArea) {
      setPartialRegenerateToolbarVisible(false);
      return;
    }
    
    // 检查选中是否在 textarea 内（需要特殊处理，因为 textarea 的选中不会创建 range）
    if (document.activeElement !== textArea) {
      setPartialRegenerateToolbarVisible(false);
      return;
    }

    // 获取 textarea 中的选中位置
    const start = textArea.selectionStart;
    const end = textArea.selectionEnd;
    const textContent = textArea.value;
    const selectedInTextArea = textContent.substring(start, end);

    if (selectedInTextArea.trim().length < 10) {
      setPartialRegenerateToolbarVisible(false);
      return;
    }

    // 计算浮动工具栏位置
    const rect = textArea.getBoundingClientRect();
    const computedStyle = window.getComputedStyle(textArea);
    const lineHeight = parseFloat(computedStyle.lineHeight) || 24;
    const paddingTop = parseFloat(computedStyle.paddingTop) || 0;
    
    // 计算选中文本起始位置所在的行号
    const textBeforeSelection = textContent.substring(0, start);
    const startLine = textBeforeSelection.split('\n').length - 1;
    
    // 计算选中文本在 textarea 中的视觉位置
    // 需要考虑 scrollTop（textarea 内部滚动偏移）
    const scrollTop = textArea.scrollTop;
    const visualTop = (startLine * lineHeight) + paddingTop - scrollTop;
    
    // 工具栏位置：textarea 顶部 + 选中文本的视觉位置 - 工具栏高度偏移
    const toolbarTop = rect.top + visualTop - 45;
    
    // 水平位置：放在 textarea 的右侧区域，避免遮挡文本
    const toolbarLeft = rect.right - 180;

    setSelectedTextForRegenerate(selectedInTextArea);
    setSelectionStartPosition(start);
    setSelectionEndPosition(end);
    
    // 计算工具栏位置，如果选中位置不在可视区域内，固定在边缘
    let finalTop = toolbarTop;
    if (visualTop < 0) {
      finalTop = rect.top + 10;
    } else if (visualTop > textArea.clientHeight) {
      finalTop = rect.bottom - 50;
    }
    
    setPartialRegenerateToolbarPosition({
      top: Math.max(rect.top + 10, Math.min(finalTop, rect.bottom - 50)),
      left: Math.min(Math.max(rect.left + 20, toolbarLeft), window.innerWidth - 200),
    });
    setPartialRegenerateToolbarVisible(true);
  }, [isEditorOpen, isGenerating]);

  // 更新工具栏位置的函数（不检测选中，只更新位置）
  const updateToolbarPosition = useCallback(() => {
    if (!partialRegenerateToolbarVisible || !selectedTextForRegenerate) return;
    
    const textArea = contentTextAreaRef.current?.resizableTextArea?.textArea;
    if (!textArea) return;
    
    const rect = textArea.getBoundingClientRect();
    const computedStyle = window.getComputedStyle(textArea);
    const lineHeight = parseFloat(computedStyle.lineHeight) || 24;
    const paddingTop = parseFloat(computedStyle.paddingTop) || 0;
    
    const textContent = textArea.value;
    const textBeforeSelection = textContent.substring(0, selectionStartPosition);
    const startLine = textBeforeSelection.split('\n').length - 1;
    
    const scrollTop = textArea.scrollTop;
    const visualTop = (startLine * lineHeight) + paddingTop - scrollTop;
    
    const toolbarTop = rect.top + visualTop - 45;
    // 固定在 textarea 右上角，不随选中位置变化
    const toolbarLeft = rect.right - 180;
    
    // 工具栏固定在 textarea 可视区域内，即使选中文本滚出视野也保持显示
    // 如果选中位置在可视区域内，跟随选中位置
    // 如果滚出视野，固定在顶部或底部边缘
    let finalTop = toolbarTop;
    if (visualTop < 0) {
      // 选中位置在上方视野外，工具栏固定在顶部
      finalTop = rect.top + 10;
    } else if (visualTop > textArea.clientHeight) {
      // 选中位置在下方视野外，工具栏固定在底部
      finalTop = rect.bottom - 50;
    }
    
    setPartialRegenerateToolbarPosition({
      top: Math.max(rect.top + 10, Math.min(finalTop, rect.bottom - 50)),
      left: Math.min(Math.max(rect.left + 20, toolbarLeft), window.innerWidth - 200),
    });
  }, [partialRegenerateToolbarVisible, selectedTextForRegenerate, selectionStartPosition]);

  // 监听选中事件
  useEffect(() => {
    if (!isEditorOpen) return;

    const textArea = contentTextAreaRef.current?.resizableTextArea?.textArea;
    if (!textArea) return;

    const handleMouseUp = () => {
      // 鼠标释放时检查选中
      setTimeout(handleTextSelection, 50);
    };

    const handleKeyUp = (e: KeyboardEvent) => {
      // Shift + 方向键选中时检查
      if (e.shiftKey && ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) {
        setTimeout(handleTextSelection, 50);
      }
    };

    const handleScroll = () => {
      // 滚动时更新位置（使用 requestAnimationFrame 优化性能）
      requestAnimationFrame(updateToolbarPosition);
    };

    // 监听 textarea 滚动
    textArea.addEventListener('mouseup', handleMouseUp);
    textArea.addEventListener('keyup', handleKeyUp);
    textArea.addEventListener('scroll', handleScroll);

    // 同时监听 Modal body 滚动（Modal 内容可能在外层容器滚动）
    const modalBody = textArea.closest('.ant-modal-body');
    if (modalBody) {
      modalBody.addEventListener('scroll', handleScroll);
    }

    // 监听窗口大小变化
    window.addEventListener('resize', handleScroll);

    return () => {
      textArea.removeEventListener('mouseup', handleMouseUp);
      textArea.removeEventListener('keyup', handleKeyUp);
      textArea.removeEventListener('scroll', handleScroll);
      if (modalBody) {
        modalBody.removeEventListener('scroll', handleScroll);
      }
      window.removeEventListener('resize', handleScroll);
    };
  }, [isEditorOpen, handleTextSelection, updateToolbarPosition]);

  // 点击其他区域时隐藏工具栏
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      
      // 如果点击的是工具栏，不隐藏
      if (target.closest('[data-partial-regenerate-toolbar]')) {
        return;
      }
      
      // 如果点击的是 textarea，不隐藏
      if (target.tagName === 'TEXTAREA') {
        return;
      }
      
      // 如果点击的是 Modal 内部（包括滚动条），不隐藏
      if (target.closest('.ant-modal-content')) {
        return;
      }
      
      // 点击 Modal 外部才隐藏工具栏
      setPartialRegenerateToolbarVisible(false);
    };

    if (partialRegenerateToolbarVisible) {
      document.addEventListener('click', handleClickOutside);
      return () => document.removeEventListener('click', handleClickOutside);
    }
  }, [partialRegenerateToolbarVisible]);

  const {
    refreshChapters,
    updateChapter,
    deleteChapter,
    generateChapterContentStream
  } = useChapterSync();

  useEffect(() => {
    if (currentProject?.id) {
      const projectId = currentProject.id;
      if (analysisPollingIntervalRef.current !== null) {
        clearInterval(analysisPollingIntervalRef.current);
        analysisPollingIntervalRef.current = null;
      }
      analysisPollingRequestIdRef.current += 1;
      analysisPollingInFlightRef.current = false;
      activeAnalysisPollingIdsRef.current.clear();
      setAnalysisTasksMap({});

      void refreshChapters(projectId).then((latestChapters) => {
        if (currentProjectIdRef.current === projectId) {
          void loadAnalysisTasks(latestChapters, projectId);
        }
      });
      loadWritingStyles();
      checkAndRestoreBatchTask();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentProject?.id]);

  // 清理轮询定时器
  useEffect(() => {
    return () => {
      if (analysisPollingIntervalRef.current !== null) {
        clearInterval(analysisPollingIntervalRef.current);
        analysisPollingIntervalRef.current = null;
      }
      if (batchPollingIntervalRef.current !== null) {
        clearInterval(batchPollingIntervalRef.current);
        batchPollingIntervalRef.current = null;
      }
    };
  }, []);

  // 加载本书各章节最近一次审查记录
  useEffect(() => {
    if (!currentProject?.id) return;
    let cancelled = false;
    (async () => {
      try {
        const r = (await api.get(`/chapters/project/${currentProject.id}/reviews`)) as { items: ChapterReviewRecord[] };
        if (!cancelled) {
          const map: Record<string, ChapterReviewRecord> = {};
          for (const item of r.items || []) map[item.chapter_id] = item;
          setReviewRecords(map);
        }
      } catch {
        // 无记录时保持空
      }
    })();
    return () => { cancelled = true; };
  }, [currentProject?.id]);

  const clearAnalysisPollingIfIdle = useCallback(() => {
    if (activeAnalysisPollingIdsRef.current.size === 0 && analysisPollingIntervalRef.current) {
      clearInterval(analysisPollingIntervalRef.current);
      analysisPollingIntervalRef.current = null;
    }
  }, []);

  const pollActiveAnalysisTasks = useCallback(async () => {
    const projectId = currentProjectIdRef.current;
    if (!projectId || analysisPollingInFlightRef.current) return;

    const activeIds = Array.from(activeAnalysisPollingIdsRef.current);
    if (activeIds.length === 0) {
      clearAnalysisPollingIfIdle();
      return;
    }

    analysisPollingInFlightRef.current = true;
    const requestId = analysisPollingRequestIdRef.current + 1;
    analysisPollingRequestIdRef.current = requestId;

    try {
      const response = await chapterApi.getBatchAnalysisStatuses(projectId, activeIds);
      if (currentProjectIdRef.current !== projectId) return;

      const tasksMap = response.items || {};

      setAnalysisTasksMap(prev => ({
        ...prev,
        ...tasksMap,
      }));

      activeIds.forEach((chapterId) => {
        const task = tasksMap[chapterId];
        if (!task || task.status === 'completed' || task.status === 'failed' || task.status === 'none' || task.status === 'superseded') {
          activeAnalysisPollingIdsRef.current.delete(chapterId);

          if (task?.status === 'completed') {
            message.success('章节分析完成');
            // 链路闭环：分析完成后自动打开结果弹窗（重新分析不再无反馈）
            setAnalysisChapterId(chapterId);
            setAnalysisVisible(true);
          } else if (task?.status === 'failed') {
            message.error(`章节分析失败: ${task.error_message || '未知错误'}`);
          } else if (task?.status === 'superseded') {
            // 内容变更导致分析失效：停止轮询该章，避免无限轮询
            console.warn(`章节 ${chapterId} 的分析已因内容变更失效`);
          }
        }
      });

      clearAnalysisPollingIfIdle();
    } catch (error) {
      console.error('批量轮询分析任务失败:', error);
    } finally {
      if (analysisPollingRequestIdRef.current === requestId) {
        analysisPollingInFlightRef.current = false;
      }
    }
  }, [clearAnalysisPollingIfIdle]);

  const ensureAnalysisPolling = useCallback(() => {
    if (analysisPollingIntervalRef.current) return;

    analysisPollingIntervalRef.current = window.setInterval(() => {
      void pollActiveAnalysisTasks();
    }, 2000);

    // 立即执行一次
    void pollActiveAnalysisTasks();
  }, [pollActiveAnalysisTasks]);

  // 加载所有章节的分析任务状态（批量接口，避免逐章请求风暴）
  // 接受可选的 chaptersToLoad 参数，解决 React 状态更新延迟导致的问题
  const loadAnalysisTasks = async (
    chaptersToLoad?: typeof chapters,
    projectId?: string,
  ) => {
    const targetChapters = chaptersToLoad || chapters;
    const targetProjectId = projectId || currentProjectIdRef.current;
    if (!targetChapters || targetChapters.length === 0 || !targetProjectId) return;

    const chapterIds = targetChapters
      .filter(chapter => chapter.content && chapter.content.trim() !== '')
      .map(chapter => chapter.id);

    if (chapterIds.length === 0) {
      setAnalysisTasksMap({});
      activeAnalysisPollingIdsRef.current.clear();
      clearAnalysisPollingIfIdle();
      return;
    }

    try {
      const response = await chapterApi.getBatchAnalysisStatuses(targetProjectId, chapterIds);
      if (currentProjectIdRef.current !== targetProjectId) return;

      const tasksMap = response.items || {};
      setAnalysisTasksMap(tasksMap);

      activeAnalysisPollingIdsRef.current.clear();
      Object.entries(tasksMap).forEach(([chapterId, task]) => {
        if (task?.status === 'pending' || task?.status === 'running') {
          activeAnalysisPollingIdsRef.current.add(chapterId);
        }
      });

      if (activeAnalysisPollingIdsRef.current.size > 0) {
        ensureAnalysisPolling();
      } else {
        clearAnalysisPollingIfIdle();
      }
    } catch (error) {
      console.error('批量加载分析任务状态失败:', error);
    }
  };

  // 启动单个章节的任务轮询（内部合并到批量轮询）
  const startPollingTask = (chapterId: string) => {
    activeAnalysisPollingIdsRef.current.add(chapterId);
    ensureAnalysisPolling();
  };

  const loadWritingStyles = async () => {
    if (!currentProject?.id) return;

    try {
      const response = await writingStyleApi.getProjectStyles(currentProject.id);
      setWritingStyles(response.styles);

      // 设置默认风格为初始选中
      const defaultStyle = response.styles.find(s => s.is_default);
      if (defaultStyle) {
        setSelectedStyleId(defaultStyle.id);
      }
    } catch (error) {
      console.error('加载写作风格失败:', error);
      message.error('加载写作风格失败');
    }
  };

  // 加载可用的 Skill 列表
  const loadAvailableSkills = async () => {
    try {
      const response = await fetch('/api/skills/list');
      if (response.ok) {
        const data = await response.json();
        if (Array.isArray(data)) {
          setAvailableSkills(data);
        }
      }
    } catch (error) {
      console.error('加载 Skill 列表失败:', error);
    }
  };

  // 预填默认服务商及其默认模型（OpenCode Go · deepseek-v4-flash），动态获取不硬编码
  const loadDefaultSelection = async (): Promise<string | null> => {
    try {
      const providerList = await aiProviderApi.list();
      const def = providerList.find(p => p.enabled && p.is_default) ?? providerList.find(p => p.enabled);
      if (def?.default_model) {
        const selection = { provider_config_id: def.id, model: def.default_model };
        setAIServiceSelection(selection);
        setSelectedModel(def.default_model);
        setBatchAIState(selection);
        return def.default_model;
      }
    } catch {
      console.log('获取默认AI服务失败，将使用默认路由');
    }
    return null;
  };

  // 加载自定义 AI 服务配置（供批量生成选择服务）
  const loadProviders = async () => {
    try {
      const list = await aiProviderApi.list();
      setProviders(list);
    } catch {
      console.log('加载 AI 服务列表失败');
    }
  };
  useEffect(() => { loadProviders(); }, []);

  // 检查并恢复批量生成任务
  const checkAndRestoreBatchTask = async () => {
    if (!currentProject?.id) return;

    try {
      const response = await fetch(`/api/chapters/project/${currentProject.id}/batch-generate/active`);
      if (!response.ok) return;

      const data = await response.json();

      if (data.has_active_task && data.task) {
        const task = data.task;

        // 恢复任务状态（只在顶部进度条显示，不弹出Modal）
        setBatchTaskId(task.batch_id);
        setBatchProgress({
          status: task.status,
          total: task.total,
          completed: task.completed,
          current_chapter_number: task.current_chapter_number,
        });
        setBatchGenerating(true);
        // 不设置 setBatchGenerateVisible(true)，避免弹出Modal遮挡页面

        // 启动轮询
        startBatchPolling(task.batch_id);

        message.info('检测到未完成的批量生成任务，请查看任务列表');
      }
    } catch (error) {
      console.error('检查批量生成任务失败:', error);
    }
  };

  // 🔔 显示浏览器通知
  const showBrowserNotification = (title: string, body: string, type: 'success' | 'error' | 'info' = 'info') => {
    // 检查浏览器是否支持通知
    if (!('Notification' in window)) {
      console.log('浏览器不支持通知功能');
      return;
    }

    // 检查通知权限
    if (Notification.permission === 'granted') {
      // 选择图标
      const icon = type === 'success' ? '/logo.svg' : type === 'error' ? '/favicon.ico' : '/logo.svg';
      
      const notification = new Notification(title, {
        body,
        icon,
        badge: '/favicon.ico',
        tag: 'batch-generation', // 相同tag会替换旧通知
        requireInteraction: false, // 自动关闭
        silent: false, // 播放提示音
      });

      // 点击通知时聚焦到窗口
      notification.onclick = () => {
        window.focus();
        notification.close();
      };

      // 5秒后自动关闭
      setTimeout(() => {
        notification.close();
      }, 5000);
    } else if (Notification.permission !== 'denied') {
      // 如果权限未被明确拒绝，尝试请求权限
      Notification.requestPermission().then(permission => {
        if (permission === 'granted') {
          showBrowserNotification(title, body, type);
        }
      });
    }
  };

  // 按章节号排序并按大纲分组章节 (必须在早返回之前调用，避免违反 Hooks 规则)
  const { sortedChapters } = useMemo(() => {
    const sorted = [...chapters].sort((a, b) => a.chapter_number - b.chapter_number);

    const groups: Record<string, {
      outlineId: string | null;
      outlineTitle: string;
      outlineOrder: number;
      chapters: Chapter[];
    }> = {};

    sorted.forEach(chapter => {
      const key = chapter.outline_id || 'uncategorized';

      if (!groups[key]) {
        groups[key] = {
          outlineId: chapter.outline_id || null,
          outlineTitle: chapter.outline_title || '未分类章节',
          outlineOrder: chapter.outline_order ?? 999,
          chapters: []
        };
      }

      groups[key].chapters.push(chapter);
    });

    return { sortedChapters: sorted };
  }, [chapters]);

  // 章节查询过滤（前端过滤，减少渲染压力）
  const filteredSortedChapters = useMemo(() => {
    const keyword = chapterSearchKeyword.trim().toLowerCase();
    if (!keyword) return sortedChapters;

    return sortedChapters.filter((chapter) => {
      return (
        String(chapter.chapter_number).includes(keyword) ||
        chapter.title.toLowerCase().includes(keyword) ||
        (chapter.outline_title || '').toLowerCase().includes(keyword)
      );
    });
  }, [sortedChapters, chapterSearchKeyword]);

  // 分页后的扁平章节
  const pagedSortedChapters = useMemo(() => {
    const start = (chapterPage - 1) * chapterPageSize;
    return filteredSortedChapters.slice(start, start + chapterPageSize);
  }, [filteredSortedChapters, chapterPage, chapterPageSize]);

  // one-to-many 模式分页后再按大纲分组
  const pagedGroupedChapters = useMemo(() => {
    const groups: Record<string, {
      outlineId: string | null;
      outlineTitle: string;
      outlineOrder: number;
      chapters: Chapter[];
    }> = {};

    pagedSortedChapters.forEach(chapter => {
      const key = chapter.outline_id || 'uncategorized';
      if (!groups[key]) {
        groups[key] = {
          outlineId: chapter.outline_id || null,
          outlineTitle: chapter.outline_title || '未分类章节',
          outlineOrder: chapter.outline_order ?? 999,
          chapters: []
        };
      }
      groups[key].chapters.push(chapter);
    });

    return Object.values(groups).sort((a, b) => a.outlineOrder - b.outlineOrder);
  }, [pagedSortedChapters]);

  // 搜索词或分页大小变化时重置到第一页
  useEffect(() => {
    setChapterPage(1);
  }, [chapterSearchKeyword, chapterPageSize, currentProject?.outline_mode]);

  // 数据变化导致页码越界时自动纠正
  useEffect(() => {
    const maxPage = Math.max(1, Math.ceil(filteredSortedChapters.length / chapterPageSize));
    if (chapterPage > maxPage) {
      setChapterPage(maxPage);
    }
  }, [filteredSortedChapters.length, chapterPage, chapterPageSize]);

  // 预计算每章可生成状态，避免在渲染阶段重复 O(n²) 扫描
  const chapterGenerateGateMap = useMemo(() => {
    const gateMap: Record<string, { canGenerate: boolean; reason: string }> = {};
    const incompleteChapterNumbers: number[] = [];
    const unanalyzedChapters: Array<{ chapterNumber: number; reason: string }> = [];

    sortedChapters.forEach((chapter) => {
      if (incompleteChapterNumbers.length > 0) {
        gateMap[chapter.id] = {
          canGenerate: false,
          reason: `需要先完成前置章节：第 ${incompleteChapterNumbers.join('、')} 章`
        };
      } else if (unanalyzedChapters.length > 0) {
        gateMap[chapter.id] = {
          canGenerate: false,
          reason: `需要先分析前置章节：第 ${unanalyzedChapters.map(c => c.chapterNumber).join('、')} 章 (${unanalyzedChapters.map(c => c.reason).join('、')})`
        };
      } else {
        gateMap[chapter.id] = { canGenerate: true, reason: '' };
      }

      // 将当前章纳入“后续章节”的前置条件
      if (!chapter.content || chapter.content.trim() === '') {
        incompleteChapterNumbers.push(chapter.chapter_number);
      }

      const task = analysisTasksMap[chapter.id];
      if (!task || !task.has_task) {
        unanalyzedChapters.push({ chapterNumber: chapter.chapter_number, reason: '未分析' });
      } else if (task.status === 'pending') {
        unanalyzedChapters.push({ chapterNumber: chapter.chapter_number, reason: '等待分析' });
      } else if (task.status === 'running') {
        unanalyzedChapters.push({ chapterNumber: chapter.chapter_number, reason: '分析中' });
      } else if (task.status === 'failed') {
        unanalyzedChapters.push({ chapterNumber: chapter.chapter_number, reason: '分析失败' });
      } else if (task.status !== 'completed') {
        unanalyzedChapters.push({ chapterNumber: chapter.chapter_number, reason: '状态未知' });
      }
    });

    return gateMap;
  }, [sortedChapters, analysisTasksMap]);

  // 当前可被“一键分析”的章节（有内容且未处于完成/进行中）
  const batchAnalyzableChapterCount = useMemo(() => {
    return sortedChapters.filter((chapter) => {
      if (!chapter.content || chapter.content.trim() === '') return false;
      const task = analysisTasksMap[chapter.id];
      if (!task || !task.has_task) return true;
      return task.status !== 'completed' && task.status !== 'pending' && task.status !== 'running';
    }).length;
  }, [sortedChapters, analysisTasksMap]);

  const stopComparisonPolling = () => {
    if (comparisonPollingRef.current !== null) {
      window.clearInterval(comparisonPollingRef.current);
      comparisonPollingRef.current = null;
    }
  };

  useEffect(() => () => stopComparisonPolling(), []);

  if (!currentProject) return null;

  // 获取人称的中文显示文本（同时支持中英文值）
  const getNarrativePerspectiveText = (perspective?: string): string => {
    const texts: Record<string, string> = {
      // 英文值映射（向后兼容）
      'first_person': '第一人称（我）',
      'third_person': '第三人称（他/她）',
      'omniscient': '全知视角',
      // 中文值映射（项目设置使用）
      '第一人称': '第一人称（我）',
      '第三人称': '第三人称（他/她）',
      '全知视角': '全知视角',
    };
    return texts[perspective || ''] || '第三人称（默认）';
  };

  const canGenerateChapter = (chapter: Chapter): boolean => {
    return chapterGenerateGateMap[chapter.id]?.canGenerate ?? true;
  };

  const getGenerateDisabledReason = (chapter: Chapter): string => {
    return chapterGenerateGateMap[chapter.id]?.reason || '';
  };

  const handleOpenModal = (id: string) => {
    const chapter = chapters.find(c => c.id === id);
    if (chapter) {
      form.setFieldsValue(chapter);
      setEditingId(id);
      setIsModalOpen(true);
      // 异步加载该章最近的对比批次（批量独立候选预览也能在此查看）
      llmComparisonApi.list({ target_type: 'chapter', target_id: id, limit: 1 })
        .then(res => {
          if (res.items && res.items.length > 0) {
            const latest = res.items[0];
            if (latest.status !== 'draft') {
              setComparisonBatch(latest);
            }
          }
        })
        .catch(() => { /* 无批次则忽略 */ });
    }
  };

  const handleSubmit = async (values: ChapterUpdate) => {
    if (!editingId) return;

    try {
      await updateChapter(editingId, values);

      // 刷新章节列表以获取完整的章节数据（包括outline_title等联查字段）
      await refreshChapters();

      message.success('章节更新成功');
      setIsModalOpen(false);
      form.resetFields();
    } catch {
      message.error('操作失败');
    }
  };

  const handleOpenEditor = (id: string) => {
    const chapter = chapters.find(c => c.id === id);
    if (chapter) {
      setCurrentChapter(chapter);
      editorForm.setFieldsValue({
        title: chapter.title,
        content: chapter.content,
      });
      setEditingId(id);
      setTemporaryNarrativePerspective(undefined); // 重置人称选择
      setSelectedSkillKey(undefined); // 重置Skill选择
      setComparisonBatch(null);
      setComparisonSelections([]);
      stopComparisonPolling();
      setIsEditorOpen(true);
      // 打开编辑窗口时加载模型列表和Skill列表
      loadDefaultSelection();
      loadAvailableSkills();
      llmComparisonApi.list({ project_id: chapter.project_id, target_type: 'chapter', target_id: chapter.id, limit: 1 })
        .then(result => setComparisonBatch(result.items[0] || null))
        .catch(() => setComparisonBatch(null));
    }
  };

  const handleEditorSubmit = async (values: ChapterUpdate) => {
    if (!editingId || !currentProject) return;

    try {
      await updateChapter(editingId, values);

      // 刷新项目信息以更新总字数统计
      const updatedProject = await projectApi.getProject(currentProject.id);
      setCurrentProject(updatedProject);

      message.success('章节保存成功');
      setIsEditorOpen(false);
    } catch {
      message.error('保存失败');
    }
  };

  const handleGenerate = async () => {
    if (!editingId) return;

    try {
      setIsContinuing(true);
      setIsGenerating(true);
      setSingleChapterProgress(0);
      setSingleChapterProgressMessage('准备开始生成...');

      const result = await generateChapterContentStream(
        editingId,
        (content) => {
          editorForm.setFieldsValue({ content });

          if (contentTextAreaRef.current) {
            const textArea = contentTextAreaRef.current.resizableTextArea?.textArea;
            if (textArea) {
              textArea.scrollTop = textArea.scrollHeight;
            }
          }
        },
        selectedStyleId,
        targetWordCount,
        (progressMsg, progressValue) => {
          // 进度回调
          setSingleChapterProgress(progressValue);
          setSingleChapterProgressMessage(progressMsg);
        },
        selectedModel,  // 传递选中的模型
        temporaryNarrativePerspective,  // 传递临时人称参数
        selectedSkillKey,  // 传递选中的Skill
        aiServiceSelection.provider_config_id
      );

      message.success('AI创作成功，正在分析章节内容...');

      // 如果返回了分析任务ID，启动轮询
      if (result?.analysis_task_id) {
        const taskId = result.analysis_task_id;
        setAnalysisTasksMap(prev => ({
          ...prev,
          [editingId]: {
            has_task: true,
            task_id: taskId,
            chapter_id: editingId,
            status: 'pending',
            progress: 0
          }
        }));

        // 启动轮询
        startPollingTask(editingId);
      }
    } catch (error) {
      const apiError = error as ApiError;
      message.error('AI创作失败：' + (apiError.response?.data?.detail || apiError.message || '未知错误'));
    } finally {
      setIsContinuing(false);
      setIsGenerating(false);
      setSingleChapterProgress(0);
      setSingleChapterProgressMessage('');
    }
  };

  const showGenerateModal = (chapter: Chapter) => {
    const previousChapters = chapters.filter(
      c => c.chapter_number < chapter.chapter_number
    ).sort((a, b) => a.chapter_number - b.chapter_number);

    const selectedStyle = writingStyles.find(s => s.id === selectedStyleId);

    const instance = modal.confirm({
      title: 'AI创作章节内容',
      width: 700,
      centered: true,
      content: (
        <div style={{ marginTop: 16 }}>
          <p>AI将根据以下信息创作本章内容：</p>
          <ul>
            <li>章节大纲和要求</li>
            <li>项目的世界观设定</li>
            <li>相关角色信息</li>
            <li><strong>前面已完成章节的内容（确保剧情连贯）</strong></li>
            {selectedStyle && (
              <li><strong>写作风格：{selectedStyle.name}</strong></li>
            )}
            <li><strong>目标字数：{targetWordCount}字</strong></li>
          </ul>

          {previousChapters.length > 0 && (
            <div style={{
              marginTop: 16,
              padding: 12,
              background: token.colorInfoBg,
              borderRadius: token.borderRadius,
              border: `1px solid ${token.colorInfoBorder}`
            }}>
              <div style={{ marginBottom: 8, fontWeight: 500, color: token.colorPrimary }}>
                📚 将引用的前置章节（共{previousChapters.length}章）：
              </div>
              <div style={{ maxHeight: 150, overflowY: 'auto' }}>
                {previousChapters.map(ch => (
                  <div key={ch.id} style={{ padding: '4px 0', fontSize: 13 }}>
                    ✓ 第{ch.chapter_number}章：{ch.title} ({ch.word_count || 0}字)
                  </div>
                ))}
              </div>
              <div style={{ marginTop: 8, fontSize: 12, color: token.colorTextSecondary }}>
                💡 AI会参考这些章节内容，确保情节连贯、角色状态一致
              </div>
            </div>
          )}

          <p style={{ color: token.colorError, marginTop: 16, marginBottom: 0 }}>
            ⚠️ 注意：此操作将覆盖当前章节内容
          </p>
        </div>
      ),
      okText: '开始创作',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        // 流式生成开始 → 切回正文编辑 Tab 看着写入
        setEditorActiveTab('edit');
        instance.update({
          okButtonProps: { danger: true, loading: true },
          cancelButtonProps: { disabled: true },
          closable: false,
          maskClosable: false,
          keyboard: false,
        });

        try {
          if (!selectedStyleId) {
            message.error('请先选择写作风格');
            instance.update({
              okButtonProps: { danger: true, loading: false },
              cancelButtonProps: { disabled: false },
              closable: true,
              maskClosable: true,
              keyboard: true,
            });
            return;
          }
          await handleGenerate();
          instance.destroy();
        } catch {
          instance.update({
            okButtonProps: { danger: true, loading: false },
            cancelButtonProps: { disabled: false },
            closable: true,
            maskClosable: true,
            keyboard: true,
          });
        }
      },
      onCancel: () => {
        if (isGenerating) {
          message.warning('AI正在创作中，请等待完成');
          return false;
        }
      },
    });
  };


  // 后台生成章节（关闭浏览器也不影响）
  // 不再强制显示进度弹窗，任务进度在右下角悬浮任务框中显示
  const handleBackgroundGenerate = async () => {
    if (!editingId) return;
    if (!selectedStyleId) {
      message.error("请先选择写作风格");
      return;
    }
    setEditorActiveTab('edit');
    try {
      await generateChapterBackground(
        editingId,
        {
          style_id: selectedStyleId,
          target_word_count: targetWordCount,
          model: selectedModel,
          narrative_perspective: temporaryNarrativePerspective,
          provider_config_id: aiServiceSelection.provider_config_id,
        },
        () => {
          // 进度更新由悬浮任务框处理，无需额外操作
        },
        () => {
          message.success("后台章节生成完成！");
          refreshChapters();
          if (currentProject) {
            projectApi.getProject(currentProject.id).then(setCurrentProject).catch(console.error);
          }
          loadAnalysisTasks();
        },
        (error) => {
          message.error("后台生成失败: " + error);
        }
      );

      message.info("章节生成任务已提交，可在右下角任务面板查看进度");
      // 通知悬浮任务框刷新
      eventBus.emit('background-task-created');
    } catch {
      message.error("创建后台任务失败");
    }
  };

  const updateComparisonSelection = (index: number, patch: Partial<Pick<LLMComparisonSelection, 'skill_key' | 'target_word_count'>>) => {
    setComparisonSelections(prev => prev.map((item, i) => (i === index ? { ...item, ...patch } : item)));
  };

  const pollComparisonBatch = (batchId: string) => {
    stopComparisonPolling();
    comparisonPollingRef.current = window.setInterval(async () => {
      try {
        const batch = await llmComparisonApi.get(batchId);
        setComparisonBatch(batch);
        if (!['draft', 'queued', 'running'].includes(batch.status)) {
          stopComparisonPolling();
        }
      } catch {
        stopComparisonPolling();
      }
    }, 2000);
  };

  const handleCreateComparison = async () => {
    if (!editingId || comparisonSelections.length < 2) {
      message.warning('请至少选择 2 个不同的 AI 服务/模型');
      return;
    }
    if (!selectedStyleId) {
      message.warning('请先选择写作风格');
      return;
    }
    try {
      setComparisonBusy(true);
      const batch = await chapterApi.createComparison(editingId, {
        selections: comparisonSelections,
        style_id: selectedStyleId,
        target_word_count: targetWordCount,
        narrative_perspective: temporaryNarrativePerspective,
        skill_key: generationMode === 'compare' ? undefined : selectedSkillKey,
        enable_mcp: true,
      });
      setComparisonBatch(batch);
      setComparisonVisible(true);
      pollComparisonBatch(batch.id);
      message.success('多模型比较任务已开始；正式章节暂时不会改变');
    } catch (error) {
      const apiError = error as ApiError;
      message.error(apiError.response?.data?.detail || '创建比较任务失败');
    } finally {
      setComparisonBusy(false);
    }
  };

  const handleRetryCandidate = async (candidate: LLMComparisonCandidate) => {
    if (!editingId || !comparisonBatch) return;
    try {
      await chapterApi.retryComparisonCandidate(editingId, comparisonBatch.id, candidate.id);
      const refreshed = await llmComparisonApi.get(comparisonBatch.id);
      setComparisonBatch(refreshed);
      pollComparisonBatch(comparisonBatch.id);
    } catch (error) {
      const apiError = error as ApiError;
      message.error(apiError.response?.data?.detail || '重试失败');
    }
  };

  const handleAdoptCandidate = (candidate: LLMComparisonCandidate) => {
    if (!editingId || !comparisonBatch) return;
    modal.confirm({
      title: `采用 ${candidate.provider_name} · ${candidate.model} 的版本？`,
      content: '采用后才会覆盖正式章节。其他候选结果仍会保留，方便以后查看。',
      okText: '确认采用',
      cancelText: '暂不采用',
      onOk: async () => {
        try {
          const batch = await chapterApi.adoptComparisonCandidate(editingId, comparisonBatch.id, candidate.id);
          setComparisonBatch(batch);
          editorForm.setFieldsValue({ content: candidate.output_text || '' });
          const latestChapters = await refreshChapters();
          await loadAnalysisTasks(latestChapters, currentProject?.id);
          startPollingTask(editingId);
          if (currentProject) {
            setCurrentProject(await projectApi.getProject(currentProject.id));
          }
          message.success('已采用为正式章节，正在按本书配置分析');
        } catch (error) {
          const apiError = error as ApiError;
          message.error(apiError.response?.data?.detail || '采用失败');
        }
      },
    });
  };

  const openCandidateEditor = (candidate: LLMComparisonCandidate) => {
    if (!editingId || !comparisonBatch) return;
    let text = candidate.output_text || '';
    modal.confirm({
      title: `编辑候选：${candidate.provider_name} · ${candidate.model}`,
      width: 800,
      content: <Input.TextArea defaultValue={text} rows={18} onChange={event => { text = event.target.value; }} />,
      okText: '保存候选',
      cancelText: '取消',
      onOk: async () => {
        const updated = await chapterApi.editComparisonCandidate(editingId, comparisonBatch.id, candidate.id, text);
        setComparisonBatch(current => current ? {
          ...current,
          candidates: current.candidates.map(item => item.id === updated.id ? updated : item),
        } : current);
      },
    });
  };

  const copyCandidate = async (candidate: LLMComparisonCandidate) => {
    await navigator.clipboard.writeText(candidate.output_text || '');
    message.success('候选正文已复制');
  };

  const openCandidateDiff = () => {
    const successful = comparisonBatch?.candidates.filter(item => item.status === 'success') || [];
    if (successful.length < 2) {
      message.info('至少需要两个生成成功的候选才能查看差异');
      return;
    }
    setCandidateDiffIds([successful[0].id, successful[1].id]);
    setCandidateDiffVisible(true);
  };
  const getStatusColor = (status: string) => {
    const colors: Record<string, string> = {
      'draft': 'default',
      'pending': 'warning',
      'writing': 'processing',
      'completed': 'success',
    };
    return colors[status] || 'default';
  };

  const getStatusText = (status: string) => {
    const texts: Record<string, string> = {
      'draft': '草稿',
      'pending': '待处理',
      'writing': '创作中',
      'completed': '已完成',
    };
    return texts[status] || status;
  };

  const handleExport = () => {
    if (chapters.length === 0) {
      message.warning('当前项目没有章节，无法导出');
      return;
    }

    modal.confirm({
      title: '导出项目章节',
      content: `确定要将《${currentProject.title}》的所有章节导出为TXT文件吗？`,
      centered: true,
      okText: '确定导出',
      cancelText: '取消',
      onOk: () => {
        try {
          projectApi.exportProject(currentProject.id);
          message.success('开始下载导出文件');
        } catch {
          message.error('导出失败，请重试');
        }
      },
    });
  };

  const handleShowAnalysis = (chapterId: string) => {
    setAnalysisChapterId(chapterId);
    setAnalysisVisible(true);
  };

  // 一键按章节顺序分析未分析章节
  const handleBatchAnalyzeUnanalyzed = async () => {
    if (!currentProject?.id) return;

    try {
      setBatchAnalyzingUnanalyzed(true);
      const result = await chapterApi.batchAnalyzeUnanalyzed(currentProject.id);

      if (result.total_started > 0) {
        setAnalysisTasksMap((prev) => ({
          ...prev,
          ...result.started_tasks,
        }));

        Object.keys(result.started_tasks).forEach((chapterId) => {
          startPollingTask(chapterId);
        });

        message.success(
          `已加入 ${result.total_started} 章顺序分析队列（跳过已分析 ${result.total_already_completed} 章，分析中/排队中 ${result.total_skipped_running} 章）`
        );
      } else {
        message.info('没有可启动分析的章节：当前章节要么无内容、要么已分析完成、要么正在分析中');
      }

      // 刷新一次状态，确保前端与后端一致
      await loadAnalysisTasks();
    } catch (error: unknown) {
      const err = error as Error;
      message.error(`一键分析失败：${err.message || '未知错误'}`);
    } finally {
      setBatchAnalyzingUnanalyzed(false);
    }
  };

  // 批量生成函数
  const handleBatchGenerate = async (values: {
    startChapterNumber: number;
    count: number;
    enableAnalysis: boolean;
    styleId?: number;
    targetWordCount?: number;
    model?: string;
    skipAnalysisCheck?: boolean;
  }) => {
    if (!currentProject?.id) return;

    // 多模型独立候选预览模式
    if (batchMode === 'compare') {
      if (batchComparisonSelections.length < 2) {
        message.warning('请选择至少 2 个模型用于对比');
        return;
      }
      try {
        setBatchGenerating(true);
        setBatchGenerateVisible(false);
        const resp = await fetch(`/api/chapters/project/${currentProject.id}/batch-compare`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            start_chapter_number: values.startChapterNumber,
            count: values.count,
            selections: batchComparisonSelections,
            style_id: values.styleId || selectedStyleId || undefined,
            target_word_count: values.targetWordCount || targetWordCount,
            enable_mcp: false,
          }),
        });
        if (!resp.ok) {
          const err = await resp.json();
          throw new Error(err.detail || '创建批量候选预览失败');
        }
        const data = await resp.json();
        // 登记到悬浮任务框查看进度
        if (data.task_id) {
          setBatchTaskId(data.task_id);
          setBatchProgress({
            status: 'running',
            total: values.count,
            completed: 0,
            current_chapter_number: values.startChapterNumber,
          });
          startBatchPolling(data.task_id);
          eventBus.emit('background-task-created');
        }
        message.success(data.message || '批量候选预览已创建（右下角任务面板查看进度）');
        console.log('[批量候选预览] 创建结果:', data);
        return;
      } catch (error: unknown) {
        const err = error as Error;
        message.error(err.message || '创建批量候选预览失败');
        return;
      } finally {
        setBatchGenerating(false);
      }
    }

    // 调试日志
    console.log('[批量生成] 表单values:', values);
    console.log('[批量生成] batchAIState状态:', batchAIState);

    // 使用批量生成对话框中选择的风格和字数，如果没有选择则使用默认值
    const styleId = values.styleId || selectedStyleId;
    const wordCount = values.targetWordCount || targetWordCount;

    // 使用批量生成专用的模型状态（统一由 AIServiceSelector 管理）
    const model = batchAIState.model;
    const providerConfigId = batchAIState.provider_config_id;

    console.log('[批量生成] 最终使用的model:', model);

    if (!styleId) {
      message.error('请选择写作风格');
      return;
    }

    try {
      setBatchGenerating(true);
      setBatchGenerateVisible(false); // 关闭配置对话框，任务进度在悬浮任务框中显示

      const requestBody: {
        start_chapter_number: number;
        count: number;
        enable_analysis: boolean;
        skip_analysis_check?: boolean;
        style_id: number;
        target_word_count: number;
        model?: string;
        provider_config_id?: string;
        skill_key?: string;
      } = {
        start_chapter_number: values.startChapterNumber,
        count: values.count,
        enable_analysis: values.enableAnalysis,
        skip_analysis_check: values.skipAnalysisCheck || false,
        style_id: styleId,
        target_word_count: wordCount,
      };

      // 如果有模型参数，添加到请求体中
      if (model) {
        requestBody.model = model;
        console.log('[批量生成] 请求体包含model:', model);
      } else {
        console.log('[批量生成] 请求体不包含model，使用后端默认模型');
      }

      // 如果有 AI 服务配置，添加到请求体中
      if (providerConfigId) {
        requestBody.provider_config_id = providerConfigId;
        console.log('[批量生成] 请求体包含provider_config_id:', providerConfigId);
      }

      // 如果有 Skill 参数，添加到请求体中
      if (batchSelectedSkillKey) {
        requestBody.skill_key = batchSelectedSkillKey;
        console.log('[批量生成] 请求体包含skill_key:', batchSelectedSkillKey);
      }

      console.log('[批量生成] 完整请求体:', JSON.stringify(requestBody, null, 2));

      const response = await fetch(`/api/chapters/project/${currentProject.id}/batch-generate`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestBody),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || '创建批量生成任务失败');
      }

      const result = await response.json();
      setBatchTaskId(result.batch_id);
      setBatchProgress({
        status: 'running',
        total: result.chapters_to_generate.length,
        completed: 0,
        current_chapter_number: values.startChapterNumber,
        estimated_time_minutes: result.estimated_time_minutes,
      });

      message.success(`批量生成任务已创建，预计需要 ${result.estimated_time_minutes} 分钟，可在右下角任务面板查看进度`);
      // 通知悬浮任务框刷新
      eventBus.emit('background-task-created');

      // 🔔 触发浏览器通知（任务开始）
      showBrowserNotification(
        '批量生成已启动',
        `开始生成 ${result.chapters_to_generate.length} 章，预计需要 ${result.estimated_time_minutes} 分钟`,
        'info'
      );

      // 开始轮询任务状态
      startBatchPolling(result.batch_id);

    } catch (error: unknown) {
      const err = error as Error;
      message.error('创建批量生成任务失败：' + (err.message || '未知错误'));
      setBatchGenerating(false);
      setBatchGenerateVisible(false);
    }
  };

  // 轮询批量生成任务状态
  const startBatchPolling = (taskId: string) => {
    if (batchPollingIntervalRef.current) {
      clearInterval(batchPollingIntervalRef.current);
    }

    const poll = async () => {
      try {
        const response = await fetch(`/api/chapters/batch-generate/${taskId}/status`);
        if (!response.ok) return;

        const status = await response.json();
        setBatchProgress({
          status: status.status,
          total: status.total,
          completed: status.completed,
          current_chapter_number: status.current_chapter_number,
        });

        // 每次轮询时刷新章节列表和分析状态，实时显示新生成的章节和分析进度
        // 使用 await 确保获取最新章节列表后再加载分析任务状态
        if (status.completed > 0) {
          const latestChapters = await refreshChapters();
          await loadAnalysisTasks(latestChapters);

          // 刷新项目信息以实时更新总字数统计
          if (currentProject?.id) {
            const updatedProject = await projectApi.getProject(currentProject.id);
            setCurrentProject(updatedProject);
          }
        }

        // 任务完成或失败，停止轮询
        if (status.status === 'completed' || status.status === 'failed' || status.status === 'cancelled') {
          if (batchPollingIntervalRef.current) {
            clearInterval(batchPollingIntervalRef.current);
            batchPollingIntervalRef.current = null;
          }

          setBatchGenerating(false);

          // 立即刷新章节列表和分析任务状态（在显示消息前）
          // 使用 refreshChapters 返回的最新章节列表传递给 loadAnalysisTasks
          const finalChapters = await refreshChapters();
          await loadAnalysisTasks(finalChapters);

          // 刷新项目信息以更新总字数统计
          if (currentProject?.id) {
            const updatedProject = await projectApi.getProject(currentProject.id);
            setCurrentProject(updatedProject);
          }

          if (status.status === 'completed') {
            message.success(`批量生成完成！成功生成 ${status.completed} 章`);
            // 🔔 触发浏览器通知
            showBrowserNotification(
              '批量生成完成',
              `《${currentProject?.title || '项目'}》成功生成 ${status.completed} 章节`,
              'success'
            );
          } else if (status.status === 'failed') {
            message.error(`批量生成失败：${status.error_message || '未知错误'}`);
            // 🔔 触发浏览器通知
            showBrowserNotification(
              '批量生成失败',
              status.error_message || '未知错误',
              'error'
            );
          } else if (status.status === 'cancelled') {
            message.warning('批量生成已取消');
          }

          // 延迟关闭对话框，让用户看到最终状态
          setTimeout(() => {
            setBatchGenerateVisible(false);
            setBatchTaskId(null);
            setBatchProgress(null);
          }, 2000);
        }
      } catch (error) {
        console.error('轮询批量生成状态失败:', error);
      }
    };

    // 立即执行一次
    poll();

    // 每2秒轮询一次
    batchPollingIntervalRef.current = window.setInterval(poll, 2000);
  };

  // 取消批量生成
  const handleCancelBatchGenerate = async () => {
    if (!batchTaskId) return;

    try {
      const response = await fetch(`/api/chapters/batch-generate/${batchTaskId}/cancel`, {
        method: 'POST',
      });

      if (!response.ok) {
        throw new Error('取消失败');
      }

      message.success('批量生成已取消');

      // 取消后立即刷新章节列表和分析任务，显示已生成的章节
      await refreshChapters();
      await loadAnalysisTasks();

      // 刷新项目信息以更新总字数统计
      if (currentProject?.id) {
        const updatedProject = await projectApi.getProject(currentProject.id);
        setCurrentProject(updatedProject);
      }
    } catch (error: unknown) {
      const err = error as Error;
      message.error('取消失败：' + (err.message || '未知错误'));
    }
  };

  // 打开批量生成对话框
  const handleOpenBatchGenerate = async () => {
    // 找到第一个未生成的章节
    const firstIncompleteChapter = sortedChapters.find(
      ch => !ch.content || ch.content.trim() === ''
    );

    if (!firstIncompleteChapter) {
      message.info('所有章节都已生成内容');
      return;
    }

    // 检查该章节是否可以生成
    if (!canGenerateChapter(firstIncompleteChapter)) {
      const reason = getGenerateDisabledReason(firstIncompleteChapter);
      message.warning(reason);
      return;
    }

    // 打开对话框时加载模型列表和Skill列表，等待完成
    const defaultModel = await loadDefaultSelection();
    loadAvailableSkills();

    console.log('[打开批量生成] defaultModel:', defaultModel);
    console.log('[打开批量生成] selectedStyleId:', selectedStyleId);

    // 批量模型选择已由 loadDefaultSelection 预填（batchAIState），无需额外设置

    // 重置表单并设置初始值（使用缓存的字数）
    batchForm.setFieldsValue({
      startChapterNumber: firstIncompleteChapter.chapter_number,
      count: 5,
      enableAnalysis: true,
      styleId: selectedStyleId,
      targetWordCount: getCachedWordCount(),
    });

    setBatchGenerateVisible(true);
  };

  // 手动创建章节(仅one-to-many模式)
  const showManualCreateChapterModal = () => {
    // 计算下一个章节号
    const nextChapterNumber = chapters.length > 0
      ? Math.max(...chapters.map(c => c.chapter_number)) + 1
      : 1;

    modal.confirm({
      title: '手动创建章节',
      width: 600,
      centered: true,
      content: (
        <Form
          form={manualCreateForm}
          layout="vertical"
          initialValues={{
            chapter_number: nextChapterNumber,
            status: 'draft'
          }}
          style={{ marginTop: 16 }}
        >
          <Form.Item
            label="章节序号"
            name="chapter_number"
            rules={[{ required: true, message: '请输入章节序号' }]}
            tooltip="建议按顺序创建章节，确保内容连贯性"
          >
            <InputNumber min={1} style={{ width: '100%' }} placeholder="自动计算的下一个序号" />
          </Form.Item>

          <Form.Item
            label="章节标题"
            name="title"
            rules={[{ required: true, message: '请输入标题' }]}
          >
            <Input placeholder="例如：第一章 初遇" />
          </Form.Item>

          <Form.Item
            label="关联大纲"
            name="outline_id"
            rules={[{ required: true, message: '请选择关联的大纲' }]}
            tooltip="one-to-many模式下，章节必须关联到大纲"
          >
            <Select placeholder="请选择所属大纲">
              {/* 直接使用 store 中的 outlines 数据，而不是从现有章节中提取 */}
              {[...outlines]
                .sort((a, b) => a.order_index - b.order_index)
                .map(outline => (
                  <Select.Option key={outline.id} value={outline.id}>
                    第{outline.order_index}卷：{outline.title}
                  </Select.Option>
                ))}
            </Select>
          </Form.Item>

          <Form.Item
            label="章节摘要（可选）"
            name="summary"
            tooltip="简要描述本章的主要内容和情节发展"
          >
            <TextArea
              rows={4}
              placeholder="简要描述本章内容..."
            />
          </Form.Item>

          <Form.Item
            label="状态"
            name="status"
          >
            <Select>
              <Select.Option value="draft">草稿</Select.Option>
              <Select.Option value="pending">待处理</Select.Option>
              <Select.Option value="writing">创作中</Select.Option>
              <Select.Option value="completed">已完成</Select.Option>
            </Select>
          </Form.Item>
        </Form>
      ),
      okText: '创建',
      cancelText: '取消',
      onOk: async () => {
        const values = await manualCreateForm.validateFields();

        // 检查章节序号是否已存在
        const conflictChapter = chapters.find(
          ch => ch.chapter_number === values.chapter_number
        );

        if (conflictChapter) {
          // 显示冲突提示Modal
          modal.confirm({
            title: '章节序号冲突',
            icon: <InfoCircleOutlined style={{ color: token.colorError }} />,
            width: 500,
            centered: true,
            content: (
              <div>
                <p style={{ marginBottom: 12 }}>
                  第 <strong>{values.chapter_number}</strong> 章已存在：
                </p>
                <div style={{
                  padding: 12,
                  background: token.colorWarningBg,
                  borderRadius: token.borderRadius,
                  border: `1px solid ${token.colorWarningBorder}`,
                  marginBottom: 12
                }}>
                  <div><strong>标题：</strong>{conflictChapter.title}</div>
                  <div><strong>状态：</strong>{getStatusText(conflictChapter.status)}</div>
                  <div><strong>字数：</strong>{conflictChapter.word_count || 0}字</div>
                  {conflictChapter.outline_title && (
                    <div><strong>所属大纲：</strong>{conflictChapter.outline_title}</div>
                  )}
                </div>
                <p style={{ color: token.colorError, marginBottom: 8 }}>
                  ⚠️ 是否删除旧章节并创建新章节？
                </p>
                <p style={{ fontSize: 12, color: token.colorTextSecondary, marginBottom: 0 }}>
                  删除后将无法恢复，章节内容和分析结果都将被删除。
                </p>
              </div>
            ),
            okText: '删除并创建',
            okButtonProps: { danger: true },
            cancelText: '取消',
            onOk: async () => {
              try {
                // 先删除旧章节
                await handleDeleteChapter(conflictChapter.id);

                // 等待一小段时间确保删除完成
                await new Promise(resolve => setTimeout(resolve, 300));

                // 创建新章节
                await chapterApi.createChapter({
                  project_id: currentProject.id,
                  ...values
                });

                message.success('已删除旧章节并创建新章节');
                await refreshChapters();

                // 刷新项目信息以更新字数统计
                const updatedProject = await projectApi.getProject(currentProject.id);
                setCurrentProject(updatedProject);

                manualCreateForm.resetFields();
              } catch (error: unknown) {
                const err = error as Error;
                message.error('操作失败：' + (err.message || '未知错误'));
                throw error;
              }
            }
          });

          // 阻止外层Modal关闭
          return Promise.reject();
        }

        // 没有冲突，直接创建
        try {
          await chapterApi.createChapter({
            project_id: currentProject.id,
            ...values
          });
          message.success('章节创建成功');
          await refreshChapters();

          // 刷新项目信息以更新字数统计
          const updatedProject = await projectApi.getProject(currentProject.id);
          setCurrentProject(updatedProject);

          manualCreateForm.resetFields();
        } catch (error: unknown) {
          const err = error as Error;
          message.error('创建失败：' + (err.message || '未知错误'));
          throw error;
        }
      }
    });
  };

  // 渲染分析状态标签
  const renderAnalysisStatus = (chapterId: string) => {
    const task = analysisTasksMap[chapterId];

    if (!task) {
      return null;
    }

    switch (task.status) {
      case 'pending':
        return (
          <Tag icon={<SyncOutlined spin />} color="processing">
            等待分析
          </Tag>
        );
      case 'running': {
        // 检查是否正在重试（后端会在error_message中包含"重试"信息）
        const isRetrying = task.error_message && task.error_message.includes('重试');
        return (
          <Tag
            icon={<SyncOutlined spin />}
            color={isRetrying ? "warning" : "processing"}
            title={task.error_message || undefined}
          >
            {isRetrying ? `重试中 ${task.progress}%` : `分析中 ${task.progress}%`}
          </Tag>
        );
      }
      case 'completed':
        return (
          <Tag icon={<CheckCircleOutlined />} color="success">
            已分析
          </Tag>
        );
      case 'failed':
        return (
          <Tag icon={<CloseCircleOutlined />} color="error" title={task.error_message || undefined}>
            分析失败
          </Tag>
        );
      default:
        return null;
    }
  };

  // 显示展开规划详情
  const showExpansionPlanModal = (chapter: Chapter) => {
    if (!chapter.expansion_plan) return;

    try {
      const planData: ExpansionPlanData = JSON.parse(chapter.expansion_plan);

      modal.info({
        title: (
          <Space style={{ flexWrap: 'wrap' }}>
            <InfoCircleOutlined style={{ color: token.colorPrimary }} />
            <span style={{ wordBreak: 'break-word' }}>第{chapter.chapter_number}章展开规划</span>
          </Space>
        ),
        width: isMobile ? 'calc(100vw - 32px)' : 800,
        centered: true,
        style: isMobile ? {
          maxWidth: 'calc(100vw - 32px)',
          margin: '0 auto',
          padding: '0 16px'
        } : undefined,
        styles: {
          body: {
            maxHeight: isMobile ? 'calc(100vh - 200px)' : 'calc(80vh - 110px)',
            overflowY: 'auto'
          }
        },
        content: (
          <div style={{ marginTop: 16 }}>
            <Descriptions
              column={1}
              size="small"
              bordered
              labelStyle={{
                whiteSpace: 'normal',
                wordBreak: 'break-word',
                width: isMobile ? '80px' : '100px'
              }}
              contentStyle={{
                whiteSpace: 'normal',
                wordBreak: 'break-word',
                overflowWrap: 'break-word'
              }}
            >
              <Descriptions.Item label="章节标题">
                <strong style={{
                  wordBreak: 'break-word',
                  whiteSpace: 'normal',
                  overflowWrap: 'break-word'
                }}>
                  {chapter.title}
                </strong>
              </Descriptions.Item>
              <Descriptions.Item label="情感基调">
                <Tag
                  color="blue"
                  style={{
                    whiteSpace: 'normal',
                    wordBreak: 'break-word',
                    height: 'auto',
                    lineHeight: '1.5',
                    padding: '4px 8px'
                  }}
                >
                  {planData.emotional_tone}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="冲突类型">
                <Tag
                  color="orange"
                  style={{
                    whiteSpace: 'normal',
                    wordBreak: 'break-word',
                    height: 'auto',
                    lineHeight: '1.5',
                    padding: '4px 8px'
                  }}
                >
                  {planData.conflict_type}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="预估字数">
                <Tag color="green">{planData.estimated_words}字</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="叙事目标">
                <span style={{
                  wordBreak: 'break-word',
                  whiteSpace: 'normal',
                  overflowWrap: 'break-word'
                }}>
                  {planData.narrative_goal}
                </span>
              </Descriptions.Item>
              <Descriptions.Item label="关键事件">
                <Space direction="vertical" size="small" style={{ width: '100%' }}>
                  {planData.key_events.map((event, idx) => (
                    <div
                      key={idx}
                      style={{
                        padding: '4px 0',
                        wordBreak: 'break-word',
                        whiteSpace: 'normal',
                        overflowWrap: 'break-word'
                      }}
                    >
                      <Tag color="purple" style={{ flexShrink: 0 }}>{idx + 1}</Tag>{' '}
                      <span style={{
                        wordBreak: 'break-word',
                        whiteSpace: 'normal',
                        overflowWrap: 'break-word'
                      }}>
                        {event}
                      </span>
                    </div>
                  ))}
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="涉及角色">
                <Space wrap style={{ maxWidth: '100%' }}>
                  {planData.character_focus.map((char, idx) => (
                    <Tag
                      key={idx}
                      color="cyan"
                      style={{
                        whiteSpace: 'normal',
                        wordBreak: 'break-word',
                        height: 'auto',
                        lineHeight: '1.5'
                      }}
                    >
                      {char}
                    </Tag>
                  ))}
                </Space>
              </Descriptions.Item>
              {planData.scenes && planData.scenes.length > 0 && (
                <Descriptions.Item label="场景规划">
                  <Space direction="vertical" size="small" style={{ width: '100%' }}>
                    {planData.scenes.map((scene, idx) => (
                      <Card
                        key={idx}
                        size="small"
                        style={{
                          backgroundColor: token.colorFillQuaternary,
                          maxWidth: '100%',
                          overflow: 'hidden'
                        }}
                      >
                        <div style={{
                          marginBottom: 4,
                          wordBreak: 'break-word',
                          whiteSpace: 'normal',
                          overflowWrap: 'break-word'
                        }}>
                          <strong>📍 地点：</strong>
                          <span style={{
                            wordBreak: 'break-word',
                            whiteSpace: 'normal',
                            overflowWrap: 'break-word'
                          }}>
                            {scene.location}
                          </span>
                        </div>
                        <div style={{ marginBottom: 4 }}>
                          <strong>👥 角色：</strong>
                          <Space
                            size="small"
                            wrap
                            style={{
                              marginLeft: isMobile ? 0 : 8,
                              marginTop: isMobile ? 4 : 0,
                              display: isMobile ? 'flex' : 'inline-flex'
                            }}
                          >
                            {scene.characters.map((char, charIdx) => (
                              <Tag
                                key={charIdx}
                                style={{
                                  whiteSpace: 'normal',
                                  wordBreak: 'break-word',
                                  height: 'auto'
                                }}
                              >
                                {char}
                              </Tag>
                            ))}
                          </Space>
                        </div>
                        <div style={{
                          wordBreak: 'break-word',
                          whiteSpace: 'normal',
                          overflowWrap: 'break-word'
                        }}>
                          <strong>🎯 目的：</strong>
                          <span style={{
                            wordBreak: 'break-word',
                            whiteSpace: 'normal',
                            overflowWrap: 'break-word'
                          }}>
                            {scene.purpose}
                          </span>
                        </div>
                      </Card>
                    ))}
                  </Space>
                </Descriptions.Item>
              )}
            </Descriptions>
            <Alert
              message="提示"
              description="这些是AI在大纲展开时生成的规划信息，可以作为创作章节内容时的参考。"
              type="info"
              showIcon
              style={{ marginTop: 16 }}
            />
          </div>
        ),
        okText: '关闭',
      });
    } catch (error) {
      console.error('解析展开规划失败:', error);
      message.error('展开规划数据格式错误');
    }
  };

  // 删除章节处理函数
  const handleDeleteChapter = async (chapterId: string) => {
    try {
      await deleteChapter(chapterId);

      // 刷新章节列表
      await refreshChapters();

      // 刷新项目信息以更新总字数统计
      if (currentProject) {
        const updatedProject = await projectApi.getProject(currentProject.id);
        setCurrentProject(updatedProject);
      }

      message.success('章节删除成功');
    } catch (error: unknown) {
      const err = error as Error;
      message.error('删除章节失败：' + (err.message || '未知错误'));
    }
  };

  // 删除全部章节（保留大纲）
  const handleDeleteAllChapters = () => {
    const total = chapters.length;
    if (total === 0) {
      message.info('当前没有可删除的章节');
      return;
    }
    Modal.confirm({
      title: '确认删除全部章节？',
      icon: <ExclamationCircleOutlined />,
      centered: true,
      content: (
        <div>
          <p>此操作将删除当前项目的全部 <strong>{total}</strong> 个章节。</p>
          <p style={{ color: token.colorPrimary, marginTop: 8 }}>📝 大纲会保留，之后可以重新展开。</p>
          <p style={{ color: token.colorError, marginTop: 8 }}>
            ⚠️ 章节正文、分析结果、相关伏笔与向量记忆将永久删除且无法恢复！
          </p>
        </div>
      ),
      okText: '确认全部删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          const res = await chapterApi.deleteAllChapters(currentProject.id);
          // 刷新章节列表
          await refreshChapters();
          // 刷新项目信息以更新总字数统计
          if (currentProject) {
            const updatedProject = await projectApi.getProject(currentProject.id);
            setCurrentProject(updatedProject);
          }
          message.success(res.message || '章节全部删除成功');
        } catch (error: unknown) {
          const err = error as Error;
          message.error('删除全部章节失败：' + (err.message || '未知错误'));
        }
      },
    });
  };

  // 打开规划编辑器
  const handleOpenPlanEditor = (chapter: Chapter) => {
    // 直接打开编辑器,如果没有规划数据则创建新的
    setEditingPlanChapter(chapter);
    setPlanEditorVisible(true);
  };

  // 保存规划信息
  const handleSavePlan = async (planData: ExpansionPlanData) => {
    if (!editingPlanChapter) return;

    try {
      const response = await fetch(`/api/chapters/${editingPlanChapter.id}/expansion-plan`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(planData),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || '更新失败');
      }

      // 刷新章节列表
      await refreshChapters();

      message.success('规划信息更新成功');

      // 关闭编辑器
      setPlanEditorVisible(false);
      setEditingPlanChapter(null);
    } catch (error: unknown) {
      const err = error as Error;
      message.error('保存规划失败：' + (err.message || '未知错误'));
      throw error;
    }
  };

  // 打开阅读器
  const handleOpenReader = (chapter: Chapter) => {
    setReadingChapter(chapter);
    setReaderVisible(true);
  };

  // 阅读器切换章节
  const handleReaderChapterChange = async (chapterId: string) => {
    try {
      const response = await fetch(`/api/chapters/${chapterId}`);
      if (!response.ok) throw new Error('获取章节失败');
      const newChapter = await response.json();
      setReadingChapter(newChapter);
    } catch {
      message.error('加载章节失败');
    }
  };

  // 打开局部重写弹窗
  const handleOpenPartialRegenerate = () => {
    setPartialRegenerateToolbarVisible(false);
    setPartialRegenerateModalVisible(true);
  };

  // 应用局部重写结果
  const handleApplyPartialRegenerate = (newText: string, startPos: number, endPos: number) => {
    // 获取当前内容
    const currentContent = editorForm.getFieldValue('content') || '';
    
    // 替换选中部分
    const newContent = currentContent.substring(0, startPos) + newText + currentContent.substring(endPos);
    
    // 更新表单
    editorForm.setFieldsValue({ content: newContent });
    
    // 关闭弹窗
    setPartialRegenerateModalVisible(false);
    
    message.success('局部重写已应用');
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {contextHolder}
      <div style={{
        position: 'sticky',
        top: 0,
        zIndex: 10,
        backgroundColor: token.colorBgContainer,
        padding: isMobile ? '12px 0' : '16px 0',
        marginBottom: isMobile ? 12 : 16,
        borderBottom: `1px solid ${token.colorBorderSecondary}`,
        display: 'flex',
        flexDirection: isMobile ? 'column' : 'row',
        gap: isMobile ? 12 : 0,
        justifyContent: 'space-between',
        alignItems: isMobile ? 'stretch' : 'center'
      }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <h2 style={{ margin: 0, fontSize: isMobile ? 18 : 24 }}>
            <BookOutlined style={{ marginRight: 8 }} />
            章节管理
          </h2>
          <Tag
            color={currentProject.outline_mode === 'one-to-one' ? 'blue' : 'green'}
            style={{ width: 'fit-content' }}
          >
            {currentProject.outline_mode === 'one-to-one'
              ? '传统模式：章节由大纲管理，请在大纲页面操作'
              : '细化模式：章节可在大纲页面展开'}
          </Tag>
        </div>
        <Space direction={isMobile ? 'vertical' : 'horizontal'} style={{ width: isMobile ? '100%' : 'auto' }}>
          <Input.Search
            allowClear
            placeholder="搜索章节（序号/标题/大纲）"
            value={chapterSearchKeyword}
            onChange={(e) => setChapterSearchKeyword(e.target.value)}
            style={{ width: isMobile ? '100%' : 280 }}
          />
          {currentProject.outline_mode === 'one-to-many' && (
            <Button
              icon={<PlusOutlined />}
              onClick={showManualCreateChapterModal}
              block={isMobile}
              size={isMobile ? 'middle' : 'middle'}
            >
              手动创建
            </Button>
          )}
          <Button
            type="primary"
            icon={<ThunderboltOutlined />}
            onClick={handleBatchAnalyzeUnanalyzed}
            loading={batchAnalyzingUnanalyzed}
            disabled={chapters.length === 0 || batchAnalyzableChapterCount === 0}
            block={isMobile}
            size={isMobile ? 'middle' : 'middle'}
            style={{ background: token.colorWarning, borderColor: token.colorWarning }}
            title={batchAnalyzableChapterCount === 0 ? '暂无可一键分析章节' : `可一键分析 ${batchAnalyzableChapterCount} 章`}
          >
            一键分析{batchAnalyzableChapterCount > 0 ? ` (${batchAnalyzableChapterCount})` : ''}
          </Button>
          <Button
            type="primary"
            icon={<RocketOutlined />}
            onClick={handleOpenBatchGenerate}
            disabled={chapters.length === 0 || batchGenerating}
            loading={batchGenerating}
            block={isMobile}
            size={isMobile ? 'middle' : 'middle'}
            style={batchGenerating ? {} : { background: token.colorInfo, borderColor: token.colorInfo }}
          >
            {batchGenerating ? '生成中...' : '批量生成'}
          </Button>
          <Button
            danger
            icon={<DeleteOutlined />}
            onClick={handleDeleteAllChapters}
            disabled={chapters.length === 0}
            block={isMobile}
            size={isMobile ? 'middle' : 'middle'}
          >
            全部删除
          </Button>
          <Button
            type="default"
            icon={<DownloadOutlined />}
            onClick={handleExport}
            disabled={chapters.length === 0}
            block={isMobile}
            size={isMobile ? 'middle' : 'middle'}
          >
            导出为TXT
          </Button>
        </Space>
      </div>


      <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
        {chapters.length === 0 ? (
          <Empty description="还没有章节，开始创作吧！" />
        ) : filteredSortedChapters.length === 0 ? (
          <Empty description="未找到匹配章节" />
        ) : currentProject.outline_mode === 'one-to-one' ? (
          // one-to-one 模式：直接显示扁平列表
          <List
            dataSource={pagedSortedChapters}
            renderItem={(item) => (
              <List.Item
                id={`chapter-item-${item.id}`}
                style={{
                  padding: '16px',
                  marginBottom: 16,
                  background: token.colorBgContainer,
                  borderRadius: token.borderRadius,
                  border: `1px solid ${token.colorBorderSecondary}`,
                  flexDirection: isMobile ? 'column' : 'row',
                  alignItems: isMobile ? 'flex-start' : 'center',
                }}
                actions={isMobile ? undefined : [
                  <Button
                    type="text"
                    icon={<ReadOutlined />}
                    onClick={() => handleOpenReader(item)}
                    disabled={!item.content || item.content.trim() === ''}
                    title={!item.content || item.content.trim() === '' ? '暂无内容' : '沉浸式阅读'}
                  >
                    阅读
                  </Button>,
                  <Button
                    type="text"
                    icon={<EditOutlined />}
                    onClick={() => handleOpenEditor(item.id)}
                  >
                    编辑
                  </Button>,
                  (() => {
                    const task = analysisTasksMap[item.id];
                    const isAnalyzing = task && (task.status === 'pending' || task.status === 'running');
                    const hasContent = item.content && item.content.trim() !== '';

                    return (
                      <Button
                        type="text"
                        icon={isAnalyzing ? <SyncOutlined spin /> : <FundOutlined />}
                        onClick={() => handleShowAnalysis(item.id)}
                        disabled={!hasContent || isAnalyzing}
                        loading={isAnalyzing}
                        title={
                          !hasContent ? '请先生成章节内容' :
                            isAnalyzing ? '分析进行中，请稍候...' :
                              ''
                        }
                      >
                        {isAnalyzing ? '分析中' : '分析'}
                      </Button>
                    );
                  })(),
                  (() => {
                    const review = reviewRecords[item.id];
                    const hasContent = item.content && item.content.trim() !== '';
                    return (
                      <Button
                        type="text"
                        icon={<SearchOutlined />}
                        onClick={() => {
                          setReviewModal(review || null);
                          setReviewModalTitle(item.title);
                        }}
                        disabled={!hasContent}
                        title={!hasContent ? '请先生成章节内容' : '查看该章最近一次审查报告'}
                      >
                        {review && review.problems.length > 0
                          ? `审查 ${review.problems.length} 个问题`
                          : review
                            ? '审查 ✓'
                            : '审查'}
                      </Button>
                    );
                  })(),
                  <Button
                    type="text"
                    icon={<SettingOutlined />}
                    onClick={() => handleOpenModal(item.id)}
                  >
                    修改
                  </Button>,
                ]}
              >
                <div style={{ width: '100%' }}>
                  <List.Item.Meta
                    avatar={!isMobile && <FileTextOutlined style={{ fontSize: 32, color: token.colorPrimary }} />}
                    title={
                      <div style={{
                        display: 'flex',
                        flexDirection: isMobile ? 'column' : 'row',
                        alignItems: isMobile ? 'flex-start' : 'center',
                        gap: isMobile ? 6 : 12,
                        width: '100%'
                      }}>
                        <span style={{ fontSize: isMobile ? 14 : 16, fontWeight: 500, flexShrink: 0 }}>
                          第{item.chapter_number}章：{item.title}
                        </span>
                        <Space wrap size={isMobile ? 4 : 8}>
                          <Tag color={getStatusColor(item.status)}>{getStatusText(item.status)}</Tag>
                          <Badge count={`${item.word_count || 0}字`} style={{ backgroundColor: token.colorSuccess }} />
                          {renderAnalysisStatus(item.id)}
                          {!canGenerateChapter(item) && (
                            <Tag icon={<LockOutlined />} color="warning" title={getGenerateDisabledReason(item)}>
                              需前置章节
                            </Tag>
                          )}
                        </Space>
                      </div>
                    }
                    description={
                      item.content ? (
                        <div style={{ marginTop: 8, color: token.colorTextSecondary, lineHeight: 1.6, fontSize: isMobile ? 12 : 14 }}>
                          {item.content.substring(0, isMobile ? 80 : 150)}
                          {item.content.length > (isMobile ? 80 : 150) && '...'}
                        </div>
                      ) : (
                        <span style={{ color: token.colorTextTertiary, fontSize: isMobile ? 12 : 14 }}>暂无内容</span>
                      )
                    }
                  />

                  {isMobile && (
                    <Space style={{ marginTop: 12, width: '100%', justifyContent: 'flex-end' }} wrap>
                      <Button
                        type="text"
                        icon={<ReadOutlined />}
                        onClick={() => handleOpenReader(item)}
                        size="small"
                        disabled={!item.content || item.content.trim() === ''}
                        title={!item.content || item.content.trim() === '' ? '暂无内容' : '阅读'}
                      />
                      <Button
                        type="text"
                        icon={<EditOutlined />}
                        onClick={() => handleOpenEditor(item.id)}
                        size="small"
                        title="编辑"
                      />
                      {(() => {
                        const task = analysisTasksMap[item.id];
                        const isAnalyzing = task && (task.status === 'pending' || task.status === 'running');
                        const hasContent = item.content && item.content.trim() !== '';

                        return (
                          <Button
                            type="text"
                            icon={isAnalyzing ? <SyncOutlined spin /> : <FundOutlined />}
                            onClick={() => handleShowAnalysis(item.id)}
                            size="small"
                            disabled={!hasContent || isAnalyzing}
                            loading={isAnalyzing}
                            title={
                              !hasContent ? '请先生成章节内容' :
                                isAnalyzing ? '分析中' :
                                  '分析'
                            }
                          />
                        );
                      })()}
                      <Button
                        type="text"
                        icon={<SettingOutlined />}
                        onClick={() => handleOpenModal(item.id)}
                        size="small"
                        title="修改"
                      />
                    </Space>
                  )}
                </div>
              </List.Item>
            )}
          />
        ) : (
          // one-to-many 模式：按大纲分组显示
          <Collapse
            bordered={false}
            defaultActiveKey={pagedGroupedChapters.length > 0 ? ['0'] : []}
            destroyInactivePanel
            expandIcon={({ isActive }) => <CaretRightOutlined rotate={isActive ? 90 : 0} />}
            style={{ background: 'transparent' }}
          >
            {pagedGroupedChapters.map((group, groupIndex) => (
              <Collapse.Panel
                key={groupIndex.toString()}
                header={
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <Tag color={group.outlineId ? 'blue' : 'default'} style={{ margin: 0 }}>
                      {group.outlineId ? `📖 大纲 ${group.outlineOrder}` : '📝 未分类'}
                    </Tag>
                    <span style={{ fontWeight: 600, fontSize: 16 }}>
                      {group.outlineTitle}
                    </span>
                    <Badge
                      count={`${group.chapters.length} 章`}
                      style={{ backgroundColor: token.colorSuccess }}
                    />
                    <Badge
                      count={`${group.chapters.reduce((sum, ch) => sum + (ch.word_count || 0), 0)} 字`}
                      style={{ backgroundColor: token.colorPrimary }}
                    />
                  </div>
                }
                style={{
                  marginBottom: 16,
                  background: token.colorBgContainer,
                  borderRadius: token.borderRadius,
                  border: `1px solid ${token.colorBorderSecondary}`,
                }}
              >
                <List
                  dataSource={group.chapters}
                  renderItem={(item) => (
                    <List.Item
                      id={`chapter-item-${item.id}`}
                      style={{
                        padding: '16px 0',
                        borderRadius: 8,
                        transition: 'background 0.3s ease',
                        flexDirection: isMobile ? 'column' : 'row',
                        alignItems: isMobile ? 'flex-start' : 'center',
                      }}
                      actions={isMobile ? undefined : [
                        <Button
                          type="text"
                          icon={<ReadOutlined />}
                          onClick={() => handleOpenReader(item)}
                          disabled={!item.content || item.content.trim() === ''}
                          title={!item.content || item.content.trim() === '' ? '暂无内容' : '沉浸式阅读'}
                        >
                          阅读
                        </Button>,
                        <Button
                          type="text"
                          icon={<EditOutlined />}
                          onClick={() => handleOpenEditor(item.id)}
                        >
                          编辑
                        </Button>,
                        (() => {
                          const task = analysisTasksMap[item.id];
                          const isAnalyzing = task && (task.status === 'pending' || task.status === 'running');
                          const hasContent = item.content && item.content.trim() !== '';

                          return (
                            <Button
                              type="text"
                              icon={isAnalyzing ? <SyncOutlined spin /> : <FundOutlined />}
                              onClick={() => handleShowAnalysis(item.id)}
                              disabled={!hasContent || isAnalyzing}
                              loading={isAnalyzing}
                              title={
                                !hasContent ? '请先生成章节内容' :
                                  isAnalyzing ? '分析进行中，请稍候...' :
                                    ''
                              }
                            >
                              {isAnalyzing ? '分析中' : '分析'}
                            </Button>
                          );
                        })(),
                        <Button
                          type="text"
                          icon={<SettingOutlined />}
                          onClick={() => handleOpenModal(item.id)}
                        >
                          修改
                        </Button>,
                        // 只在 one-to-many 模式下显示删除按钮
                        ...(currentProject.outline_mode === 'one-to-many' ? [
                          <Popconfirm
                            title="确定删除这个章节吗？"
                            description="删除后将无法恢复，章节内容和分析结果都将被删除。"
                            onConfirm={() => handleDeleteChapter(item.id)}
                            okText="确定删除"
                            cancelText="取消"
                            okButtonProps={{ danger: true }}
                          >
                            <Button
                              type="text"
                              danger
                              icon={<DeleteOutlined />}
                            >
                              删除
                            </Button>
                          </Popconfirm>
                        ] : []),
                      ]}
                    >
                      <div style={{ width: '100%' }}>
                        <List.Item.Meta
                          avatar={!isMobile && <FileTextOutlined style={{ fontSize: 32, color: token.colorPrimary }} />}
                          title={
                            <div style={{
                              display: 'flex',
                              flexDirection: isMobile ? 'column' : 'row',
                              alignItems: isMobile ? 'flex-start' : 'center',
                              gap: isMobile ? 6 : 12,
                              width: '100%'
                            }}>
                              <span style={{ fontSize: isMobile ? 14 : 16, fontWeight: 500, flexShrink: 0 }}>
                                第{item.chapter_number}章：{item.title}
                              </span>
                              <Space wrap size={isMobile ? 4 : 8}>
                                <Tag color={getStatusColor(item.status)}>{getStatusText(item.status)}</Tag>
                                <Badge count={`${item.word_count || 0}字`} style={{ backgroundColor: token.colorSuccess }} />
                                {renderAnalysisStatus(item.id)}
                                {!canGenerateChapter(item) && (
                                  <Tag icon={<LockOutlined />} color="warning" title={getGenerateDisabledReason(item)}>
                                    需前置章节
                                  </Tag>
                                )}
                                <Space size={4}>
                                  {item.expansion_plan && (
                                    <InfoCircleOutlined
                                      title="查看展开详情"
                                      style={{ color: token.colorPrimary, cursor: 'pointer', fontSize: 16 }}
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        showExpansionPlanModal(item);
                                      }}
                                    />
                                  )}
                                  <FormOutlined
                                    title={item.expansion_plan ? "编辑规划信息" : "创建规划信息"}
                                    style={{ color: token.colorSuccess, cursor: 'pointer', fontSize: 16 }}
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      handleOpenPlanEditor(item);
                                    }}
                                  />
                                </Space>
                              </Space>
                            </div>
                          }
                          description={
                            item.content ? (
                              <div style={{ marginTop: 8, color: token.colorTextSecondary, lineHeight: 1.6, fontSize: isMobile ? 12 : 14 }}>
                                {item.content.substring(0, isMobile ? 80 : 150)}
                                {item.content.length > (isMobile ? 80 : 150) && '...'}
                              </div>
                            ) : (
                              <span style={{ color: token.colorTextTertiary, fontSize: isMobile ? 12 : 14 }}>暂无内容</span>
                            )
                          }
                        />

                        {isMobile && (
                          <Space style={{ marginTop: 12, width: '100%', justifyContent: 'flex-end' }} wrap>
                            <Button
                              type="text"
                              icon={<ReadOutlined />}
                              onClick={() => handleOpenReader(item)}
                              size="small"
                              disabled={!item.content || item.content.trim() === ''}
                              title={!item.content || item.content.trim() === '' ? '暂无内容' : '阅读'}
                            />
                            <Button
                              type="text"
                              icon={<EditOutlined />}
                              onClick={() => handleOpenEditor(item.id)}
                              size="small"
                              title="编辑"
                            />
                            {(() => {
                              const task = analysisTasksMap[item.id];
                              const isAnalyzing = task && (task.status === 'pending' || task.status === 'running');
                              const hasContent = item.content && item.content.trim() !== '';

                              return (
                                <Button
                                  type="text"
                                  icon={isAnalyzing ? <SyncOutlined spin /> : <FundOutlined />}
                                  onClick={() => handleShowAnalysis(item.id)}
                                  size="small"
                                  disabled={!hasContent || isAnalyzing}
                                  loading={isAnalyzing}
                                  title={
                                    !hasContent ? '请先生成章节内容' :
                                      isAnalyzing ? '分析中' :
                                        '分析'
                                  }
                                />
                              );
                            })()}
                            <Button
                              type="text"
                              icon={<SettingOutlined />}
                              onClick={() => handleOpenModal(item.id)}
                              size="small"
                              title="修改"
                            />
                            {/* 只在 one-to-many 模式下显示删除按钮 */}
                            {currentProject.outline_mode === 'one-to-many' && (
                              <Popconfirm
                                title="确定删除？"
                                description="删除后无法恢复"
                                onConfirm={() => handleDeleteChapter(item.id)}
                                okText="删除"
                                cancelText="取消"
                                okButtonProps={{ danger: true }}
                              >
                                <Button
                                  type="text"
                                  danger
                                  icon={<DeleteOutlined />}
                                  size="small"
                                  title="删除章节"
                                />
                              </Popconfirm>
                            )}
                          </Space>
                        )}
                      </div>
                    </List.Item>
                  )}
                />
              </Collapse.Panel>
            ))}
          </Collapse>
        )}
      </div>

      {filteredSortedChapters.length > 0 && (
        <div style={{ paddingTop: 12, display: 'flex', justifyContent: 'flex-end' }}>
          <Pagination
            current={chapterPage}
            pageSize={chapterPageSize}
            total={filteredSortedChapters.length}
            showSizeChanger
            pageSizeOptions={['10', '20', '50', '100']}
            onChange={(page, size) => {
              setChapterPage(page);
              if (size !== chapterPageSize) {
                setChapterPageSize(size);
                setChapterPage(1);
              }
            }}
            showTotal={(total) => `共 ${total} 条`}
            size={isMobile ? 'small' : 'default'}
          />
        </div>
      )}

      <Modal
        title={editingId ? '编辑章节信息' : '添加章节'}
        open={isModalOpen}
        onCancel={() => setIsModalOpen(false)}
        footer={null}
        centered
        width={isMobile ? 'calc(100vw - 32px)' : 520}
        style={isMobile ? {
          maxWidth: 'calc(100vw - 32px)',
          margin: '0 auto',
          padding: '0 16px'
        } : undefined}
        styles={{
          body: {
            maxHeight: isMobile ? 'calc(100vh - 200px)' : 'calc(80vh - 110px)',
            overflowY: 'auto'
          }
        }}
      >
        <Form form={form} layout="vertical" onFinish={handleSubmit}>
          <Form.Item
            label="章节标题"
            name="title"
            tooltip={
              currentProject.outline_mode === 'one-to-one'
                ? "章节标题由大纲管理，请在大纲页面修改"
                : "一对多模式下可以修改章节标题"
            }
            rules={
              currentProject.outline_mode === 'one-to-many'
                ? [{ required: true, message: '请输入章节标题' }]
                : undefined
            }
          >
            <Input
              placeholder="输入章节标题"
              disabled={currentProject.outline_mode === 'one-to-one'}
            />
          </Form.Item>

          <Form.Item
            label="章节序号"
            name="chapter_number"
            tooltip="章节序号不允许修改，请删除对应大纲，重新生成"
          >
            <Input type="number" placeholder="章节排序序号" disabled />
          </Form.Item>

          <Form.Item label="状态" name="status">
            <Select placeholder="选择状态">
              <Select.Option value="draft">草稿</Select.Option>
              <Select.Option value="pending">待处理</Select.Option>
              <Select.Option value="writing">创作中</Select.Option>
              <Select.Option value="completed">已完成</Select.Option>
            </Select>
          </Form.Item>

          <Form.Item>
            <Space style={{ float: 'right' }}>
              <Button onClick={() => setIsModalOpen(false)}>取消</Button>
              <Button type="primary" htmlType="submit">
                更新
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="编辑章节内容"
        open={isEditorOpen}
        onCancel={() => {
          if (isGenerating) {
            message.warning('AI正在创作中，请等待完成后再关闭');
            return;
          }
          setIsEditorOpen(false);
        }}
        closable={!isGenerating}
        maskClosable={false}
        keyboard={!isGenerating}
        width={isMobile ? 'calc(100vw - 32px)' : '94%'}
        centered
        style={isMobile ? {
          maxWidth: 'calc(100vw - 32px)',
          margin: '0 auto',
          padding: '0 16px'
        } : undefined}
        styles={{
          body: {
            maxHeight: isMobile ? 'calc(100vh - 200px)' : 'calc(100vh - 140px)',
            overflowY: 'auto',
            padding: isMobile ? '16px 12px' : '8px 16px'
          }
        }}
        footer={
          <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
            <Button
              onClick={() => {
                if (isGenerating) {
                  message.warning('AI正在创作中，请等待完成后再关闭');
                  return;
                }
                setIsEditorOpen(false);
              }}
              disabled={isGenerating}
            >
              取消
            </Button>
            <Button
              type="primary"
              htmlType="submit"
              disabled={isGenerating}
              onClick={() => editorForm.submit()}
            >
              保存章节
            </Button>
          </Space>
        }
      >
        <Form form={editorForm} layout="vertical" onFinish={handleEditorSubmit}>
          <Tabs
            activeKey={editorActiveTab}
            onChange={setEditorActiveTab}
            size="small"
            items={[
              {
                key: 'edit',
                label: '📝 正文编辑',
                forceRender: true,
                children: (
                  <>
          {/* 📋 本章章纲（来自大纲展开，写作时对照查看） */}
          {editingId && (() => {
            const ch = chapters.find(c => c.id === editingId);
            if (!ch?.expansion_plan) return null;
            try {
              const plan = JSON.parse(ch.expansion_plan) as ExpansionPlanData;
              return (
                <Collapse
                  defaultActiveKey={['plan']}
                  size="small"
                  style={{ marginBottom: 12, background: token.colorFillQuaternary }}
                  items={[{
                    key: 'plan',
                    label: (
                      <Space wrap>
                        <BookOutlined />
                        <span style={{ fontWeight: 500 }}>本章章纲</span>
                        {plan.estimated_words ? <Tag color="blue">预计 {plan.estimated_words} 字</Tag> : null}
                        {plan.emotional_tone ? <Tag color="green">{plan.emotional_tone}</Tag> : null}
                      </Space>
                    ),
                    children: (
                      <Space direction="vertical" size={8} style={{ width: '100%' }}>
                        {plan.narrative_goal && (
                          <div style={{ fontSize: 13, lineHeight: 1.8 }}>
                            <strong>🎯 叙事目标：</strong>{plan.narrative_goal}
                          </div>
                        )}
                        {plan.key_events && plan.key_events.length > 0 && (
                          <div style={{ fontSize: 13, lineHeight: 1.8 }}>
                            <strong>🔑 关键事件：</strong>
                            <ul style={{ margin: '4px 0 0 18px', padding: 0 }}>
                              {plan.key_events.map((e, i) => <li key={i}>{e}</li>)}
                            </ul>
                          </div>
                        )}
                        {plan.character_focus && plan.character_focus.length > 0 && (
                          <div style={{ fontSize: 13, lineHeight: 1.8 }}>
                            <strong>👤 涉及角色：</strong>
                            {plan.character_focus.map((c, i) => <Tag key={i} style={{ marginLeft: 4 }}>{c}</Tag>)}
                          </div>
                        )}
                        {plan.scenes && plan.scenes.length > 0 && (
                          <div style={{ fontSize: 13, lineHeight: 1.8 }}>
                            <strong>📍 场景：</strong>
                            {plan.scenes.map((s, i) => (
                              <div key={i} style={{ marginLeft: 18, fontSize: 12.5, color: token.colorTextSecondary, lineHeight: 1.8 }}>
                                {typeof s === 'string'
                                  ? s
                                  : `${s.location || ''}${s.characters && s.characters.length ? `（${s.characters.join('、')}）` : ''}${s.purpose ? `：${s.purpose}` : ''}`}
                              </div>
                            ))}
                          </div>
                        )}
                        {plan.conflict_type && (
                          <div style={{ fontSize: 13, lineHeight: 1.8 }}>
                            <strong>⚔️ 冲突类型：</strong>{plan.conflict_type}
                          </div>
                        )}
                      </Space>
                    ),
                  }]}
                />
              );
            } catch {
              return null;
            }
          })()}
          {/* 章节标题和AI创作按钮 */}
          <Form.Item
            label="章节标题"
            tooltip="（1-1模式请在大纲修改，1-N模式请使用修改按钮编辑）"
            style={{ marginBottom: isMobile ? 16 : 12 }}
          >
            <Space.Compact style={{ width: '100%' }}>
              <Form.Item name="title" noStyle>
                <Input disabled style={{ flex: 1 }} />
              </Form.Item>
              {editingId && (() => {
                const currentChapter = chapters.find(c => c.id === editingId);
                const canGenerate = currentChapter ? canGenerateChapter(currentChapter) : false;
                const disabledReason = currentChapter ? getGenerateDisabledReason(currentChapter) : '';

                return (
                  <>
                  <Button
                    type="primary"
                    icon={canGenerate ? <ThunderboltOutlined /> : <LockOutlined />}
                    onClick={() => currentChapter && showGenerateModal(currentChapter)}
                    loading={isContinuing}
                    disabled={!canGenerate}
                    danger={!canGenerate}
                    style={{ fontWeight: 'bold' }}
                    title={!canGenerate ? disabledReason : '根据大纲和前置章节内容创作（流式）'}
                  >
                    {isMobile ? 'AI' : 'AI创作'}
                  </Button>
                  <Button
                    icon={<RocketOutlined />}
                    onClick={handleBackgroundGenerate}
                    disabled={!canGenerate || isContinuing}
                    style={{ fontWeight: 'bold' }}
                    title={!canGenerate ? disabledReason : '后台生成：关闭浏览器也不影响，完成后自动保存'}
                  >
                    {isMobile ? '后台' : '后台生成'}
                  </Button>
                  </>
                );
              })()}
            </Space.Compact>
          </Form.Item>

          <Form.Item label="章节内容" name="content">
            <TextArea
              ref={contentTextAreaRef}
              rows={isMobile ? 12 : 20}
              placeholder="开始写作..."
              style={{ fontFamily: 'monospace', fontSize: isMobile ? 12 : 14 }}
              disabled={isGenerating}
            />
          </Form.Item>

          {/* 局部重写浮动工具栏（跟随正文编辑区） */}
          <div data-partial-regenerate-toolbar>
            <PartialRegenerateToolbar
              visible={partialRegenerateToolbarVisible && !isGenerating}
              position={partialRegenerateToolbarPosition}
              selectedText={selectedTextForRegenerate}
              onRegenerate={handleOpenPartialRegenerate}
            />
          </div>

          </>)}
          , {
            key: 'gen',
            label: '⚡ AI 生成',
            forceRender: true,
            children: (
              <>
          {/* 第一行：写作风格 + 叙事角度 */}
          <div style={{
            display: isMobile ? 'block' : 'flex',
            gap: isMobile ? 0 : 16,
            marginBottom: isMobile ? 0 : 12
          }}>
            <Form.Item
              label="写作风格"
              tooltip="选择AI创作时使用的写作风格"
              required
              style={{ flex: 1, marginBottom: isMobile ? 16 : 0 }}
            >
              <Select
                placeholder="请选择写作风格"
                value={selectedStyleId}
                onChange={setSelectedStyleId}
                disabled={isGenerating}
                status={!selectedStyleId ? 'error' : undefined}
              >
                {writingStyles.map(style => (
                  <Select.Option key={style.id} value={style.id}>
                    {style.name}{style.is_default && ' (默认)'}
                  </Select.Option>
                ))}
              </Select>
              {!selectedStyleId && (
                <div style={{ color: token.colorError, fontSize: 12, marginTop: 4 }}>请选择写作风格</div>
              )}
            </Form.Item>

            <Form.Item
              label="叙事角度"
              tooltip="第一人称(我)代入感强；第三人称(他/她)更客观；全知视角洞悉一切"
              style={{ flex: 1, marginBottom: isMobile ? 16 : 0 }}
            >
              <Select
                placeholder={`项目默认: ${getNarrativePerspectiveText(currentProject?.narrative_perspective)}`}
                value={temporaryNarrativePerspective}
                onChange={setTemporaryNarrativePerspective}
                allowClear
                disabled={isGenerating}
              >
                <Select.Option value="第一人称">第一人称(我)</Select.Option>
                <Select.Option value="第三人称">第三人称(他/她)</Select.Option>
                <Select.Option value="全知视角">全知视角</Select.Option>
              </Select>
              {temporaryNarrativePerspective && (
                <div style={{ color: token.colorSuccess, fontSize: 12, marginTop: 4 }}>
                  ✓ {getNarrativePerspectiveText(temporaryNarrativePerspective)}
                </div>
              )}
            </Form.Item>
          </div>

          {/* 第二行：目标字数 + AI模型 + Skill */}
          <Form.Item label="生成方式" style={{ marginBottom: 12 }}>
            <Segmented
              block
              value={generationMode}
              options={[
                { label: '单模型直接写入', value: 'single' },
                { label: '多模型比较（推荐）', value: 'compare' },
              ]}
              onChange={value => setGenerationMode(value as 'single' | 'compare')}
              disabled={isGenerating || comparisonBusy}
            />
          </Form.Item>
          {generationMode === 'single' ? (
            <AIServiceSelector
              usageType="chapter_write"
              value={{ ...aiServiceSelection, model: selectedModel }}
              onChange={(selection) => {
                setAIServiceSelection(selection);
                setSelectedModel(selection.model);
              }}
              disabled={isGenerating}
            />
          ) : (
            <>
              <LLMMultiSelector
                value={comparisonSelections}
                onChange={(next) => {
                  // 保留已选模型单独配置的 Skill / 字数；新加的模型留空（跟随通用设置）
                  setComparisonSelections(next.map(item => {
                    const prev = comparisonSelections.find(p => p.provider_config_id === item.provider_config_id && p.model === item.model);
                    return prev || item;
                  }));
                }}
                disabled={isGenerating || comparisonBusy}
              />
              {comparisonSelections.length > 0 && (
                <Card size="small" style={{ marginBottom: 12, background: token.colorFillQuaternary }}>
                  <div style={{ fontSize: 12, color: token.colorTextSecondary, marginBottom: 8 }}>
                    每个模型单独设置（可选）：留空 = 不使用 Skill、字数用默认值
                  </div>
                  <Space direction="vertical" style={{ width: '100%' }} size="small">
                    {comparisonSelections.map((selection, index) => {
                      const provider = providers.find(p => p.id === selection.provider_config_id);
                      return (
                        <div key={`${selection.provider_config_id}\u0000${selection.model}`} style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                          <Tag style={{ marginRight: 0, flexShrink: 0, whiteSpace: 'nowrap' }}>{provider?.name || selection.provider_config_id} · {selection.model}</Tag>
                          <Select
                            style={{ width: 260, flexShrink: 0 }}
                            placeholder="不使用 Skill"
                            allowClear
                            showSearch
                            optionFilterProp="label"
                            value={selection.skill_key}
                            disabled={isGenerating || comparisonBusy}
                            onChange={(value) => updateComparisonSelection(index, { skill_key: value })}
                          >
                            {writingSkills.map(skill => (
                              <Select.Option key={skill.template_key} value={skill.template_key} label={skill.template_name}>
                                {skill.template_name}
                              </Select.Option>
                            ))}
                          </Select>
                          <InputNumber
                            style={{ width: 170, flexShrink: 0 }}
                            placeholder="默认字数"
                            min={500}
                            max={10000}
                            step={100}
                            value={selection.target_word_count}
                            disabled={isGenerating || comparisonBusy}
                            onChange={(value) => updateComparisonSelection(index, { target_word_count: value ?? undefined })}
                            formatter={(value) => `${value} 字`}
                            parser={(value) => parseInt(value?.replace(' 字', '') || '0', 10) as unknown as 500}
                          />
                        </div>
                      );
                    })}
                  </Space>
                </Card>
              )}
            </>
          )}
          <div style={{
            display: isMobile ? 'block' : 'flex',
            gap: isMobile ? 0 : 16,
            marginBottom: isMobile ? 16 : 12
          }}>
            {generationMode !== 'compare' && (
              <Form.Item
                label="应用 Skill"
                tooltip="选择一个 Skill 工作流指导 AI 创作，不选则使用标准创作流程"
                style={{ flex: 1, marginBottom: isMobile ? 16 : 0 }}
              >
                <SkillSelector value={selectedSkillKey} onChange={setSelectedSkillKey} disabled={isGenerating} categories={SKILL_CATEGORIES.WRITING} />
              </Form.Item>
            )}

            {generationMode !== 'compare' && (
              <Form.Item
                label="目标字数"
                tooltip="AI生成章节时的目标字数，实际可能略有偏差（修改后会自动记住）"
                style={{ flex: 1, marginBottom: isMobile ? 16 : 0 }}
              >
                <InputNumber
                  min={500}
                  max={10000}
                  step={100}
                  value={targetWordCount}
                  onChange={(value) => {
                    const newValue = value || DEFAULT_WORD_COUNT;
                    setTargetWordCount(newValue);
                    setCachedWordCount(newValue);
                  }}
                  disabled={isGenerating}
                  style={{ width: '100%' }}
                  formatter={(value) => `${value} 字`}
                  parser={(value) => parseInt(value?.replace(' 字', '') || '0', 10) as unknown as 500}
                />
              </Form.Item>
            )}
          </div>

          </>)}
          , {
            key: 'ai-edit',
            label: '🤖 AI 修改',
            forceRender: true,
            children: (
              <>
          {/* 🤖 AI 对话式修改（指令驱动最小修改 → diff 确认） */}
          {editingId && (
            <ChapterAIChatEdit
              chapterId={editingId}
              originalContent={editorForm.getFieldValue('content') || ''}
              onApply={(newContent) => {
                editorForm.setFieldsValue({ content: newContent });
                if (contentTextAreaRef.current) {
                  const textArea = contentTextAreaRef.current.resizableTextArea?.textArea;
                  if (textArea) textArea.scrollTop = 0;
                }
              }}
            />
          )}

          </>)}
          , {
            key: 'compare',
            label: '🔀 多模型比较',
            forceRender: true,
            children: (
              <>
          {generationMode === 'compare' && (
            <Card size="small" style={{ marginBottom: 16 }}>
              <Space wrap>
                <Button
                  type="primary"
                  icon={<ThunderboltOutlined />}
                  loading={comparisonBusy}
                  disabled={comparisonSelections.length < 2 || !editingId}
                  onClick={handleCreateComparison}
                >
                  生成 {comparisonSelections.length || ''} 个候选版本
                </Button>
                {comparisonBatch && (
                  <Button onClick={() => setComparisonVisible(true)}>
                    查看最近比较结果
                  </Button>
                )}
                <span style={{ color: token.colorTextSecondary }}>
                  生成期间不会覆盖上面的正式章节内容
                </span>
              </Space>
            </Card>
          )}

          </>)}
          , ]}>
        </Tabs>
      </Form>
    </Modal>

      {analysisChapterId && (
        <ChapterAnalysis
          chapterId={analysisChapterId}
          visible={analysisVisible}
          onClose={() => {
            setAnalysisVisible(false);

            // 刷新章节列表以显示最新内容
            refreshChapters();

            // 刷新项目信息以更新字数统计
            if (currentProject) {
              projectApi.getProject(currentProject.id)
                .then(updatedProject => {
                  setCurrentProject(updatedProject);
                })
                .catch(error => {
                  console.error('刷新项目信息失败:', error);
                });
            }

            // 延迟500ms后批量刷新分析状态，避免单章接口高频调用
            setTimeout(() => {
              loadAnalysisTasks();
            }, 500);

            setAnalysisChapterId(null);
          }}
        />
      )}

      <ChapterReviewModal
        record={reviewModal}
        chapterTitle={reviewModalTitle}
        projectId={currentProject?.id || ''}
        onClose={() => setReviewModal(null)}
      />

      {/* 批量生成对话框 */}
      <Modal
        title={
          <Space>
            <RocketOutlined style={{ color: token.colorInfo }} />
            <span>批量生成章节内容</span>
          </Space>
        }
        open={batchGenerateVisible}
        onCancel={() => {
          if (batchGenerating) {
            modal.confirm({
              title: '确认取消',
              content: '批量生成正在进行中，确定要取消吗？',
              okText: '确定取消',
              cancelText: '继续生成',
              centered: true,
              onOk: () => {
                handleCancelBatchGenerate();
                setBatchGenerateVisible(false);
              },
            });
          } else {
            setBatchGenerateVisible(false);
          }
        }}
        footer={!batchGenerating ? (
          <Space style={{ width: '100%', justifyContent: 'flex-end', flexWrap: 'wrap' }}>
            <Button onClick={() => setBatchGenerateVisible(false)}>
              取消
            </Button>
            <Button type="primary" icon={<RocketOutlined />} onClick={() => batchForm.submit()}>
              开始批量生成
            </Button>
          </Space>
        ) : null}
        width={isMobile ? 'calc(100vw - 32px)' : 700}
        centered
        closable={!batchGenerating}
        maskClosable={!batchGenerating}
        style={isMobile ? {
          maxWidth: 'calc(100vw - 32px)',
          margin: '0 auto',
          padding: '0 16px'
        } : undefined}
        styles={{
          body: {
            maxHeight: isMobile ? 'calc(100vh - 200px)' : 'calc(100vh - 260px)',
            overflowY: 'auto',
            overflowX: 'hidden'
          }
        }}
      >
        {!batchGenerating ? (
          <Form
            form={batchForm}
            layout="vertical"
            onFinish={handleBatchGenerate}
            initialValues={{
              startChapterNumber: sortedChapters.find(ch => !ch.content || ch.content.trim() === '')?.chapter_number || 1,
              count: 5,
              enableAnalysis: true,
              styleId: selectedStyleId,
              targetWordCount: getCachedWordCount(),
              model: selectedModel,
            }}
          >
            <Alert
              message="批量生成说明：严格按序生成 | 统一风格字数 | 任一失败则终止"
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
            />

            {/* 第一行：起始章节 + 生成数量 */}
            <div style={{ display: 'flex', flexDirection: isMobile ? 'column' : 'row', gap: isMobile ? 0 : 16 }}>
              <Form.Item
                label="起始章节"
                name="startChapterNumber"
                rules={[{ required: true, message: '请选择' }]}
                style={{ flex: 1, marginBottom: 12 }}
              >
                <Select placeholder="选择起始章节">
                  {sortedChapters
                    .filter(ch => !ch.content || ch.content.trim() === '')
                    .filter(ch => canGenerateChapter(ch))
                    .map(ch => (
                      <Select.Option key={ch.id} value={ch.chapter_number}>
                        第{ch.chapter_number}章：{ch.title}
                      </Select.Option>
                    ))}
                </Select>
              </Form.Item>

              <Form.Item
                label="生成数量"
                name="count"
                rules={[{ required: true, message: '请选择' }]}
                style={{ marginBottom: 12 }}
              >
                <Radio.Group buttonStyle="solid" size={isMobile ? 'small' : 'middle'}>
                  <Radio.Button value={5}>5章</Radio.Button>
                  <Radio.Button value={10}>10章</Radio.Button>
                  <Radio.Button value={15}>15章</Radio.Button>
                  <Radio.Button value={20}>20章</Radio.Button>
                </Radio.Group>
              </Form.Item>
            </div>

            {/* 第二行：写作风格 + 目标字数 */}
            <div style={{ display: 'flex', flexDirection: isMobile ? 'column' : 'row', gap: isMobile ? 0 : 16 }}>
              <Form.Item
                label="写作风格"
                name="styleId"
                rules={[{ required: true, message: '请选择' }]}
                style={{ flex: 1, marginBottom: 12 }}
              >
                <Select placeholder="请选择写作风格" showSearch optionFilterProp="children">
                  {writingStyles.map(style => (
                    <Select.Option key={style.id} value={style.id}>
                      {style.name}{style.is_default && ' (默认)'}
                    </Select.Option>
                  ))}
                </Select>
              </Form.Item>

              <Form.Item
                label="目标字数"
                name="targetWordCount"
                rules={[{ required: true, message: '请设置' }]}
                tooltip="修改后自动记住"
                style={{ flex: 1, marginBottom: 12 }}
              >
                <InputNumber
                  min={500}
                  max={10000}
                  step={100}
                  style={{ width: '100%' }}
                  formatter={(value) => `${value} 字`}
                  parser={(value) => parseInt(value?.replace(' 字', '') || '0', 10) as unknown as 500}
                  onChange={(value) => {
                    if (value) {
                      setCachedWordCount(value);
                    }
                  }}
                />
              </Form.Item>
            </div>

            {/* 生成方式：单模型连续批量 / 多模型独立候选预览 */}
            <Form.Item label="生成方式" style={{ marginBottom: 12 }}>
              <Segmented
                block
                value={batchMode}
                options={[
                  { label: '单模型批量', value: 'single' },
                  { label: '多模型候选预览', value: 'compare' },
                ]}
                onChange={value => setBatchMode(value as 'single' | 'compare')}
                disabled={batchGenerating}
              />
            </Form.Item>
            {batchMode === 'compare' && (
              <Form.Item
                label="选择模型（为每章分别生成独立候选）"
                tooltip="候选不会自动成为下一章上下文；只有逐章采用并完成正式分析后，才进入书籍的连续创作链路。Token 消耗约为模型数倍。"
                style={{ marginBottom: 12 }}
              >
                <LLMMultiSelector
                  value={batchComparisonSelections}
                  onChange={setBatchComparisonSelections}
                  disabled={batchGenerating}
                />
              </Form.Item>
            )}

            {/* 第三行：AI 服务 + 模型 + Skill */}
            <div style={{ display: 'flex', flexDirection: isMobile ? 'column' : 'row', gap: isMobile ? 0 : 16 }}>
              <div style={{ flex: 1 }}>
                <AIServiceSelector
                  usageType="chapter_write"
                  value={batchAIState}
                  onChange={setBatchAIState}
                  disabled={batchGenerating}
                />
              </div>

              <Form.Item
                label="应用 Skill"
                tooltip="选择一个 Skill 工作流指导批量创作，不选则使用标准创作流程"
                style={{ flex: 1, marginBottom: 12 }}
              >
                <Select
                  placeholder="不使用 Skill（标准创作）"
                  value={batchSelectedSkillKey}
                  onChange={setBatchSelectedSkillKey}
                  allowClear
                  showSearch
                  optionFilterProp="label"
                >
                  {writingSkills.map(skill => (
                    <Select.Option key={skill.template_key} value={skill.template_key} label={skill.template_name}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span>{skill.template_name}</span>
                        <Tag style={{ fontSize: 11, lineHeight: '18px', padding: '0 4px' }}>{skill.category}</Tag>
                      </div>
                    </Select.Option>
                  ))}
                </Select>
              </Form.Item>
            </div>

            {/* 同步分析（固定开启） */}
            <Form.Item
              label="同步分析"
              name="enableAnalysis"
              tooltip="必须开启，确保剧情连贯"
              style={{ marginBottom: 12 }}
            >
              <Radio.Group disabled>
                <Radio value={true}>
                  <span style={{ fontSize: 12, color: token.colorSuccess }}>✓ 自动更新角色状态</span>
                </Radio>
              </Radio.Group>
            </Form.Item>

            {/* 跳过上一章分析检查（默认关闭；上一章分析失败/卡死时用于解除阻塞） */}
            <Form.Item name="skipAnalysisCheck" valuePropName="checked" style={{ marginBottom: 12 }}>
              <Checkbox>
                跳过上一章分析检查
                <span style={{ fontSize: 12, color: token.colorTextTertiary, marginLeft: 8 }}>
                  （上一章分析失败/卡死导致无法生成时勾选；可能导致记忆/伏笔不连贯）
                </span>
              </Checkbox>
            </Form.Item>
          </Form>
        ) : (
          <div>
            <Alert
              message="温馨提示"
              description={
                <ul style={{ margin: '8px 0 0 0', paddingLeft: 20 }}>
                  <li>批量生成需要一定时间，可以切换到其他页面</li>
                  <li>关闭页面后重新打开，会自动恢复任务进度</li>
                  <li>可以随时点击"取消任务"按钮中止生成</li>
                  {batchProgress?.estimated_time_minutes && batchProgress.completed === 0 && (
                    <li>⏱️ 预计耗时：约 {batchProgress.estimated_time_minutes} 分钟</li>
                  )}
                </ul>
              }
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
            />

            <div style={{ textAlign: 'center' }}>
              <Button
                danger
                icon={<StopOutlined />}
                onClick={() => {
                  modal.confirm({
                    title: '确认取消',
                    content: '确定要取消批量生成吗？已生成的章节将保留。',
                    okText: '确定取消',
                    cancelText: '继续生成',
                    okButtonProps: { danger: true },
                    onOk: handleCancelBatchGenerate,
                  });
                }}
              >
                取消任务
              </Button>
            </div>
          </div>
        )}
      </Modal>

      {/* 单章节生成进度显示 */}
      <SSELoadingOverlay
        loading={isGenerating}
        progress={singleChapterProgress}
        message={singleChapterProgressMessage}
      />

      <Modal
        title="多模型章节候选比较"
        open={comparisonVisible}
        onCancel={() => setComparisonVisible(false)}
        footer={null}
        width={isMobile ? 'calc(100vw - 24px)' : '92%'}
        destroyOnHidden={false}
      >
        {comparisonBatch ? (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <Alert
              showIcon
              type={comparisonBatch.status === 'partial_failed' ? 'warning' : comparisonBatch.status === 'failed' ? 'error' : 'info'}
              message={comparisonBatch.status === 'adopted'
                ? '已采用一个候选作为正式章节；其他结果仍保留。'
                : ['draft', 'queued', 'running'].includes(comparisonBatch.status)
                  ? '正在生成候选。此时正式章节不会发生变化。'
                  : '候选已生成，请比较后再选择是否采用。'}
            />
            <Button onClick={openCandidateDiff} disabled={comparisonBatch.candidates.filter(item => item.status === 'success').length < 2}>
              比较两个候选的差异
            </Button>
            <Row gutter={[16, 16]}>
              {comparisonBatch.candidates.map(candidate => (
                <Col xs={24} lg={comparisonBatch.candidates.length === 2 ? 12 : 8} key={candidate.id}>
                  <LLMCandidateCard
                    candidate={candidate}
                    adopted={comparisonBatch.adopted_candidate_id === candidate.id}
                    actionsDisabled={comparisonBatch.status === 'adopted'}
                    onRetry={handleRetryCandidate}
                    onAdopt={handleAdoptCandidate}
                  />
                  {(() => {
                    const variants = (comparisonBatch.input_snapshot?.selection_variants || {}) as Record<string, { skill_name?: string; target_word_count?: number }>;
                    const key = candidate.provider_config_id ? `${candidate.provider_config_id}\u0000${candidate.model}` : '';
                    const variant = variants[key];
                    return variant ? (
                      <div style={{ fontSize: 12, color: token.colorTextSecondary, marginTop: 4 }}>
                        Skill：{variant.skill_name || '不使用 Skill'} · 目标字数：{variant.target_word_count} 字
                      </div>
                    ) : null;
                  })()}
                  {candidate.status === 'success' && (
                    <Space style={{ marginTop: 8 }}>
                      <Button size="small" onClick={() => copyCandidate(candidate)}>复制正文</Button>
                      {!comparisonBatch.adopted_candidate_id && (
                        <Button size="small" onClick={() => openCandidateEditor(candidate)}>编辑候选</Button>
                      )}
                    </Space>
                  )}
                </Col>
              ))}
            </Row>
          </Space>
        ) : <Empty description="暂无比较结果" />}
      </Modal>

      <LLMCandidateDiffModal
        open={candidateDiffVisible}
        candidates={comparisonBatch?.candidates || []}
        leftId={candidateDiffIds[0]}
        rightId={candidateDiffIds[1]}
        onSelectionChange={(left, right) => setCandidateDiffIds([left, right])}
        onClose={() => setCandidateDiffVisible(false)}
      />

      {/* 章节阅读器 */}
      {readingChapter && (
        <ChapterReader
          visible={readerVisible}
          chapter={readingChapter}
          onClose={() => {
            setReaderVisible(false);
            setReadingChapter(null);
          }}
          onChapterChange={handleReaderChapterChange}
        />
      )}

      {/* 局部重写弹窗 */}
      {editingId && (
        <PartialRegenerateModal
          visible={partialRegenerateModalVisible}
          chapterId={editingId}
          selectedText={selectedTextForRegenerate}
          startPosition={selectionStartPosition}
          endPosition={selectionEndPosition}
          styleId={selectedStyleId}
          onClose={() => setPartialRegenerateModalVisible(false)}
          onApply={handleApplyPartialRegenerate}
        />
      )}

      {/* 规划编辑器 */}
      {editingPlanChapter && currentProject && (() => {
        let parsedPlanData = null;
        try {
          if (editingPlanChapter.expansion_plan) {
            parsedPlanData = JSON.parse(editingPlanChapter.expansion_plan);
          }
        } catch (error) {
          console.error('解析规划数据失败:', error);
        }

        return (
          <ExpansionPlanEditor
            visible={planEditorVisible}
            planData={parsedPlanData}
            chapterSummary={editingPlanChapter.summary || null}
            projectId={currentProject.id}
            onSave={handleSavePlan}
            onCancel={() => {
              setPlanEditorVisible(false);
              setEditingPlanChapter(null);
            }}
          />
        );
      })()}
    </div>
  );
}
