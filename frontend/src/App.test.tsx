import { useEffect, useImperativeHandle, useState } from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { flushPendingLayout } = vi.hoisted(() => ({ flushPendingLayout: vi.fn().mockResolvedValue(undefined) }));

vi.mock('./hooks/useAuthSession', () => ({ useAuthSession: vi.fn() }));
vi.mock('./hooks/useBackendReadiness', () => ({ useBackendReadiness: vi.fn() }));
vi.mock('./hooks/useSelectionSuggestion', () => ({ useSelectionSuggestion: vi.fn() }));
vi.mock('./hooks/useThreadSession', () => ({ useThreadSession: vi.fn() }));
vi.mock('./hooks/useAgentStream', () => ({ useAgentStream: vi.fn() }));

vi.mock('./services/analytics', () => ({ trackEvent: vi.fn().mockResolvedValue(undefined) }));
vi.mock('./services/api', () => ({ checkDiagramIntent: vi.fn(), fetchGraphHistory: vi.fn().mockResolvedValue({current_revision_id: null, revisions: []}), fetchGraphRevision: vi.fn(), restoreGraphRevision: vi.fn() }));
vi.mock('./services/auth', () => ({ signOut: vi.fn().mockResolvedValue(undefined) }));
vi.mock('./utils/threadState', () => ({
  shouldPersistThreadSnapshot: vi.fn(() => true),
  storageKeyForThread: vi.fn(userId => `thread:${userId}`),
  writeThreadSnapshot: vi.fn(),
}));

vi.mock('./components/GraphCanvas/HiddenGraphEvaluator', () => ({
  HiddenGraphEvaluator: ({ candidate }: { candidate: GraphCandidate | null }) => <div data-testid="hidden-evaluator">{candidate?.evaluationId}</div>,
}));

vi.mock('./components/Auth/AuthScreen', () => ({
  AuthScreen: ({ onAuthenticated }: { onAuthenticated: (session: unknown) => void }) => (
    <button onClick={() => onAuthenticated({ user: { id: 'new-user' } })}>Authenticate</button>
  ),
}));

vi.mock('./components/Layout/TitleBar', () => ({
  TitleBar: ({
    threadTitle,
    onToggleSidebar,
    onOpenDashboard,
    onOpenChat,
    onLogout,
    dashboardActive,
  }: {
    threadTitle: string;
    onToggleSidebar: () => void;
    onOpenDashboard?: () => void;
    onOpenChat?: () => void;
    onLogout: () => void;
    dashboardActive?: boolean;
  }) => (
    <header>
      <span>{threadTitle}</span>
      <button onClick={onToggleSidebar}>Toggle sidebar</button>
      <button onClick={dashboardActive ? onOpenChat : onOpenDashboard}>
        {dashboardActive ? 'Back to chat' : 'Open dashboard'}
      </button>
      <button onClick={onLogout}>Log out</button>
    </header>
  ),
}));

vi.mock('./components/Layout/SplitPane', () => ({
  SplitPane: ({ left, right, graphVisible }: {
    left: React.ReactNode;
    right: React.ReactNode;
    graphVisible: boolean;
  }) => (
    <main data-testid="split-pane" data-graph-visible={String(graphVisible)}>
      {left}
      {right}
    </main>
  ),
}));

vi.mock('./components/Layout/ThreadSidebar', () => ({
  HISTORY_OVERLAY_QUERY: '(max-width: 1279px)',
  ThreadSidebar: ({ onNewChat, onSelectThread, onDeleteThread, isOpen }: {
    onNewChat: () => void;
    onSelectThread: (threadId: string) => void;
    onDeleteThread: (threadId: string) => void;
    isOpen: boolean;
  }) => (
    <aside data-sidebar-open={String(isOpen)}>
      <button onClick={onNewChat}>New chat</button>
      <button onClick={() => onSelectThread('thread-2')}>Select thread</button>
      <button onClick={() => onDeleteThread('thread-2')}>Delete thread</button>
    </aside>
  ),
}));

vi.mock('./components/Chat/RetrievalNoticeBar', () => ({
  RetrievalNoticeBar: ({ notice, onUseSearchTool }: {
    notice: { message: string } | null;
    onUseSearchTool?: () => void;
  }) => notice ? (
    <div>
      {notice.message}
      {onUseSearchTool && <button onClick={onUseSearchTool}>Request search</button>}
    </div>
  ) : null,
}));

vi.mock('./components/Chat/ContextBar', () => ({
  ContextBar: ({ selectedNode, onSendMessage, onClear }: {
    selectedNode: unknown;
    onSendMessage: (content: string, diagramRequested?: boolean) => void;
    onClear: () => void;
  }) => selectedNode ? (
    <div>
      <button onClick={() => onSendMessage('Explain selected context')}>Ask context</button>
      <button onClick={onClear}>Clear context</button>
    </div>
  ) : null,
}));

