import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import type { DiagramIntentAction, GraphNode, Message, SendOptions } from './types';
import './App.css';
import { trackEvent } from './services/analytics';
import { useAgentStream } from './hooks/useAgentStream';
import { graphStructureKey } from './utils/graphStructureKey';
import { TitleBar } from './components/Layout/TitleBar';
import { SplitPane } from './components/Layout/SplitPane';
import { HISTORY_OVERLAY_QUERY, ThreadSidebar } from './components/Layout/ThreadSidebar';
import { RetrievalNoticeBar } from './components/Chat/RetrievalNoticeBar';
import { ContextBar } from './components/Chat/ContextBar';
import { ChatInput } from './components/Chat/ChatInput';
import { AuthScreen } from './components/Auth/AuthScreen';
import { signOut } from './services/auth';
import type { GraphCanvasHandle } from './components/GraphCanvas';
import { GraphHistoryControls } from './components/GraphHistoryControls';
import { useGraphHistory } from './hooks/useGraphHistory';
import { checkDiagramIntent } from './services/api';
import { useAuthSession } from './hooks/useAuthSession';
import { useBackendReadiness } from './hooks/useBackendReadiness';
import { useSelectionSuggestion } from './hooks/useSelectionSuggestion';
import { useThreadSession } from './hooks/useThreadSession';
import {
  formatNodeQuestionRequest,
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
  const { authReady, handleAuthenticated, setAuthSession, authSession } = auth;
  const [sidebarOpen, setSidebarOpen] = useState(() => !window.matchMedia?.(HISTORY_OVERLAY_QUERY).matches);
  const viewportRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const media = window.matchMedia?.(HISTORY_OVERLAY_QUERY);
    if (!media) return;
    const update = () => setSidebarOpen(!media.matches);
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);

  useEffect(() => {
    const viewport = window.visualViewport;
    const shell = viewportRef.current;
    if (!viewport || !shell) return;
    const update = () => {
      // Dynamic viewport units exclude some mobile keyboards. Do not constrain pinch zoom.
      if (viewport.scale === 1) {
        shell.style.setProperty('--workspace-height', `${viewport.height}px`);
        shell.style.setProperty('--workspace-top', `${viewport.offsetTop}px`);
      } else {
        shell.style.removeProperty('--workspace-height');
        shell.style.removeProperty('--workspace-top');
      }
    };
    update();
    viewport.addEventListener('resize', update);
    viewport.addEventListener('scroll', update);
    return () => {
      viewport.removeEventListener('resize', update);
      viewport.removeEventListener('scroll', update);
    };
  }, [authReady]);
  const [hasUnsavedGraphEdit, setHasUnsavedGraphEdit] = useState(false);
  const [appRoute, setAppRoute] = useState<AppRoute>(resolveRouteFromHash);
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
    diagramRequested,
    acknowledgeGraphRendered,
    graphData,
    isSavingGraphEdit,
    publishedGraphKey,
    graphPreview,
    graphCandidate,
    liveActivity,
    retrievalNotice,
    graphNotice,
    selectedNode,
    selectNode,
    clearSelectedNode,
    streamStatus,
    providerNotice,
    hydrateThread,
    sendMessage,
    retryMessage,
    startThreadAndSend,
    adoptRestoredGraph,
    saveGraphEdit,
    requestSearchTool,
    stopGeneration,
    isFinishingDiagram,
  } = useAgentStream(authSession, activeThreadId);

  const graphEditBlocked = hasUnsavedGraphEdit || isSavingGraphEdit;
  const graphCanvasRef = useRef<GraphCanvasHandle>(null);
  const [actionBusy, setActionBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [retryingMessageId, setRetryingMessageId] = useState<string | null>(null);
  const actionInFlight = useRef(false);
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);
  const currentContext = useRef('');
  const context = `${authSession?.user.id ?? ''}:${activeThreadId ?? ''}:${graphData?.version ?? ''}`;
  currentContext.current = context;
  const flushLayout = useCallback(async () => { await graphCanvasRef.current?.flushPendingLayout(); }, []);
  const clearGraphSelection = useCallback(() => { clearSelection(); clearSelectedNode(); }, [clearSelection, clearSelectedNode]);
  const history = useGraphHistory({
    session: authSession, threadId: activeThreadId, graph: graphData,
    blocked: graphEditBlocked || loadingThread || actionBusy || streamStatus === 'generating',
    flushLayout, clearSelection: clearGraphSelection, adoptGraph: adoptRestoredGraph,
  });


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

  const handleSend = useCallback(async (content: string, action?: DiagramIntentAction, selectedNodeId?: string) => {
    if (backendReadiness !== 'ready' || isFinishingDiagram || graphEditBlocked || history.busy || history.preview || actionInFlight.current) {
      throw new Error('Finish the current diagram action before sending. Your message is saved here.');
    }
    actionInFlight.current = true;
    setRetryingMessageId(null);
    setActionBusy(true);
    setActionError(null);
    try {
      await flushLayout();
      if (!mountedRef.current || currentContext.current !== context) throw new Error('The conversation changed. Please try again.');
      const chipNode = selectedNodeId === undefined ? undefined : graphData?.nodes.find(node => node.id === selectedNodeId);
      if (selectedNodeId !== undefined && !chipNode) {
        throw new Error('The selected component is no longer in this diagram. Select a component and try again.');
      }
      const hasSelectedTextContext = !chipNode && selectionReferenceActive && !!selectionSuggestion;
      const requestContent = chipNode
        ? formatNodeQuestionRequest(content, chipNode)
        : hasSelectedTextContext
        ? ['Explain this highlighted part in beginner-friendly terms and relate it to the diagram.', '',
          `Highlighted text: "${selectionSuggestion}"`, '', `User question: ${content}`].join('\n')
        : content;
      const graphAction = action === 'extend' ? 'extend' : action === 'answer' ? 'answer'
        : action === 'new_chat' || !graphData ? 'new' : undefined;
      const options: SendOptions = {
        complexity: 'auto', graphMode: 'on', researchEnabled: true,
        graphAction, expectedGraphVersion: graphAction === 'extend' ? graphData?.version ?? null : undefined,
        displayContent: content, backendReadinessState: backendReadiness,
        hasSelectedTextContext,
      };
      let accepted: boolean;
      if (action === 'new_chat') {
        const created = await handleNewChat({ preserveCurrentView: true });
        if (!created) throw new Error('Could not create a new chat. Your message is saved here.');
        const createdContext = `${authSession?.user.id ?? ''}:${created.thread.id}:`;
        if (!mountedRef.current || (currentContext.current !== context && !currentContext.current.startsWith(createdContext))) {
          throw new Error('The conversation changed. Please try again.');
        }
        accepted = startThreadAndSend(created, requestContent, options);
      } else {
        accepted = sendMessage(requestContent, options);
      }
      if (!accepted) throw new Error('Could not send. Your message is saved here. Please try again.');
      clearGraphSelection();
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Could not save the diagram. Please retry.';
      setActionError(message);
      throw error;
    } finally {
      actionInFlight.current = false;
      setActionBusy(false);
    }
  }, [backendReadiness, isFinishingDiagram, graphEditBlocked, history.busy, history.preview, flushLayout, context, authSession, selectionReferenceActive, selectionSuggestion, graphData, handleNewChat, startThreadAndSend, sendMessage, clearGraphSelection]);

  const handleRetryMessage = useCallback(async (message: Message) => {
    if (!message.retryRequest || streamStatus === 'generating' || loadingThread || !activeThreadId
      || backendReadiness !== 'ready' || isFinishingDiagram || graphEditBlocked
      || history.busy || history.preview || actionInFlight.current) return;
    actionInFlight.current = true;
    setActionBusy(true);
    setActionError(null);
    setRetryingMessageId(message.id);
    try {
      await flushLayout();
      if (!mountedRef.current || currentContext.current !== context) throw new Error('The conversation changed. Please try again.');
      const accepted = await retryMessage(message, graphData?.version ?? null);
      if (!accepted) throw new Error('Could not retry this response. Please try again.');
      clearGraphSelection();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Could not retry this response. Please try again.');
      setRetryingMessageId(null);
    } finally {
      actionInFlight.current = false;
      setActionBusy(false);
    }
  }, [streamStatus, loadingThread, activeThreadId, backendReadiness, isFinishingDiagram, graphEditBlocked, history.busy, history.preview, flushLayout, context, retryMessage, graphData, clearGraphSelection]);

  const checkSubmission = useCallback(async (content: string) => {
    if (!authSession || !activeThreadId) throw new Error('Chat is not ready');
    return checkDiagramIntent(authSession, activeThreadId, content);
  }, [authSession, activeThreadId]);

  // isGenerating: LLM is actively streaming — show Stop button
  const isGenerating = streamStatus === 'generating';
  // isStreaming: busy state used to disable sidebar/new-chat during loads
  const isStreaming = isGenerating || loadingThread || graphEditBlocked || actionBusy || history.busy;
  const composerLocked = loadingThread || isSavingGraphEdit;
  const sendLocked = composerLocked || isFinishingDiagram || actionBusy || history.busy || !!history.preview || graphEditBlocked || backendReadiness !== 'ready' || !activeThreadId;
  const readinessRetryDisabled = isGenerating || composerLocked || !authSession;

  const handleNodeClick = (node: GraphNode) => {
    // Useful actions appear immediately. The low-cost model request may refine
    // them asynchronously, but latency or a provider failure never leaves an
    // empty context bar.
    if (history.preview || history.busy || actionBusy) return;
    selectNode(node);
    void trackEvent('node_selected', {
      thread_id: activeThreadId ?? undefined,
      node_id: node.id,
      node_label: node.label,
    }, authSession);
  };

  const handleTellMeMore = useCallback((node: GraphNode) => {
    void handleSend(
      `Tell me more about ${node.label}. Walk me through how it fits into this architecture like I am a beginner, and use simple analogies.`,
      'answer',
    ).catch(() => {});
  }, [handleSend]);

  const handleExpandGraph = useCallback((node: GraphNode) => {
    if (graphEditBlocked || history.busy || history.preview || actionBusy) return;
    void trackEvent('expand_graph_clicked', { thread_id: activeThreadId ?? undefined, node_id: node.id, node_label: node.label }, authSession);
    void handleSend(`Expand the current graph around ${node.label}. Keep the same topic and build on the existing diagram.`, 'extend').catch(() => {});
  }, [handleSend, graphEditBlocked, history.busy, history.preview, actionBusy, activeThreadId, authSession]);

  const startNewChat = useCallback(async () => {
    if (graphEditBlocked || isStreaming || actionInFlight.current) return;
    actionInFlight.current = true;
    setActionBusy(true);
    setActionError(null);
    try {
      await flushLayout();
      if (mountedRef.current && currentContext.current === context) {
        await handleNewChat();
        if (mountedRef.current && window.matchMedia?.(HISTORY_OVERLAY_QUERY).matches) setSidebarOpen(false);
      }
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Could not save the diagram. Please retry.');
    } finally {
      actionInFlight.current = false;
      setActionBusy(false);
    }
  }, [graphEditBlocked, isStreaming, flushLayout, context, handleNewChat]);

  const selectThread = useCallback(async (threadId: string) => {
    if (isStreaming || actionInFlight.current) return;
    actionInFlight.current = true;
    setActionBusy(true);
    setActionError(null);
    try {
      await flushLayout();
      if (mountedRef.current && currentContext.current === context) {
        handleSelectThread(threadId);
        if (window.matchMedia?.(HISTORY_OVERLAY_QUERY).matches) setSidebarOpen(false);
      }
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Could not save the diagram. Please retry.');
    } finally {
      actionInFlight.current = false;
      setActionBusy(false);
    }
  }, [isStreaming, flushLayout, context, handleSelectThread]);

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
  const displayedGraphData = history.preview?.graph_data ?? (graphPreview?.edges.length === 0 && graphData?.edges.length
    ? graphData
    : graphPreview ?? graphData);
  const showGraphPane = !!displayedGraphData || !!graphCandidate || diagramRequested || isGenerating;
  const dashboardActive = appRoute === 'internal-dashboard' && !!authSession;

  return (
    <div ref={viewportRef} className="app-viewport">
    <Suspense fallback={null}>
      <HiddenGraphEvaluator candidate={graphCandidate} />
    </Suspense>
    {/* Keep the workspace mounted so authentication preserves local state. */}
    {!authSession && <AuthScreen onAuthenticated={handleAuthenticated} />}
    <div className="app-workspace" inert={!authSession} aria-hidden={!authSession}>
      <a className="app-skip-link" href="#learning-workspace" onClick={event => {
        event.preventDefault();
        document.getElementById('learning-workspace')?.focus();
      }}>Skip to workspace</a>
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
      <main id="learning-workspace" className="app-workspace__main app-workspace__body" tabIndex={-1}>
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
              onClose={() => setSidebarOpen(false)}
            />
            <SplitPane
              graphVisible={showGraphPane}
              left={
                <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
                  {graphData && <GraphHistoryControls
                    history={history.history} previewId={history.preview?.revision_id ?? null}
                    undoId={history.undoId} redoId={history.redoId}
                    disabled={isGenerating || loadingThread || graphEditBlocked || actionBusy}
                    busy={history.busy} error={history.error}
                    onUndo={history.undo} onRedo={history.redo}
                    onPreview={history.previewRevision} onRestore={history.restoreRevision}
                    onReturn={history.returnToCurrent} onReload={() => void history.reload()}
                  />}
                <div style={{ display: 'flex', flex: 1, minHeight: 0, position: 'relative' }}>
                <Suspense fallback={<div style={panelFallbackStyle}>Loading graph…</div>}>
                  <GraphCanvas
                    ref={graphCanvasRef}
                    historyPreview={!!history.preview}
                    layoutLocked={history.busy || actionBusy || loadingThread}
                    graphData={displayedGraphData}
                    isPreview={graphPreview !== null}
                    isAcceptedGraph={displayedGraphData !== null && displayedGraphData === graphData}
                    animateSequence={!isGenerating && publishedGraphKey === graphStructureKey(displayedGraphData)}
                    authSession={authSession}
                    activeThreadId={activeThreadId}
                    onNodeClick={handleNodeClick}
                    onSaveGraphEdit={saveGraphEdit}
                    onEditDraftChange={setHasUnsavedGraphEdit}
                    editingDisabled={!!history.preview || history.busy || actionBusy || isGenerating || loadingThread || isSavingGraphEdit || graphPreview !== null || !authSession || !activeThreadId}
                    onTellMeMore={handleTellMeMore}
                    onExpandGraph={handleExpandGraph}
                    selectedNode={selectedNode}
                    onClosePopup={clearSelectedNode}
                    sourceTexts={[latestAssistantText]}
                    isBuilding={isGenerating}
                    onGraphReady={acknowledgeGraphRendered}
                  />
                </Suspense>
                </div>
                </div>
              }
              right={
                <div className="app-conversation" style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
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
                    <MessageList messages={visibleMessages} liveActivity={liveActivity} revisionIds={history.history?.revisions.map(revision => revision.id)} viewedRevisionId={history.preview?.revision_id ?? history.history?.current_revision_id ?? null} onViewDiagram={id => id === history.history?.current_revision_id ? history.returnToCurrent() : history.previewRevision(id)} historyDisabled={isStreaming} onRetryMessage={handleRetryMessage} retryDisabled={sendLocked || isGenerating} retryingMessageId={actionBusy || isGenerating ? retryingMessageId : null} />
                  </Suspense>
                  <RetrievalNoticeBar
                    notice={retrievalNotice}
                    onUseSearchTool={requestSearchTool}
                  />
                  <RetrievalNoticeBar
                    notice={graphNotice}
                  />
                  <ContextBar
                    selectedNode={selectedNode}
                    onSendMessage={content => { if (selectedNode) void handleSend(content, 'answer', selectedNode.node.id).catch(() => {}); }}
                    onClear={clearSelectedNode}
                  />
                  {graphEditBlocked && (
                    <p role="status" style={{ margin: '0 1rem 0.5rem', color: '#c4b5fd', fontSize: '0.75rem' }}>
                      {isSavingGraphEdit ? 'Saving component edits…' : 'Save or cancel component edits to continue.'}
                    </p>
                  )}
                  {actionError && <p role="alert" style={{ margin: '0 1rem 0.5rem', color: '#ffb4ad', fontSize: '0.8rem' }}>{actionError}</p>}
                  <ChatInput
                    hasGraph={!!graphData}
                    onSend={handleSend}
                    checkSubmission={checkSubmission}
                    onStop={stopGeneration}
                    isFinishingDiagram={isFinishingDiagram}
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
      </main>
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
