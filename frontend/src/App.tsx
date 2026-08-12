import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Spin } from 'antd';

// 路由懒加载：首屏只加载当前页面，其余页面按需分包（显著减少首屏 JS）
const ProjectList = lazy(() => import('./pages/ProjectList'));
const ProjectWizardNew = lazy(() => import('./pages/ProjectWizardNew'));
const Inspiration = lazy(() => import('./pages/Inspiration'));
const ProjectDetail = lazy(() => import('./pages/ProjectDetail'));
const WorldSetting = lazy(() => import('./pages/WorldSetting'));
const Outline = lazy(() => import('./pages/Outline'));
const OutlineOverview = lazy(() => import('./pages/OutlineOverview'));
const BodyReader = lazy(() => import('./pages/BodyReader'));
const Characters = lazy(() => import('./pages/Characters'));
const Careers = lazy(() => import('./pages/Careers'));
const Relationships = lazy(() => import('./pages/Relationships'));
const RelationshipGraph = lazy(() => import('./pages/RelationshipGraph'));
const Organizations = lazy(() => import('./pages/Organizations'));
const Chapters = lazy(() => import('./pages/Chapters'));
const ChapterReader = lazy(() => import('./pages/ChapterReader'));
const ChapterAnalysis = lazy(() => import('./pages/ChapterAnalysis'));
const PipelinePanel = lazy(() => import('./pages/PipelinePanel'));
const ThemeTemplates = lazy(() => import('./pages/ThemeTemplates'));
const Foreshadows = lazy(() => import('./pages/Foreshadows'));
const WritingStyles = lazy(() => import('./pages/WritingStyles'));
const PromptWorkshop = lazy(() => import('./pages/PromptWorkshop'));
const Settings = lazy(() => import('./pages/Settings'));
const MCPPlugins = lazy(() => import('./pages/MCPPlugins'));
const UserManagement = lazy(() => import('./pages/UserManagement'));
const PromptTemplates = lazy(() => import('./pages/PromptTemplates'));
const SkillChat = lazy(() => import('./pages/SkillChat'));
const SkillManage = lazy(() => import('./pages/SkillManage'));
const ReviewConfig = lazy(() => import('./pages/ReviewConfig'));
const AIUsageLogs = lazy(() => import('./pages/AIUsageLogs'));
// import Polish from './pages/Polish';
const Login = lazy(() => import('./pages/Login'));
const AuthCallback = lazy(() => import('./pages/AuthCallback'));
import ProtectedRoute from './components/ProtectedRoute';
import AppFooter from './components/AppFooter';
import SpringFestival from './components/SpringFestival';
import './App.css';

function PageLoading() {
  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '60vh' }}>
      <Spin size="large" tip="加载中..." />
    </div>
  );
}

function App() {
  return (
    <>
      {/* 🧧 春节喜庆装饰 */}
      <SpringFestival />
      <BrowserRouter
        future={{
          v7_startTransition: true,
          v7_relativeSplatPath: true,
        }}
      >
        <Suspense fallback={<PageLoading />}>
          <Routes>
          <Route path="/login" element={<><Login /><AppFooter /></>} />
          <Route path="/auth/callback" element={<AuthCallback />} />

          <Route path="/" element={<ProtectedRoute><><ProjectList /><AppFooter sidebarWidth={220} /></></ProtectedRoute>} />
          <Route path="/projects" element={<ProtectedRoute><><ProjectList /><AppFooter sidebarWidth={220} /></></ProtectedRoute>} />
          <Route path="/wizard" element={<ProtectedRoute><ProjectWizardNew /></ProtectedRoute>} />
          <Route path="/inspiration" element={<ProtectedRoute><Inspiration /></ProtectedRoute>} />
          <Route path="/settings" element={<ProtectedRoute><Settings /></ProtectedRoute>} />
          <Route path="/theme-templates" element={<ProtectedRoute><ThemeTemplates /></ProtectedRoute>} />
          <Route path="/prompt-templates" element={<ProtectedRoute><><PromptTemplates /><AppFooter /></></ProtectedRoute>} />
          <Route path="/mcp-plugins" element={<ProtectedRoute><MCPPlugins /></ProtectedRoute>} />
          <Route path="/user-management" element={<ProtectedRoute><UserManagement /></ProtectedRoute>} />
          <Route path="/chapters/:chapterId/reader" element={<ProtectedRoute><ChapterReader /></ProtectedRoute>} />
          <Route path="/project/:projectId" element={<ProtectedRoute><ProjectDetail /></ProtectedRoute>}>
            <Route index element={<Navigate to="world-setting" replace />} />
            <Route path="world-setting" element={<WorldSetting />} />
            <Route path="careers" element={<Careers />} />
            <Route path="outline" element={<Outline />} />
            <Route path="outline-overview" element={<OutlineOverview />} />
            <Route path="body-reader" element={<BodyReader />} />
            <Route path="characters" element={<Characters />} />
            <Route path="relationships" element={<Relationships />} />
            <Route path="relationships-graph" element={<RelationshipGraph />} />
            <Route path="organizations" element={<Organizations />} />
            <Route path="chapters" element={<Chapters />} />
            <Route path="chapter-analysis" element={<ChapterAnalysis />} />
            <Route path="foreshadows" element={<Foreshadows />} />
            <Route path="writing-styles" element={<WritingStyles />} />
            <Route path="prompt-workshop" element={<PromptWorkshop />} />
            <Route path="skill-chat" element={<SkillChat />} />
            <Route path="skill-manage" element={<SkillManage />} />
            <Route path="review-config" element={<ReviewConfig />} />
            <Route path="ai-usage" element={<AIUsageLogs />} />
            <Route path="pipeline" element={<PipelinePanel />} />
            {/* <Route path="polish" element={<Polish />} /> */}
          </Route>
          </Routes>
        </Suspense>
      </BrowserRouter>
    </>
  );
}

export default App;