vi.mock('./components/Chat/ChatInput', () => ({
  ChatInput: ({
    onSend,
    onStop,
    onRetryReadiness,
    onUseSelection,
    onDismissSelection,
    onClearSelectionReference,
    backendReadiness,
    sendDisabled,
  }: {
    onSend: (content: string, action?: 'ask' | 'answer' | 'new_chat') => Promise<void>;
    onStop: () => void;
    onRetryReadiness: () => void;
    onUseSelection: () => void;
    onDismissSelection: () => void;
    onClearSelectionReference: () => void;
    backendReadiness: string;
    sendDisabled?: boolean;
  }) => (
    <div>
      <button disabled={sendDisabled} onClick={() => { void onSend('User question').catch(() => {}); }}>Send message</button>
      <button disabled={sendDisabled} onClick={() => { void onSend('How do I read this diagram?', 'answer').catch(() => {}); }}>Send diagram answer</button>
      <button disabled={sendDisabled} onClick={() => { void onSend('AI trading bot?', 'ask').catch(() => {}); }}>Send broad request</button>
      <button disabled={sendDisabled} onClick={() => { void onSend('Separate topic', 'new_chat').catch(() => {}); }}>Send in new chat</button>
      <button onClick={onStop}>Stop generation</button>
      {backendReadiness === 'error' && <button onClick={onRetryReadiness}>Retry connection</button>}
      <button onClick={onUseSelection}>Use selection</button>
      <button onClick={onDismissSelection}>Dismiss selection</button>
      <button onClick={onClearSelectionReference}>Clear selection reference</button>
    </div>
  ),
}));

vi.mock('./components/GraphCanvas', () => ({
  GraphCanvas: ({ ref, graphData, isPreview, isAcceptedGraph, onNodeClick, onTellMeMore, onExpandGraph, onSaveGraphEdit, onEditDraftChange, editingDisabled }: {
    ref?: React.Ref<{flushPendingLayout: () => Promise<void>}>;
    graphData: GraphData | null;
    isPreview?: boolean;
    isAcceptedGraph?: boolean;
    onNodeClick: (node: { id: string; label: string; type: 'service'; technology: string; description: string; detail: null }) => void;
    onTellMeMore: (node: { id: string; label: string; type: 'service'; technology: string; description: string; detail: null }) => void;
    onExpandGraph: (node: { id: string; label: string; type: 'service'; technology: string; description: string; detail: null }) => void;
    onSaveGraphEdit?: (edit: { nodes: Array<{ id: string; label: string }> }) => Promise<void>;
    onEditDraftChange?: (dirty: boolean) => void;
    editingDisabled?: boolean;
  }) => {
    useImperativeHandle(ref, () => ({ flushPendingLayout }), []);
    const node = {
      id: 'retrieval',
      label: 'Retrieval API',
      type: 'service' as const,
      technology: 'FastAPI',
      description: 'Finds evidence.',
      detail: null,
    };
    return (
      <section data-testid="graph-canvas">
        <span data-testid="rendered-graph-title">{graphData?.title ?? ''}</span>
        <span data-testid="rendered-graph-preview">{isPreview ? 'yes' : 'no'}</span>
        <span data-testid="rendered-graph-accepted">{isAcceptedGraph ? 'yes' : 'no'}</span>
        <span data-testid="graph-edit-disabled">{String(editingDisabled)}</span>
        <button onClick={() => onNodeClick(node)}>Choose node</button>
        <button onClick={() => onTellMeMore(node)}>Tell me more</button>
        <button onClick={() => onExpandGraph(node)}>Expand graph</button>
        <button onClick={() => onEditDraftChange?.(true)}>Start graph edit</button>
        <button onClick={() => onEditDraftChange?.(false)}>Cancel graph edit</button>
        <button onClick={() => void onSaveGraphEdit?.({ nodes: [{ id: 'retrieval', label: 'Edited retrieval' }] })}>Save graph edit</button>
      </section>
    );
  },
}));

vi.mock('./components/Chat/MessageList', () => ({
  MessageList: ({ messages, onViewDiagram, onRetryMessage, retryDisabled }: {
    messages: Array<{ retryRequest?: unknown }>; onViewDiagram?: (id: string) => void;
    onRetryMessage?: (message: unknown) => void; retryDisabled?: boolean;
  }) => (
    <div><span data-testid="message-list">{messages.length} messages</span>
      <button onClick={() => onViewDiagram?.('old')}>View earlier answer diagram</button>
      <button onClick={() => onViewDiagram?.('current')}>View current answer diagram</button>
      {messages.filter(message => message.retryRequest).map((message, index) => (
        <button key={index} disabled={retryDisabled} onClick={() => onRetryMessage?.(message)}>Retry generation</button>
      ))}
    </div>
  ),
}));

vi.mock('./components/InternalDashboard', () => ({
  InternalDashboard: () => <div data-testid="internal-dashboard">Dashboard content</div>,
}));

import App from './App';
import { useAgentStream } from './hooks/useAgentStream';
import { useAuthSession } from './hooks/useAuthSession';
import { useBackendReadiness } from './hooks/useBackendReadiness';
import { useSelectionSuggestion } from './hooks/useSelectionSuggestion';
import { useThreadSession } from './hooks/useThreadSession';
import { trackEvent } from './services/analytics';
import { signOut } from './services/auth';
import { fetchGraphHistory, fetchGraphRevision } from './services/api';
import type { AuthSession, GraphCandidate, GraphData, ThreadDetail } from './types';
import { shouldPersistThreadSnapshot, writeThreadSnapshot } from './utils/threadState';


const session: AuthSession = {
  access_token: 'access-token',
  refresh_token: 'refresh-token',
  user: { id: 'user-1', email: 'user@example.com' },
};

const graph: GraphData = {
  graph_type: 'architecture',
  title: 'Reviewed architecture',
  nodes: [],
  edges: [],
  sequence: [],
};

const authState = {
  authReady: true,
  handleAuthenticated: vi.fn(),
  setAuthSession: vi.fn(),
  authSession: session,
};

const selectionState = {
  selectionSuggestion: null as string | null,
  selectionReferenceActive: false,
  clearSelection: vi.fn(),
  activateSelectionReference: vi.fn(),
  dismissSelection: vi.fn(),
  clearSelectionReference: vi.fn(),
};

