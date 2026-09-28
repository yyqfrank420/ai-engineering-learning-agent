import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import type { CSSProperties } from 'react';
import type { GraphNode } from './types';
import { trackEvent } from './services/analytics';
import { useAgentStream } from './hooks/useAgentStream';
import { graphStructureKey } from './utils/graphStructureKey';
import { TitleBar } from './components/Layout/TitleBar';
import { SplitPane } from './components/Layout/SplitPane';
import { ThreadSidebar } from './components/Layout/ThreadSidebar';
import { ThinkingIndicator } from './components/Chat/ThinkingIndicator';
import { RetrievalNoticeBar } from './components/Chat/RetrievalNoticeBar';
import { ContextBar } from './components/Chat/ContextBar';
import { ChatInput } from './components/Chat/ChatInput';
import { AuthScreen } from './components/Auth/AuthScreen';
import { signOut } from './services/auth';
import { checkDiagramIntent } from './services/api';
import { useAuthSession } from './hooks/useAuthSession';
import { useBackendReadiness } from './hooks/useBackendReadiness';
import { useSelectionSuggestion } from './hooks/useSelectionSuggestion';
import { useThreadSession } from './hooks/useThreadSession';
import {
  shouldPersistThreadSnapshot,
  storageKeyForThread,
  writeThreadSnapshot,
} from './utils/threadState';

const HiddenGraphEvaluator = lazy(() =>
  import('./components/GraphCanvas/HiddenGraphEvaluator').then(module => ({ default: module.HiddenGraphEvaluator })),
);
const GraphCanvas = lazy(() =>
  import('./components/GraphCanvas').then(module => ({ default: module.GraphCanvas })),
);
const MessageList = lazy(() =>
  import('./components/Chat/MessageList').then(module => ({ default: module.MessageList })),
);
const InternalDashboard = lazy(() =>
  import('./components/InternalDashboard').then(module => ({ default: module.InternalDashboard })),
);

type AppRoute = 'chat' | 'internal-dashboard';

function resolveRouteFromHash(): AppRoute {
  return window.location.hash === '#/internal/dashboard' ? 'internal-dashboard' : 'chat';
}

export default function App() {
  const auth = useAuthSession();
  const workspaceKey = auth.authSession ? `user:${auth.authSession.user.id}` : 'signed-out';
  return <AppWorkspace key={workspaceKey} auth={auth} />;
}