const readinessState = {
  backendReadiness: 'ready' as const,
  prepareMessage: null,
  isBackendReady: true,
  prepareBackendNow: vi.fn(),
  clearPreparedCache: vi.fn(),
};

const threadState = {
  activeThreadId: 'thread-1',
  threadTitle: 'Architecture thread',
  loadingThread: false,
  threadError: null as string | null,
  threadSnapshot: { title: 'Architecture thread', messages: [], graphData: graph },
  handleNewChat: vi.fn(),
  handleSelectThread: vi.fn(),
  handleDeleteThread: vi.fn(),
  retryThread: vi.fn(),
};

const agentState = {
  visibleMessages: [
    { id: 'm1', role: 'user' as const, content: 'Question' },
    { id: 'm2', role: 'assistant' as const, content: 'Grounded answer' },
  ],
  answerPending: false,
  diagramRequested: false,
  acknowledgeGraphRendered: vi.fn(),
  messages: [
    { id: 'm1', role: 'user' as const, content: 'Question' },
    { id: 'm2', role: 'assistant' as const, content: 'Grounded answer' },
  ],
  graphData: graph,
  isSavingGraphEdit: false,
    publishedGraphKey: null,
    graphPreview: null,
  graphCandidate: null,
  liveActivity: null,
  workerStatus: {
    rag: null,
    graph: null,
    critic: null,
    orchestrator: null,
    research: null,
  },
  retrievalNotice: { requestId: 'request-1', message: 'Search available', requested: false },
  graphNotice: { message: 'Approved graph retained' },
  selectedNode: {
    node: {
      id: 'retrieval',
      label: 'Retrieval API',
      type: 'service' as const,
      technology: 'FastAPI',
      description: 'Finds evidence.',
      detail: null,
    },
    suggestions: ['Explain retrieval'],
  },
  selectNode: vi.fn(),
  clearSelectedNode: vi.fn(),
  streamStatus: 'connected' as const,
  providerNotice: null,
  hydrateThread: vi.fn(),
  sendMessage: vi.fn().mockReturnValue(true),
  retryMessage: vi.fn().mockResolvedValue(true),
  adoptRestoredGraph: vi.fn().mockReturnValue(true),
  startThreadAndSend: vi.fn().mockReturnValue(true),
  saveGraphEdit: vi.fn().mockResolvedValue(undefined),
  requestSearchTool: vi.fn(),
  stopGeneration: vi.fn(),
  isFinishingDiagram: false,
};


describe('App coordination', () => {
  afterEach(() => vi.unstubAllGlobals());
  beforeEach(() => {
    vi.clearAllMocks();
    flushPendingLayout.mockReset().mockResolvedValue(undefined);
    window.location.hash = '';
    localStorage.clear();
    localStorage.setItem('thread:user-1', 'cached');
    vi.mocked(useAuthSession).mockReturnValue(authState);
    vi.mocked(useSelectionSuggestion).mockReturnValue(selectionState);
    vi.mocked(useBackendReadiness).mockReturnValue(readinessState);
    vi.mocked(useThreadSession).mockReturnValue(threadState);
    vi.mocked(useAgentStream).mockReturnValue(agentState);
    vi.mocked(shouldPersistThreadSnapshot).mockReturnValue(true);
  });

  it('flushes layout before retrying and prevents duplicate clicks while the action is pending', async () => {
    const failure = { id: 'failed', role: 'assistant' as const, content: 'Generation failed', retryRequest: {
      content: 'Original prompt', complexity: 'auto' as const, graphMode: 'on' as const,
      diagramRequested: true, researchEnabled: true, graphAction: 'extend' as const,
      expectedGraphVersion: 'old',
    } };
    vi.mocked(useAgentStream).mockReturnValue({ ...agentState, messages: [failure], visibleMessages: [failure] });
    let releaseFlush!: () => void;
    flushPendingLayout.mockReturnValueOnce(new Promise<void>(resolve => { releaseFlush = resolve; }));
    render(<App />);
    await screen.findByTestId('graph-canvas');
    const retry = screen.getByRole('button', { name: 'Retry generation' }) as HTMLButtonElement;
    fireEvent.click(retry);
    expect(retry.disabled).toBe(true);
    fireEvent.click(retry);
    expect(agentState.retryMessage).not.toHaveBeenCalled();
    await act(async () => { releaseFlush(); });
    expect(agentState.retryMessage).toHaveBeenCalledExactlyOnceWith(failure, null);
    expect(agentState.sendMessage).not.toHaveBeenCalled();
  });

  it.each(['Select thread', 'New chat'])('closes compact history after saving layout for %s', async (action) => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({
      matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn(),
    })));
    let resolveLayout!: () => void;
    flushPendingLayout.mockReturnValue(new Promise<void>(resolve => { resolveLayout = resolve; }));
    render(<App />);
    await screen.findByTestId('graph-canvas');
    await waitFor(() => expect((screen.getByText('Send in new chat') as HTMLButtonElement).disabled).toBe(false));
    expect(document.querySelector('[data-sidebar-open]')?.getAttribute('data-sidebar-open')).toBe('false');
    fireEvent.click(screen.getByText('Toggle sidebar'));
    expect(document.querySelector('[data-sidebar-open]')?.getAttribute('data-sidebar-open')).toBe('true');
    fireEvent.click(screen.getByText(action));
    expect(threadState.handleSelectThread).not.toHaveBeenCalled();
    expect(threadState.handleNewChat).not.toHaveBeenCalled();
    expect(document.querySelector('[data-sidebar-open]')?.getAttribute('data-sidebar-open')).toBe('true');
    await act(async () => { resolveLayout(); });
    if (action === 'Select thread') expect(threadState.handleSelectThread).toHaveBeenCalledWith('thread-2');
    else expect(threadState.handleNewChat).toHaveBeenCalledOnce();
    expect(document.querySelector('[data-sidebar-open]')?.getAttribute('data-sidebar-open')).toBe('false');
  });

  it('tracks the visible keyboard viewport while preserving pinch zoom and cleaning up listeners', () => {
    const viewport = Object.assign(new EventTarget(), { height: 844, offsetTop: 0, scale: 1 });
    const remove = vi.spyOn(viewport, 'removeEventListener');
    vi.stubGlobal('visualViewport', viewport);
    const { container, unmount } = render(<App />);
    const shell = container.querySelector<HTMLElement>('.app-viewport')!;
    expect(shell.style.getPropertyValue('--workspace-height')).toBe('844px');
    act(() => {
      viewport.height = 410;
      viewport.offsetTop = 30;
      viewport.dispatchEvent(new Event('resize'));
    });
    expect(shell.style.getPropertyValue('--workspace-height')).toBe('410px');
    expect(shell.style.getPropertyValue('--workspace-top')).toBe('30px');
    act(() => {
      viewport.scale = 2;
      viewport.dispatchEvent(new Event('resize'));
    });
    expect(shell.style.getPropertyValue('--workspace-height')).toBe('');
    expect(shell.style.getPropertyValue('--workspace-top')).toBe('');
    unmount();
    expect(remove.mock.calls.map(([name]) => name)).toEqual(['resize', 'scroll']);
  });

  it('renders a bounded loading state before authentication initializes', () => {
    vi.mocked(useAuthSession).mockReturnValue({ ...authState, authReady: false });

    render(<App />);

    expect(screen.getByText('Loading session…')).toBeTruthy();
    expect(screen.queryByTestId('split-pane')).toBeNull();
  });

  it('coordinates authenticated chat, graph, selection, and thread actions', async () => {
    render(<App />);

    await screen.findByTestId('graph-canvas');
    await waitFor(() => expect((screen.getByText('Send message') as HTMLButtonElement).disabled).toBe(false));
    expect(screen.getAllByTestId('hidden-evaluator')).toHaveLength(1);
    expect(screen.getByTestId('split-pane').dataset.graphVisible).toBe('true');
    expect(agentState.hydrateThread).toHaveBeenCalledWith(threadState.threadSnapshot);
    expect(writeThreadSnapshot).toHaveBeenCalledWith(
      'user-1',
      'thread-1',
      expect.objectContaining({ title: 'Architecture thread', graphData: graph }),
    );

    await waitFor(() => expect((screen.getByText('Send message') as HTMLButtonElement).disabled).toBe(false));
    await act(async () => { fireEvent.click(screen.getByText('Send message')); });
    expect(selectionState.clearSelection).toHaveBeenCalled();
    expect(agentState.sendMessage).toHaveBeenCalledWith(
      'User question',
      expect.objectContaining({
        complexity: 'auto',
        graphMode: 'on',
        researchEnabled: true,
      }),
    );

    fireEvent.click(screen.getByText('Choose node'));
    await act(async () => { fireEvent.click(screen.getByText('Tell me more')); });
    await act(async () => { fireEvent.click(screen.getByText('Expand graph')); });
    expect(agentState.selectNode).toHaveBeenCalled();
    expect(agentState.sendMessage).toHaveBeenCalledWith(
      expect.stringContaining('Tell me more about Retrieval API'),
      expect.any(Object),
    );
    expect(agentState.sendMessage).toHaveBeenCalledWith(
      expect.stringContaining('Expand the current graph around Retrieval API'),
      expect.objectContaining({ graphMode: 'on' }),
    );
    expect(agentState.clearSelectedNode).toHaveBeenCalled();
    expect(trackEvent).toHaveBeenCalledWith(
      'node_selected',
      expect.objectContaining({ node_id: 'retrieval' }),
      session,
    );
    expect(trackEvent).toHaveBeenCalledWith(
      'expand_graph_clicked',
      expect.objectContaining({ node_id: 'retrieval' }),
      session,
    );

    await act(async () => { fireEvent.click(screen.getByText('Ask context')); });
    fireEvent.click(screen.getByText('Clear context'));
    fireEvent.click(screen.getByText('Request search'));
    fireEvent.click(screen.getByText('Stop generation'));
    expect(agentState.requestSearchTool).toHaveBeenCalledTimes(1);
    expect(agentState.stopGeneration).toHaveBeenCalledTimes(1);

    await act(async () => { fireEvent.click(screen.getByText('New chat')); });
    await act(async () => { fireEvent.click(screen.getByText('Select thread')); });
    fireEvent.click(screen.getByText('Delete thread'));
    expect(threadState.handleNewChat).toHaveBeenCalledTimes(1);
    expect(threadState.handleSelectThread).toHaveBeenCalledWith('thread-2');
    expect(threadState.handleDeleteThread).toHaveBeenCalledWith('thread-2');

    fireEvent.click(screen.getByText('Toggle sidebar'));
    expect(screen.getByText('New chat').parentElement?.dataset.sidebarOpen).toBe('false');
  });

  it('keeps the current thread when pending layout cannot be saved', async () => {
    flushPendingLayout.mockRejectedValue(new Error('Layout save failed'));
    render(<App />);
    await screen.findByTestId('graph-canvas');
    await waitFor(() => expect((screen.getByText('Send in new chat') as HTMLButtonElement).disabled).toBe(false));
    await act(async () => { fireEvent.click(screen.getByText('Select thread')); });
    expect(threadState.handleSelectThread).not.toHaveBeenCalled();
    expect(screen.getByRole('alert').textContent).toBe('Layout save failed');
  });

  it('does not create a chat after unmount while waiting for layout persistence', async () => {
    let resolve!: () => void;
    flushPendingLayout.mockReturnValue(new Promise<void>(done => { resolve = done; }));
    const view = render(<App />);
    await screen.findByTestId('graph-canvas');
    await waitFor(() => expect((screen.getByText('Send in new chat') as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByText('New chat'));
    expect(flushPendingLayout).toHaveBeenCalledOnce();
    view.unmount();
    await act(async () => resolve());
    expect(threadState.handleNewChat).not.toHaveBeenCalled();
  });

  it('waits for initial history before sending or creating a chat', async () => {
    let resolveHistory!: (value: { current_revision_id: null; revisions: [] }) => void;
    vi.mocked(fetchGraphHistory).mockReturnValueOnce(new Promise(done => { resolveHistory = done; }));
    render(<App />);
    await screen.findByTestId('graph-canvas');
    expect(screen.getByText('Updating history…')).toBeTruthy();
    expect((screen.getByText('Send in new chat') as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByText('Send message') as HTMLButtonElement).disabled).toBe(true);
    await act(async () => { fireEvent.click(screen.getByText('Send message')); });
    await act(async () => { fireEvent.click(screen.getByText('Send in new chat')); });
    expect(agentState.sendMessage).not.toHaveBeenCalled();
    expect(selectionState.clearSelection).not.toHaveBeenCalled();
    expect(threadState.handleNewChat).not.toHaveBeenCalled();
    await act(async () => resolveHistory({ current_revision_id: null, revisions: [] }));
    expect((screen.getByText('Send message') as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByText('Send in new chat') as HTMLButtonElement).disabled).toBe(false);
    await act(async () => { fireEvent.click(screen.getByText('Send message')); });
    expect(agentState.sendMessage).toHaveBeenCalledExactlyOnceWith('User question', expect.any(Object));
    expect(selectionState.clearSelection).toHaveBeenCalledOnce();
    await act(async () => { fireEvent.click(screen.getByText('Send in new chat')); });
    expect(threadState.handleNewChat).toHaveBeenCalledWith({ preserveCurrentView: true });
  });

  it('accepts its created thread when React commits that selection before creation resolves', async () => {
    let resolve!: (thread: ThreadDetail) => void;
    const create = vi.fn(() => new Promise<ThreadDetail>(done => { resolve = done; }));
    vi.mocked(useThreadSession).mockReturnValue({ ...threadState, handleNewChat: create });
    const view = render(<App />);
    await screen.findByTestId('graph-canvas');
    await waitFor(() => expect((screen.getByText('Send in new chat') as HTMLButtonElement).disabled).toBe(false));
    await act(async () => { fireEvent.click(screen.getByText('Send in new chat')); });
    expect(create).toHaveBeenCalledWith({ preserveCurrentView: true });
    const created: ThreadDetail = {
      thread: { id: 'created-thread', title: 'New chat', graph_data: null, created_at: '', updated_at: '', last_seen_at: '' },
      messages: [],
    };
    vi.mocked(useThreadSession).mockReturnValue({ ...threadState, activeThreadId: created.thread.id, handleNewChat: create });
    view.rerender(<App />);
    await act(async () => resolve(created));
    expect(agentState.startThreadAndSend).toHaveBeenCalledExactlyOnceWith(created, 'Separate topic', expect.objectContaining({ graphAction: 'new' }));
    expect(agentState.sendMessage).not.toHaveBeenCalled();
    expect(screen.queryByText('The conversation changed. Please try again.')).toBeNull();
  });

  it('returns to the current diagram when its answer link is selected during an older preview', async () => {
    vi.mocked(fetchGraphHistory).mockResolvedValueOnce({
      current_revision_id: 'current',
      revisions: ['old', 'current'].map((id, index) => ({ id, parent_revision_id: index ? 'old' : null, revision_number: index + 1, label: id, created_at: '', node_count: 0, edge_count: 0 })),
    });
    vi.mocked(fetchGraphRevision).mockResolvedValueOnce({ revision_id: 'old', graph_data: { ...graph, title: 'Earlier diagram', version: 'old' } });
    render(<App />);
    await screen.findByRole('option', { name: 'Version 2 (current)' });
    await act(async () => { fireEvent.click(screen.getByText('View earlier answer diagram')); });
    expect(screen.getByTestId('rendered-graph-title').textContent).toBe('Earlier diagram');
    expect(screen.getByText('Preview')).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByText('View current answer diagram')); });
    expect(screen.getByTestId('rendered-graph-title').textContent).toBe(graph.title);
    expect(screen.queryByText('Preview')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Restore' })).toBeNull();
    expect(fetchGraphRevision).toHaveBeenCalledExactlyOnceWith(session, 'thread-1', 'old');
  });

  it('blocks steering while an accepted diagram is finishing', async () => {
    vi.mocked(useAgentStream).mockReturnValue({ ...agentState, streamStatus: 'generating', isFinishingDiagram: true });
    render(<App />);
    await screen.findByTestId('graph-canvas');
    await act(async () => { fireEvent.click(screen.getByText('Send message')); });
    expect(agentState.sendMessage).not.toHaveBeenCalled();
  });

  it('blocks chat and thread changes while a graph edit draft is open', async () => {
    render(<App />);
    await screen.findByTestId('graph-canvas');
    fireEvent.click(screen.getByText('Start graph edit'));

    expect(screen.getByText('Save or cancel component edits to continue.')).toBeTruthy();
    const unload = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(unload);
    expect(unload.defaultPrevented).toBe(true);
    await act(async () => { fireEvent.click(screen.getByText('Send message')); });
    await act(async () => { fireEvent.click(screen.getByText('New chat')); });
    await act(async () => { fireEvent.click(screen.getByText('Select thread')); });
    fireEvent.click(screen.getByText('Delete thread'));
    await act(async () => { fireEvent.click(screen.getByText('Expand graph')); });
    expect(agentState.sendMessage).not.toHaveBeenCalled();
    expect(threadState.handleNewChat).not.toHaveBeenCalled();
    expect(threadState.handleSelectThread).not.toHaveBeenCalled();
    expect(threadState.handleDeleteThread).not.toHaveBeenCalled();

    fireEvent.click(screen.getByText('Cancel graph edit'));
    expect(screen.queryByText('Save or cancel component edits to continue.')).toBeNull();
    await act(async () => { fireEvent.click(screen.getByText('Send message')); });
    expect(agentState.sendMessage).toHaveBeenCalledTimes(1);
  });

  it('wires graph edits to the hook and disables editing while save is pending', async () => {
    vi.mocked(useAgentStream).mockReturnValue({ ...agentState, isSavingGraphEdit: true });
    render(<App />);
    await screen.findByTestId('graph-canvas');
    expect(screen.getByTestId('graph-edit-disabled').textContent).toBe('true');
    expect(screen.getByText('Saving component edits…')).toBeTruthy();
    fireEvent.click(screen.getByText('Save graph edit'));
    expect(agentState.saveGraphEdit).toHaveBeenCalledWith({
      nodes: [{ id: 'retrieval', label: 'Edited retrieval' }],
    });
  });

  it('renders a preview without writing it into the durable thread snapshot', async () => {
    const preview = { ...graph, title: 'Private preview', detail_level: 'overview' as const };
    vi.mocked(useAgentStream).mockReturnValue({ ...agentState, graphPreview: preview });

    render(<App />);

    await screen.findByTestId('graph-canvas');
    expect(screen.getByTestId('rendered-graph-title').textContent).toBe('Private preview');
    expect(screen.getByTestId('rendered-graph-preview').textContent).toBe('yes');
    expect(screen.getByTestId('rendered-graph-accepted').textContent).toBe('no');
    expect(writeThreadSnapshot).toHaveBeenCalledWith(
      'user-1',
      'thread-1',
      expect.objectContaining({ graphData: graph }),
    );
  });

  it('keeps the connected graph visible during a component-only expansion preview', async () => {
    const connected = { ...graph, detail_level: 'overview' as const, edges: [{ source: 'a', target: 'b', label: 'Request', technology: '', sync: 'sync' as const, description: '' }] };
    vi.mocked(useAgentStream).mockReturnValue({ ...agentState, graphData: connected,
      graphPreview: { ...graph, title: 'Components only', edges: [] } });
    render(<App />);
    await screen.findByTestId('graph-canvas');
    expect(screen.getByTestId('rendered-graph-title').textContent).toBe(graph.title);
    expect(screen.getByTestId('rendered-graph-preview').textContent).toBe('yes');
    expect(screen.getByTestId('rendered-graph-accepted').textContent).toBe('yes');
  });

  it('sends answer mode in the current thread and retains its diagram and conversation', async () => {
    render(<App />);
    await screen.findByTestId('graph-canvas');
    await waitFor(() => expect((screen.getByText('Send diagram answer') as HTMLButtonElement).disabled).toBe(false));

    await act(async () => { fireEvent.click(screen.getByText('Send diagram answer')); });

    expect(flushPendingLayout).toHaveBeenCalledOnce();
    expect(agentState.sendMessage).toHaveBeenCalledExactlyOnceWith(
      'How do I read this diagram?',
      expect.objectContaining({ graphAction: 'answer', displayContent: 'How do I read this diagram?' }),
    );
    expect(threadState.handleNewChat).not.toHaveBeenCalled();
    expect(agentState.startThreadAndSend).not.toHaveBeenCalled();
    expect(useAgentStream).toHaveBeenLastCalledWith(session, 'thread-1');
    expect(screen.getByTestId('rendered-graph-title').textContent).toBe(graph.title);
    expect(screen.getByTestId('rendered-graph-accepted').textContent).toBe('yes');
    expect(screen.getByTestId('message-list').textContent).toBe('2 messages');
    expect(screen.getByText('Architecture thread')).toBeTruthy();
  });

  it('preserves highlighted text in an answer-mode request before clearing selection', async () => {
    vi.mocked(useSelectionSuggestion).mockReturnValue({
      ...selectionState,
      selectionSuggestion: 'A selected architecture passage',
      selectionReferenceActive: true,
    });
    render(<App />);
    await screen.findByTestId('graph-canvas');
    await waitFor(() => expect((screen.getByText('Send diagram answer') as HTMLButtonElement).disabled).toBe(false));

    await act(async () => { fireEvent.click(screen.getByText('Send diagram answer')); });

    expect(agentState.sendMessage).toHaveBeenCalledExactlyOnceWith(
      ['Explain this highlighted part in beginner-friendly terms and relate it to the diagram.', '',
        'Highlighted text: "A selected architecture passage"', '',
        'User question: How do I read this diagram?'].join('\n'),
      expect.objectContaining({
        graphAction: 'answer',
        displayContent: 'How do I read this diagram?',
        hasSelectedTextContext: true,
      }),
    );
    expect(selectionState.clearSelection).toHaveBeenCalledOnce();
    expect(agentState.sendMessage.mock.invocationCallOrder[0]).toBeLessThan(selectionState.clearSelection.mock.invocationCallOrder[0]);
    expect(threadState.handleNewChat).not.toHaveBeenCalled();
    expect(agentState.startThreadAndSend).not.toHaveBeenCalled();
  });

  it('grounds a selected-text request with fixed generation settings', async () => {
    vi.mocked(useSelectionSuggestion).mockReturnValue({
      ...selectionState,
      selectionSuggestion: 'A selected architecture passage',
      selectionReferenceActive: true,
    });
    render(<App />);
    await screen.findByTestId('graph-canvas');

    fireEvent.click(screen.getByText('Use selection'));
    fireEvent.click(screen.getByText('Dismiss selection'));
    fireEvent.click(screen.getByText('Clear selection reference'));
    await act(async () => { fireEvent.click(screen.getByText('Send message')); });

    expect(agentState.sendMessage).toHaveBeenLastCalledWith(
      expect.stringContaining('Highlighted text: "A selected architecture passage"'),
      expect.objectContaining({
        complexity: 'auto',
        graphMode: 'on',
        researchEnabled: true,
        hasSelectedTextContext: true,
      }),
    );
    expect(trackEvent).not.toHaveBeenCalledWith('mode_changed', expect.anything(), expect.anything());
  });

  it('blocks sending and thread retry while the backend warms', async () => {
    vi.mocked(useBackendReadiness).mockReturnValue({
      ...readinessState,
      backendReadiness: 'preparing',
      isBackendReady: false,
    });
    vi.mocked(useThreadSession).mockReturnValue({
      ...threadState,
      threadError: 'database unavailable',
    });
    render(<App />);

    await act(async () => { fireEvent.click(screen.getByText('Send message')); });
    expect(agentState.sendMessage).not.toHaveBeenCalled();
    expect(screen.queryByText('Prepare backend')).toBeNull();
    expect(screen.queryByText('Retry connection')).toBeNull();
    const retry = screen.getByRole('button', { name: 'Retry' });
    expect((retry as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(retry);
    expect(readinessState.prepareBackendNow).not.toHaveBeenCalled();
    expect(threadState.retryThread).not.toHaveBeenCalled();
  });

  it('connects the explicit readiness retry action only after startup fails', () => {
    vi.mocked(useBackendReadiness).mockReturnValue({
      ...readinessState,
      backendReadiness: 'error',
      isBackendReady: false,
    });
    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: 'Retry connection' }));
    expect(readinessState.prepareBackendNow).toHaveBeenCalledOnce();
    expect(screen.queryByText('Prepare backend')).toBeNull();
  });

  it('shows a thread creation error with an available retry', () => {
    vi.mocked(useThreadSession).mockReturnValue({
      ...threadState,
      activeThreadId: null,
      loadingThread: false,
      threadError: 'Could not start a new chat. Try again.',
    });
    render(<App />);

    const alert = screen.getByRole('alert');
    expect(alert.textContent).toContain('Could not start a new chat. Try again.');
    expect(alert.textContent).not.toContain('Backend unreachable');
    const retry = screen.getByRole('button', { name: 'Retry' });
    expect((retry as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(retry);
    expect(threadState.retryThread).toHaveBeenCalledTimes(1);
  });

  it('prevents duplicate thread retries while a thread is loading', () => {
    vi.mocked(useThreadSession).mockReturnValue({
      ...threadState,
      loadingThread: true,
      threadError: 'Could not open this chat. Try again.',
    });
    render(<App />);

    const retry = screen.getByRole('button', { name: 'Retry' });
    expect((retry as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(retry);
    expect(threadState.retryThread).not.toHaveBeenCalled();
  });

  it('isolates workspace state by account while retaining it across token refresh', async () => {
    const mountedOwners: string[] = [];
    const cleanedOwners: string[] = [];
    vi.mocked(useThreadSession).mockImplementation(({ authSession }) => {
      const [owner] = useState(() => authSession?.user.id ?? 'signed-out');
      const ownedGraph = owner === 'user-1' ? graph : null;
      const ownedMessages = owner === 'user-1' ? agentState.messages : [];
      return {
        ...threadState,
        activeThreadId: owner === 'signed-out' ? null : `thread-${owner}`,
        threadTitle: owner === 'user-1' ? 'Account A chat' : 'New chat',
        threadSnapshot: {
          title: owner === 'user-1' ? 'Account A chat' : 'New chat',
          messages: ownedMessages,
          graphData: ownedGraph,
        },
      };
    });
    vi.mocked(useAgentStream).mockImplementation((authSession) => {
      const [owner] = useState(() => authSession?.user.id ?? 'signed-out');
      useEffect(() => {
        mountedOwners.push(owner);
        return () => { cleanedOwners.push(owner); };
      }, [owner]);
      const ownedMessages = owner === 'user-1' ? agentState.messages : [];
      return {
        ...agentState,
        messages: ownedMessages,
        visibleMessages: ownedMessages,
        graphData: owner === 'user-1' ? graph : null,
        selectedNode: null,
      };
    });

    const view = render(<App />);
    await screen.findByTestId('graph-canvas');
    expect(screen.getByTestId('rendered-graph-title').textContent).toBe('Reviewed architecture');
    expect(mountedOwners).toEqual(['user-1']);
    expect(cleanedOwners).toEqual([]);

    const refreshedSession = { ...session, access_token: 'refreshed-token' };
    vi.mocked(useAuthSession).mockReturnValue({ ...authState, authSession: refreshedSession });
    view.rerender(<App />);
    expect(mountedOwners).toEqual(['user-1']);
    expect(cleanedOwners).toEqual([]);
    expect(screen.getByTestId('rendered-graph-title').textContent).toBe('Reviewed architecture');

    const otherSession = {
      ...session,
      access_token: 'account-b-token',
      user: { ...session.user, id: 'user-2' },
    };
    vi.mocked(useAuthSession).mockReturnValue({ ...authState, authSession: otherSession });
    view.rerender(<App />);
    expect(cleanedOwners).toEqual(['user-1']);
    expect(mountedOwners).toEqual(['user-1', 'user-2']);
    expect(screen.getByTestId('rendered-graph-title').textContent).toBe('');
    expect(screen.getByTestId('message-list').textContent).toBe('0 messages');
    expect(writeThreadSnapshot).toHaveBeenCalledWith('user-2', 'thread-user-2', {
      title: 'New chat',
      messages: [],
      graphData: null,
    });
    expect(vi.mocked(writeThreadSnapshot).mock.calls
      .filter(([userId]) => userId === 'user-2')
      .every(([, , snapshot]) => snapshot.graphData === null && snapshot.messages.length === 0)).toBe(true);
  });

  it('keeps the private candidate evaluator mounted across routes with no published graph', async () => {
    vi.mocked(useAgentStream).mockReturnValue({
      ...agentState,
      graphData: null,
      graphPreview: null,
      graphCandidate: {
        evaluationId: 'candidate-1',
        graphVersion: 'version-1',
        criteria: { viewport_width: 1440, viewport_height: 960, minimum_text_px: 11 },
        data: graph,
      },
    });
    window.location.hash = '#/internal/dashboard';
    render(<App />);
    await screen.findByTestId('internal-dashboard');
    const evaluator = screen.getByTestId('hidden-evaluator');
    expect(evaluator.textContent).toBe('candidate-1');
    fireEvent.click(screen.getByText('Back to chat'));
    await screen.findByTestId('graph-canvas');
    expect(screen.getAllByTestId('hidden-evaluator')).toEqual([evaluator]);
    fireEvent.click(screen.getByText('Open dashboard'));
    await screen.findByTestId('internal-dashboard');
    expect(screen.getAllByTestId('hidden-evaluator')).toEqual([evaluator]);
  });

  it('moves between dashboard and chat and clears local state on logout', async () => {
    window.location.hash = '#/internal/dashboard';
    render(<App />);

    await screen.findByTestId('internal-dashboard');
    const evaluator = screen.getByTestId('hidden-evaluator');
    expect(screen.getByText('Internal dashboard')).toBeTruthy();
    fireEvent.click(screen.getByText('Back to chat'));
    await screen.findByTestId('split-pane');
    expect(window.location.hash).toBe('');
    expect(screen.getByTestId('hidden-evaluator')).toBe(evaluator);

    fireEvent.click(screen.getByText('Open dashboard'));
    await screen.findByTestId('internal-dashboard');
    expect(window.location.hash).toBe('#/internal/dashboard');
    expect(screen.getAllByTestId('hidden-evaluator')).toEqual([evaluator]);

    fireEvent.click(screen.getByText('Log out'));
    await waitFor(() => expect(signOut).toHaveBeenCalledTimes(1));
    expect(localStorage.getItem('thread:user-1')).toBeNull();
    expect(readinessState.clearPreparedCache).toHaveBeenCalledTimes(1);
    expect(authState.setAuthSession).toHaveBeenCalledWith(null);
  });

  it('requests a diagram for a broad learner message without a confirmation', async () => {
    vi.mocked(useSelectionSuggestion).mockReturnValue({ ...selectionState, selectionSuggestion: null, selectionReferenceActive: false });
    vi.mocked(useAgentStream).mockReturnValue({ ...agentState, graphData: null });
    render(<App />);
    await screen.findByText('Send broad request');
    await act(async () => { fireEvent.click(screen.getByText('Send broad request')); });
    expect(agentState.sendMessage).toHaveBeenCalledWith('AI trading bot?', expect.objectContaining({
      graphAction: 'new', graphMode: 'on', complexity: 'auto', researchEnabled: true, displayContent: 'AI trading bot?',
    }));
  });

  it('keeps the diagram pane after a graphless completion and displays only released messages', async () => {
    vi.mocked(useAgentStream).mockReturnValue({
      ...agentState,
      graphData: null,
      diagramRequested: true,
      answerPending: true,
      visibleMessages: [agentState.messages[0]],
    });
    render(<App />);
    const pane = await screen.findByTestId('split-pane');
    expect(pane.getAttribute('data-graph-visible')).toBe('true');
    expect(screen.getByTestId('message-list').textContent).toBe('1 messages');
  });

  it('shows authentication and skips persistence without an active session', () => {
    vi.mocked(useAuthSession).mockReturnValue({ ...authState, authSession: null });
    vi.mocked(useThreadSession).mockReturnValue({
      ...threadState,
      activeThreadId: null,
      threadTitle: '',
    });
    vi.mocked(useAgentStream).mockReturnValue({
      ...agentState,
      graphData: null,
      graphCandidate: null,
      selectedNode: null,
      streamStatus: 'disconnected',
    });
    render(<App />);

    expect(screen.getByText('Authenticate')).toBeTruthy();
    expect(screen.getByText('New chat', { selector: 'span' })).toBeTruthy();
    expect(writeThreadSnapshot).not.toHaveBeenCalled();
  });
});