function AppWorkspace({ auth }: { auth: ReturnType<typeof useAuthSession> }) {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [hasUnsavedGraphEdit, setHasUnsavedGraphEdit] = useState(false);
  const [appRoute, setAppRoute] = useState<AppRoute>(resolveRouteFromHash);
  const { authReady, handleAuthenticated, setAuthSession, authSession } = auth;
  const {
    selectionSuggestion,
    selectionReferenceActive,
    clearSelection,
    activateSelectionReference,
    dismissSelection,
    clearSelectionReference,
  } = useSelectionSuggestion();
  const {
    backendReadiness,
    prepareMessage,
    isBackendReady,
    prepareBackendNow,
    clearPreparedCache,
  } = useBackendReadiness(authSession);

  const {
    activeThreadId,
    threadTitle,
    loadingThread,
    threadError,
    threadSnapshot,
    handleNewChat,
    handleSelectThread,
    handleDeleteThread,
    retryThread,
  } = useThreadSession({
    authSession,
    backendReady: isBackendReady,
    clearSelection,
  });

  const {
    messages,
    visibleMessages,
    answerPending,
    diagramRequested,
    acknowledgeGraphRendered,
    graphData,
    isSavingGraphEdit,
    publishedGraphKey,
    graphPreview,
    graphCandidate,
    workflowProgress,
    retrievalNotice,
    graphNotice,
    selectedNode,
    selectNode,
    clearSelectedNode,
    streamStatus,
    providerNotice,
    hydrateThread,
    sendMessage,
    saveGraphEdit,
    requestSearchTool,
    stopGeneration,
  } = useAgentStream(authSession, activeThreadId);

  const graphEditBlocked = hasUnsavedGraphEdit || isSavingGraphEdit;

  useEffect(() => {
    if (!graphEditBlocked) return;
    const warnBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', warnBeforeUnload);
    return () => window.removeEventListener('beforeunload', warnBeforeUnload);
  }, [graphEditBlocked]);

  useEffect(() => {
    const handleHashChange = () => {
      const nextRoute = resolveRouteFromHash();
      if (graphEditBlocked && nextRoute !== appRoute) {
        window.location.hash = appRoute === 'chat' ? '' : '/internal/dashboard';
        return;
      }
      setAppRoute(nextRoute);
    };
    window.addEventListener('hashchange', handleHashChange);
    return () => window.removeEventListener('hashchange', handleHashChange);
  }, [appRoute, graphEditBlocked]);

  useEffect(() => {
    hydrateThread(threadSnapshot);
  }, [hydrateThread, threadSnapshot]);

  const handleLogout = useCallback(async () => {
    if (graphEditBlocked) return;
    if (authSession) {
      localStorage.removeItem(storageKeyForThread(authSession.user.id));
      clearPreparedCache();
    }

    await signOut();
    setAuthSession(null);
  }, [authSession, clearPreparedCache, graphEditBlocked, setAuthSession]);

  const handleSend = useCallback((content: string, diagramRequested?: boolean) => {
    if (backendReadiness !== 'ready' || graphEditBlocked) {
      return;
    }
    const requestContent = selectionReferenceActive && selectionSuggestion
      ? [
          'Explain this highlighted part in beginner-friendly terms and relate it to the diagram.',
          '',
          `Highlighted text: "${selectionSuggestion}"`,
          '',
          `User question: ${content}`,
        ].join('\n')
      : content;

    clearSelection();
    sendMessage(requestContent, {
      complexity: 'auto',
      graphMode: 'on',
      diagramRequested,
      researchEnabled: true,
      displayContent: content,
      backendReadinessState: backendReadiness,
      hasSelectedTextContext: selectionReferenceActive && !!selectionSuggestion,
    });
  }, [backendReadiness, clearSelection, graphEditBlocked, selectionReferenceActive, selectionSuggestion, sendMessage]);

  const checkSubmission = useCallback(async (content: string) => {
    if (!authSession || !activeThreadId) throw new Error('Chat is not ready');
    return checkDiagramIntent(authSession, activeThreadId, content);
  }, [authSession, activeThreadId]);

  // isGenerating: LLM is actively streaming — show Stop button
  const isGenerating = streamStatus === 'generating';
  // isStreaming: busy state used to disable sidebar/new-chat during loads
  const isStreaming = isGenerating || loadingThread || graphEditBlocked;
  const composerLocked = loadingThread || isSavingGraphEdit;
  const sendLocked = composerLocked || graphEditBlocked || backendReadiness !== 'ready' || !activeThreadId;
  const readinessRetryDisabled = isGenerating || composerLocked || !authSession;

  const handleNodeClick = (node: GraphNode) => {
    // Useful actions appear immediately. The low-cost model request may refine
    // them asynchronously, but latency or a provider failure never leaves an
    // empty context bar.
    selectNode(node);
    void trackEvent('node_selected', {
      thread_id: activeThreadId ?? undefined,
      node_id: node.id,
      node_label: node.label,
    }, authSession);
  };

  const handleTellMeMore = useCallback((node: GraphNode) => {
    handleSend(
      `Tell me more about ${node.label}. Walk me through how it fits into this architecture like I am a beginner, and use simple analogies.`,
    );
  }, [handleSend]);

  const handleExpandGraph = useCallback((node: GraphNode) => {
    if (graphEditBlocked) return;
    clearSelection();
    clearSelectedNode();
    void trackEvent('expand_graph_clicked', {
      thread_id: activeThreadId ?? undefined,
      node_id: node.id,
      node_label: node.label,
      complexity: 'auto',
      graph_mode: 'on',
      research_enabled: true,
      backend_readiness_state: backendReadiness,
    }, authSession);
    sendMessage(
      [
        `Expand the current graph around ${node.label}.`,
        '',
        'Keep the same overall topic and build on the existing graph instead of replacing it.',
        'Add only the most relevant nearby nodes, edges, and steps that help a beginner understand this part better.',
        'Do not start a brand-new graph unless the topic has clearly changed.',
        'Do not expand business-constraint or decision nodes unless they are central to the user request.',
      ].join('\n'),
      {
        complexity: 'auto',
        graphMode: 'on',
        researchEnabled: true,
        displayContent: `Expand graph around ${node.label}`,
        backendReadinessState: backendReadiness,
        hasSelectedTextContext: false,
      },
    );
  }, [activeThreadId, authSession, backendReadiness, clearSelectedNode, clearSelection, graphEditBlocked, sendMessage]);

  const startNewChat = useCallback(() => {
    if (!graphEditBlocked) void handleNewChat();
  }, [graphEditBlocked, handleNewChat]);

  const selectThread = useCallback((threadId: string) => {
    if (!graphEditBlocked) handleSelectThread(threadId);
  }, [graphEditBlocked, handleSelectThread]);

  const deleteThread = useCallback((threadId: string) => {
    if (!graphEditBlocked) handleDeleteThread(threadId);
  }, [graphEditBlocked, handleDeleteThread]);

  const handleRetryThread = useCallback(() => {
    if (!graphEditBlocked) retryThread();
  }, [graphEditBlocked, retryThread]);

  const effectiveThreadTitle = useMemo(
    () => threadTitle || 'New chat',
    [threadTitle],
  );

  useEffect(() => {
    if (!authSession || !activeThreadId) {
      return;
    }

    const liveSnapshot = {
      title: effectiveThreadTitle,
      messages,
      graphData,
    };

    if (!shouldPersistThreadSnapshot(liveSnapshot, threadSnapshot)) {
      return;
    }

    writeThreadSnapshot(authSession.user.id, activeThreadId, liveSnapshot);
  }, [activeThreadId, authSession, effectiveThreadTitle, graphData, messages, threadSnapshot]);

  const latestAssistantText = useMemo(
    () => [...messages].reverse().find((message) => message.role === 'assistant')?.content ?? '',
    [messages],
  );

  const handleToggleSidebar = useCallback(() => {
    setSidebarOpen(open => !open);
  }, []);

  const openDashboard = useCallback(() => {
    if (graphEditBlocked) return;
    window.location.hash = '/internal/dashboard';
    setAppRoute('internal-dashboard');
  }, [graphEditBlocked]);

  const openChat = useCallback(() => {
    if (graphEditBlocked) return;
    window.location.hash = '';
    setAppRoute('chat');
  }, [graphEditBlocked]);

  if (!authReady) {
    return <div style={loadingScreenStyle}>Loading session…</div>;
  }

  // Component-only previews have no topology. Keep the connected diagram during edits.
  const displayedGraphData = graphPreview?.edges.length === 0 && graphData?.edges.length
    ? graphData
    : graphPreview ?? graphData;
  const showGraphPane = !!displayedGraphData || !!graphCandidate || diagramRequested || isGenerating;
  const dashboardActive = appRoute === 'internal-dashboard' && !!authSession;

  return (
    <div style={{ position: 'relative', height: '100vh', overflow: 'hidden' }}>
    <Suspense fallback={null}>
      <HiddenGraphEvaluator candidate={graphCandidate} />
    </Suspense>
    {/* Auth overlay — sits above blurred app when unauthenticated */}
    {!authSession && <AuthScreen onAuthenticated={handleAuthenticated} />}
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100vh',
      // Ambient gradient backdrop — vivid enough for glass panels to refract color
      background: `
        radial-gradient(ellipse 80% 60% at 10% -5%, rgba(124,58,237,0.55) 0%, transparent 60%),
        radial-gradient(ellipse 70% 50% at 90% 105%, rgba(37,99,235,0.45) 0%, transparent 60%),
        radial-gradient(ellipse 50% 40% at 75% 25%, rgba(5,150,105,0.18) 0%, transparent 50%),
        radial-gradient(ellipse 40% 30% at 25% 70%, rgba(124,58,237,0.12) 0%, transparent 50%),
        #070a10
      `,
      color: '#e2e8f0',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      // Blur + dim the app when unauthenticated so it shows as a preview behind auth
      ...(authSession ? {} : {
        filter: 'blur(6px)',
        opacity: 0.35,
        pointerEvents: 'none',
        userSelect: 'none',
      }),
    }}>
      <TitleBar
        streamStatus={streamStatus}
        providerNotice={providerNotice}
        userEmail={authSession?.user.email ?? ''}
        threadTitle={dashboardActive ? 'Internal dashboard' : effectiveThreadTitle}
        sidebarOpen={sidebarOpen}
        showDashboardLink={!!authSession}
        dashboardActive={dashboardActive}
        onToggleSidebar={handleToggleSidebar}
        onOpenDashboard={openDashboard}
        onOpenChat={openChat}
        onLogout={handleLogout}
      />

      {/* Main body: sidebar + split pane side-by-side */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        {dashboardActive && authSession ? (
          <Suspense fallback={<div style={panelFallbackStyle}>Loading dashboard…</div>}>
            <InternalDashboard authSession={authSession} />
          </Suspense>
        ) : (
          <>
            <ThreadSidebar
              authSession={authSession}
              activeThreadId={activeThreadId}
              backendReadiness={backendReadiness}
              onNewChat={startNewChat}
              onSelectThread={selectThread}
              onDeleteThread={deleteThread}
              isLoading={isStreaming}
              isOpen={sidebarOpen}
            />
            <SplitPane
              graphVisible={showGraphPane}
              left={
                <Suspense fallback={<div style={panelFallbackStyle}>Loading graph…</div>}>
                  <GraphCanvas
                    graphData={displayedGraphData}
                    isPreview={graphPreview !== null}
                    isAcceptedGraph={displayedGraphData !== null && displayedGraphData === graphData}
                    animateSequence={!isGenerating && publishedGraphKey === graphStructureKey(displayedGraphData)}
                    authSession={authSession}
                    activeThreadId={activeThreadId}
                    onNodeClick={handleNodeClick}
                    onSaveGraphEdit={saveGraphEdit}
                    onEditDraftChange={setHasUnsavedGraphEdit}
                    editingDisabled={isGenerating || loadingThread || isSavingGraphEdit || graphPreview !== null || !authSession || !activeThreadId}
                    onTellMeMore={handleTellMeMore}
                    onExpandGraph={handleExpandGraph}
                    selectedNode={selectedNode}
                    onClosePopup={clearSelectedNode}
                    sourceTexts={[latestAssistantText]}
                    isBuilding={isGenerating}
                    onGraphReady={acknowledgeGraphRendered}
                  />
                </Suspense>
              }
              right={
                <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
                  {threadError && (
                    <div role="alert" style={{
                      margin: '1rem',
                      padding: '0.75rem 1rem',
                      borderRadius: '8px',
                      background: 'rgba(248,81,73,0.08)',
                      border: '1px solid rgba(248,81,73,0.2)',
                      color: '#f85149',
                      fontSize: '0.8rem',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      gap: '0.75rem',
                      flexShrink: 0,
                    }}>
                      <span>{threadError}</span>
                      <button
                        onClick={handleRetryThread}
                        disabled={graphEditBlocked || loadingThread || !isBackendReady}
                        style={{
                          background: 'rgba(248,81,73,0.12)',
                          border: '1px solid rgba(248,81,73,0.3)',
                          borderRadius: '6px',
                          color: '#f85149',
                          fontSize: '0.75rem',
                          padding: '3px 10px',
                          cursor: 'pointer',
                          flexShrink: 0,
                        }}
                      >
                        Retry
                      </button>
                    </div>
                  )}
                  <Suspense fallback={<div style={panelFallbackStyle}>Loading conversation…</div>}>
                    <MessageList messages={visibleMessages} />
                  </Suspense>
                  <ThinkingIndicator
                    workflowProgress={workflowProgress}
                    isGenerating={isGenerating || answerPending}
                  />
                  <RetrievalNoticeBar
                    notice={retrievalNotice}
                    onUseSearchTool={requestSearchTool}
                  />
                  <RetrievalNoticeBar
                    notice={graphNotice}
                  />
                  <ContextBar
                    selectedNode={selectedNode}
                    onSendMessage={handleSend}
                    onClear={clearSelectedNode}
                  />
                  {graphEditBlocked && (
                    <p role="status" style={{ margin: '0 1rem 0.5rem', color: '#c4b5fd', fontSize: '0.75rem' }}>
                      {isSavingGraphEdit ? 'Saving component edits…' : 'Save or cancel component edits to continue.'}
                    </p>
                  )}
                  <ChatInput
                    onSend={handleSend}
                    checkSubmission={checkSubmission}
                    onStop={stopGeneration}
                    onRetryReadiness={prepareBackendNow}
                    threadId={activeThreadId}
                    isGenerating={isGenerating}
                    disabled={composerLocked}
                    sendDisabled={sendLocked}
                    backendReadiness={backendReadiness}
                    retryDisabled={readinessRetryDisabled}
                    readinessMessage={prepareMessage}
                    selectionSuggestion={selectionSuggestion}
                    selectionReferenceActive={selectionReferenceActive}
                    onUseSelection={activateSelectionReference}
                    onDismissSelection={dismissSelection}
                    onClearSelectionReference={clearSelectionReference}
                  />
                </div>
              }
            />
          </>
        )}
      </div>
    </div>
    </div>
  );
}

const loadingScreenStyle: CSSProperties = {
  minHeight: '100vh',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  background: '#0d1117',
  color: '#e6edf3',
};

const panelFallbackStyle: CSSProperties = {
  flex: 1,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  color: '#8b949e',
  fontSize: '0.85rem',
};
