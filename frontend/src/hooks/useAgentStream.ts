// ─────────────────────────────────────────────────────────────────────────────
// File: frontend/src/hooks/useAgentStream.ts
// Purpose: React hook that wraps the agent transport and dispatches incoming
//          WebSocket/SSE events to the correct state update handlers.
//          Components call sendMessage/selectNode — they never touch
//          transport details directly.
//
//          streamStatus semantics:
//            'connected'    — idle, ready to send
//            'generating'   — a request stream is in flight
//            'disconnected' — not used (all transient errors recover to 'connected')
//
//          providerNotice — non-null while a response is being served by the
//            OpenAI fallback (cleared on 'done').
//
// Language: TypeScript
// Connects to: services/agentTransport.ts, types/index.ts
// ─────────────────────────────────────────────────────────────────────────────

import { useCallback, useEffect, useRef, useState } from 'react';
import { isSupportedDiagramEvaluationCriteria } from '../diagramEvaluationContract';
import { agentTransport, ChatTurnTimeoutError, createClientRequestId } from '../services/agentTransport';
import { fetchThread, saveGraphContentEdit } from '../services/api';
import { trackEvent } from '../services/analytics';
import type {
  AuthSession,
  ComplexityLevel,
  GraphCandidate,
  GraphContentEdit,
  GraphNotice,
  GraphData,
  GraphMode,
  GraphNode,
  Message,
  RetrievalNotice,
  SelectedNode,
  ServerEvent,
  SendOptions,
  ThreadDetail,
  WorkerStatus,
  WorkflowProgress,
} from '../types';
import { graphStructureKey } from '../utils/graphStructureKey';
import { mapThreadMessages, type ThreadSnapshot } from '../utils/threadState';
import { normalizeGraphData } from '../utils/graphData';
import { initialNodeSuggestions } from './nodeSuggestions';

function makeId() {
  return createClientRequestId();
}

const GRAPH_PAINT_GRACE_MS = 3000;
const EMPTY_RESPONSE_MESSAGE = 'The response could not be completed. Please try again.';

const IDLE_WORKER_STATUS: WorkerStatus = {
  rag: null,
  graph: null,
  critic: null,
  orchestrator: null,
  research: null,
};

const OPTIMISTIC_CHAT_STATUS: WorkerStatus = {
  ...IDLE_WORKER_STATUS,
  orchestrator: 'Question received — starting the workflow…',
};

// graphStructureKey imported from ../utils/graphStructureKey

export function useAgentStream(authSession: AuthSession | null, activeThreadId: string | null) {
  const mountedRef = useRef(false);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);
  const [messages,     setMessages]     = useState<Message[]>([]);
  const [graphData,    setGraphData]    = useState<GraphData | null>(null);
  const [isSavingGraphEdit, setIsSavingGraphEdit] = useState(false);
  const [publishedGraphKey, setPublishedGraphKey] = useState<string | null>(null);
  const [graphPreview, setGraphPreview] = useState<GraphData | null>(null);
  const [workerStatus, setWorkerStatus] = useState<WorkerStatus>(IDLE_WORKER_STATUS);
  const [retrievalNotice, setRetrievalNotice] = useState<RetrievalNotice | null>(null);
  const [graphNotice, setGraphNotice] = useState<GraphNotice | null>(null);
  const [selectedNode, setSelectedNode] = useState<SelectedNode | null>(null);
  const [graphCandidate, setGraphCandidate] = useState<GraphCandidate | null>(null);
  const [workflowProgress, setWorkflowProgress] = useState<WorkflowProgress[]>([]);
  const [answerTurn, setAnswerTurn] = useState<{ userId: string; diagram: boolean } | null>(null);
  const [paintGraceExpiredTurnId, setPaintGraceExpiredTurnId] = useState<string | null>(null);
  const [renderedGraphKey, setRenderedGraphKey] = useState<string | null>(null);
  const acknowledgeGraphRendered = useCallback((key: string) => setRenderedGraphKey(key), []);

  // 'connected' = idle, 'generating' = stream in flight
  const [streamStatus, setStreamStatus] = useState<'generating' | 'connected' | 'disconnected'>('connected');

  // Non-null while the response is being served by the OpenAI fallback
  const [providerNotice, setProviderNotice] = useState<string | null>(null);

  // Tracks the ID of the assistant message currently being streamed
  const streamingIdRef = useRef<string | null>(null);
  const activeChatStreamIdRef = useRef<string | null>(null);
  const activeThreadIdRef = useRef<string | null>(activeThreadId);
  const graphEditEpochRef = useRef(0);
  const graphEditInFlightRef = useRef(false);
  const activeNodeStreamIdRef = useRef<string | null>(null);
  const authSessionRef = useRef<AuthSession | null>(authSession);
  const graphDataRef = useRef<GraphData | null>(null);
  const durableGraphDataRef = useRef<GraphData | null>(null);
  const selectedNodeRef = useRef<SelectedNode | null>(null);
  const activeChatTerminalRef = useRef<string | null>(null);
  const turnOutputRef = useRef({ text: false, graph: false, initialGraphKey: 'null' });
  const activeExplanationMessageIdsRef = useRef<string[]>([]);
  const activeChatAnalyticsRef = useRef<{
    threadId: string;
    clientRequestId: string;
    complexity: ComplexityLevel;
    graphMode: GraphMode;
    researchEnabled: boolean;
    backendReadinessState?: string;
    hasSelectedTextContext?: boolean;
  } | null>(null);

  // Caches suggested questions per node ID so repeat clicks skip the LLM call
  const suggestionsCacheRef = useRef<Map<string, string[]>>(new Map());
  const lastGraphKeyRef = useRef<string>('null');

  const resetThreadView = useCallback(() => {
    graphEditEpochRef.current += 1;
    graphEditInFlightRef.current = false;
    setIsSavingGraphEdit(false);
    const chatRequestId = activeChatStreamIdRef.current;
    const nodeRequestId = activeNodeStreamIdRef.current;
    activeChatStreamIdRef.current = null;
    activeNodeStreamIdRef.current = null;
    if (chatRequestId) agentTransport.stopGeneration(chatRequestId);
    if (nodeRequestId) agentTransport.cancelNodeSelection(nodeRequestId);
    setMessages([]);
    setAnswerTurn(null);
    setPaintGraceExpiredTurnId(null);
    turnOutputRef.current = { text: false, graph: false, initialGraphKey: 'null' };
    setRenderedGraphKey(null);
    setGraphData(null);
    setPublishedGraphKey(null);
    setGraphPreview(null);
    setSelectedNode(null);
    setGraphCandidate(null);
    setWorkflowProgress([]);
    activeExplanationMessageIdsRef.current = [];
    graphDataRef.current = null;
    durableGraphDataRef.current = null;
    selectedNodeRef.current = null;
    suggestionsCacheRef.current.clear();
    lastGraphKeyRef.current = 'null';
    streamingIdRef.current = null;
    activeChatAnalyticsRef.current = null;
    activeChatTerminalRef.current = null;
    setWorkerStatus(IDLE_WORKER_STATUS);
    setRetrievalNotice(null);
    setGraphNotice(null);
    setProviderNotice(null);
    setStreamStatus('connected');
  }, []);

  useEffect(() => {
    if (activeThreadIdRef.current !== activeThreadId) {
      activeThreadIdRef.current = activeThreadId;
      resetThreadView();
    }
    return () => {
      // An explicit fresh-thread handoff may already own the next stream.
      if (activeThreadIdRef.current !== activeThreadId) return;
      const chatRequestId = activeChatStreamIdRef.current;
      const nodeRequestId = activeNodeStreamIdRef.current;
      activeChatStreamIdRef.current = null;
      activeNodeStreamIdRef.current = null;
      if (chatRequestId) agentTransport.stopGeneration(chatRequestId);
      if (nodeRequestId) agentTransport.cancelNodeSelection(nodeRequestId);
    };
  }, [activeThreadId, resetThreadView]);

  useEffect(() => {
    authSessionRef.current = authSession;
  }, [authSession]);

  useEffect(() => {
    graphDataRef.current = graphData;
  }, [graphData]);

  useEffect(() => {
    selectedNodeRef.current = selectedNode;
  }, [selectedNode]);

  const hydrateThread = useCallback((thread: Pick<ThreadSnapshot, 'threadId' | 'messages' | 'graphData'>) => {
    if (thread.threadId && thread.threadId === activeThreadIdRef.current && activeChatStreamIdRef.current) return;
    resetThreadView();
    setMessages(thread.messages);
    const nextGraph = normalizeGraphData(thread.graphData);
    lastGraphKeyRef.current = graphStructureKey(nextGraph);
    graphDataRef.current = nextGraph;
    durableGraphDataRef.current = nextGraph;
    setGraphData(nextGraph);
  }, [resetThreadView]);

  const publishGraph = useCallback((nextGraph: GraphData | null) => {
    const nextGraphKey = graphStructureKey(nextGraph);
    const graphChanged = lastGraphKeyRef.current !== nextGraphKey;
    lastGraphKeyRef.current = nextGraphKey;

    if (graphChanged) {
      setPublishedGraphKey(nextGraph ? nextGraphKey : null);
      suggestionsCacheRef.current.clear();
      setGraphNotice(null);
    }
    const currentSelected = selectedNodeRef.current;
    if (currentSelected) {
      const liveNode = nextGraph?.nodes.find(
        (node) => node.id === currentSelected.node.id,
      );
      const nextSelection = liveNode
        ? {
            node: liveNode,
            suggestions: graphChanged
              ? initialNodeSuggestions(liveNode.label)
              : currentSelected.suggestions,
          }
        : null;
      selectedNodeRef.current = nextSelection;
      setSelectedNode(nextSelection);
    }

    const prevGraph = graphDataRef.current;
    if (prevGraph && nextGraph && graphStructureKey(prevGraph) === graphStructureKey(nextGraph)) {
      return;
    }
    graphDataRef.current = nextGraph;
    setGraphData(nextGraph);
  }, []);

  const saveGraphEdit = useCallback(async (edit: GraphContentEdit): Promise<void> => {
    if (!authSession || !activeThreadId || !graphDataRef.current) {
      throw new Error('Open a saved diagram before editing it.');
    }
    const activeChatId = activeChatStreamIdRef.current;
    if (streamStatus === 'generating' || (activeChatId && activeChatTerminalRef.current !== activeChatId)) {
      throw new Error('Wait for diagram generation to finish before editing.');
    }
    if (graphEditInFlightRef.current) {
      throw new Error('Wait for the current diagram edit to finish saving.');
    }

    const originalGraph = graphDataRef.current;
    const originalKey = graphStructureKey(originalGraph);
    const editEpoch = graphEditEpochRef.current;
    const userId = authSession.user.id;
    graphEditInFlightRef.current = true;
    setIsSavingGraphEdit(true);
    try {
      const savedGraph = await saveGraphContentEdit(
        authSession,
        activeThreadId,
        originalGraph.version ?? null,
        edit,
      );
      if (
        editEpoch !== graphEditEpochRef.current
        || activeThreadIdRef.current !== activeThreadId
        || authSessionRef.current?.user.id !== userId
      ) {
        return;
      }
      if (graphStructureKey(graphDataRef.current) !== originalKey) {
        throw new Error('The diagram changed while this edit was saving. Reload it before editing again.');
      }

      const nextGraph = normalizeGraphData(savedGraph) ?? savedGraph;
      const nextKey = graphStructureKey(nextGraph);
      if (nextKey !== originalKey) {
        suggestionsCacheRef.current.clear();
      }
      lastGraphKeyRef.current = nextKey;
      graphDataRef.current = nextGraph;
      durableGraphDataRef.current = nextGraph;
      setGraphData(nextGraph);
      setAnswerTurn(null);
      setGraphNotice(null);
      const currentSelected = selectedNodeRef.current;
      if (currentSelected) {
        const liveNode = nextGraph.nodes.find(node => node.id === currentSelected.node.id);
        const nextSelection = liveNode
          ? {
              node: liveNode,
              suggestions: liveNode.label === currentSelected.node.label
                ? currentSelected.suggestions
                : initialNodeSuggestions(liveNode.label),
            }
          : null;
        selectedNodeRef.current = nextSelection;
        setSelectedNode(nextSelection);
      }
    } finally {
      if (editEpoch === graphEditEpochRef.current) {
        graphEditInFlightRef.current = false;
        setIsSavingGraphEdit(false);
      }
    }
  }, [activeThreadId, authSession, streamStatus]);

  const adoptRestoredGraph = useCallback((nextGraph: GraphData, threadId: string, expectedVersion: string | null): boolean => {
    const chatId = activeChatStreamIdRef.current;
    if (!mountedRef.current || !authSession || authSessionRef.current?.user.id !== authSession.user.id
      || activeThreadIdRef.current !== threadId || graphEditInFlightRef.current
      || (chatId && activeChatTerminalRef.current !== chatId)
      || (graphDataRef.current?.version ?? null) !== expectedVersion) return false;
    const normalized = normalizeGraphData(nextGraph);
    if (!normalized?.nodes.length) return false;
    if (activeNodeStreamIdRef.current) agentTransport.cancelNodeSelection(activeNodeStreamIdRef.current);
    activeNodeStreamIdRef.current = null;
    graphEditEpochRef.current += 1;
    graphDataRef.current = normalized;
    durableGraphDataRef.current = normalized;
    lastGraphKeyRef.current = graphStructureKey(normalized);
    suggestionsCacheRef.current.clear();
    selectedNodeRef.current = null;
    setSelectedNode(null);
    setGraphData(normalized);
    setGraphPreview(null);
    setGraphCandidate(null);
    setGraphNotice(null);
    setPublishedGraphKey(null);
    setAnswerTurn(null);
    return true;
  }, [authSession]);

  const handleEvent = useCallback((event: ServerEvent, meta: { kind: 'chat' | 'node-selected'; clientRequestId: string }) => {
    if (meta.kind === 'chat' && activeChatStreamIdRef.current !== meta.clientRequestId) {
      return;
    }
    if (meta.kind === 'node-selected' && activeNodeStreamIdRef.current !== meta.clientRequestId) {
      return;
    }

    switch (event.type) {

      case 'worker_status':
        if (meta.kind !== 'chat') break;
        setWorkerStatus(prev => ({ ...prev, [event.worker]: event.status }));
        break;

      case 'response_delta': {
        if (meta.kind !== 'chat') break;
        turnOutputRef.current.text ||= event.content.trim().length > 0;
        if (!streamingIdRef.current) {
          // First delta — create the streaming message
          const id = makeId();
          streamingIdRef.current = id;
          setMessages(prev => [...prev, {
            id, role: 'assistant', content: event.content, isStreaming: true, clientRequestId: meta.clientRequestId,
          }]);
        } else {
          // Append to the existing streaming message
          const id = streamingIdRef.current;
          setMessages(prev => prev.map(m =>
            m.id === id ? { ...m, content: m.content + event.content } : m
          ));
        }
        break;
      }

      case 'provider_switch':
        if (meta.kind !== 'chat') break;
        setProviderNotice(
          event.provider === 'openai'
            ? 'Claude unavailable — responding with GPT'
            : `Responding with ${event.provider}`
        );
        break;

      case 'response_reset':
        if (meta.kind !== 'chat') break;
        turnOutputRef.current.text = false;
        turnOutputRef.current.graph = false;
        if (streamingIdRef.current) {
          const id = streamingIdRef.current;
          setMessages(prev => prev.filter(message => message.id !== id));
          streamingIdRef.current = null;
        }
        setProviderNotice(null);
        if (activeExplanationMessageIdsRef.current.length > 0) {
          const obsolete = new Set(activeExplanationMessageIdsRef.current);
          setMessages(prev => prev.filter(message => !obsolete.has(message.id)));
          activeExplanationMessageIdsRef.current = [];
        }
        setGraphCandidate(null);
        setGraphPreview(null);
        publishGraph(durableGraphDataRef.current);
        setWorkflowProgress([]);
        break;

      case 'workflow_progress':
        if (meta.kind !== 'chat') break;
        setWorkflowProgress(prev => {
          const index = prev.findIndex(item => item.phase === event.phase);
          const next = {
            phase: event.phase,
            status: event.status,
            title: event.title,
            detail: event.detail,
          };
          if (index < 0) return [...prev, next].slice(-8);
          return [...prev.filter(item => item.phase !== next.phase), next];
        });
        break;

      case 'graph_candidate':
        if (meta.kind !== 'chat') break;
        if (!isSupportedDiagramEvaluationCriteria(event.criteria)) {
          setGraphCandidate(null);
          break;
        }
        setGraphCandidate({
          evaluationId: event.evaluation_id,
          graphVersion: event.graph_version,
          criteria: event.criteria,
          // Private render review must inspect the exact server candidate.
          // Legacy normalization remains on hydrated and published graphs.
          data: event.data,
        });
        break;

      case 'explanation_block': {
        if (meta.kind !== 'chat') break;
        turnOutputRef.current.text ||= event.content.trim().length > 0;
        const id = makeId();
        const block = {
          id,
          title: event.title,
          content: event.content,
          relatedNodeIds: event.related_node_ids,
          clientRequestId: meta.clientRequestId,
        };
        activeExplanationMessageIdsRef.current.push(id);
        setMessages(prev => [...prev, {
          ...block,
          role: 'assistant',
          kind: 'explanation',
          isStreaming: false,
        }]);
        break;
      }

      case 'command_rejected':
        if (meta.kind !== 'chat') break;
        setMessages(prev => [...prev, {
          id: makeId(),
          role: 'assistant',
          content: `Your follow-up could not be applied: ${event.reason}`,
          isStreaming: false,
        }]);
        break;

      case 'steer_applied':
      case 'retrieval_evidence':
      case 'research_evidence':
        break;

      case 'stopped':
        if (meta.kind !== 'chat') break;
        setGraphPreview(null);
        publishGraph(durableGraphDataRef.current);
        break;

      case 'done':
        if (meta.kind === 'chat') {
          const analytics = activeChatAnalyticsRef.current;
          const terminalAlreadyRecorded = activeChatTerminalRef.current === meta.clientRequestId;
          const emptyResponse = !turnOutputRef.current.text && !turnOutputRef.current.graph;
          if (emptyResponse && !terminalAlreadyRecorded) {
            setMessages(prev => [...prev, {
              id: makeId(), role: 'assistant', content: EMPTY_RESPONSE_MESSAGE, isStreaming: false,
            }]);
          }
          if (streamingIdRef.current) {
            const id = streamingIdRef.current;
            setMessages(prev => prev.map(m =>
              m.id === id ? { ...m, isStreaming: false } : m
            ));
            streamingIdRef.current = null;
          }
          setWorkerStatus(IDLE_WORKER_STATUS);
          setRetrievalNotice(null);
          setProviderNotice(null);
          setStreamStatus('connected');
          setGraphCandidate(null);
          setGraphPreview(null);
          if (analytics && !terminalAlreadyRecorded) {
            activeChatTerminalRef.current = analytics.clientRequestId;
            void trackEvent(
              emptyResponse ? 'chat_stream_failed' : 'chat_stream_completed',
              {
                thread_id: analytics.threadId,
                client_request_id: analytics.clientRequestId,
                complexity: analytics.complexity,
                graph_mode: analytics.graphMode,
                research_enabled: analytics.researchEnabled,
                backend_readiness_state: analytics.backendReadinessState,
                has_selected_text_context: analytics.hasSelectedTextContext,
                ...(emptyResponse ? { error_code: 'empty_response' } : {}),
              },
              authSessionRef.current,
            );
          }
          const session = authSessionRef.current;
          const threadId = activeThreadIdRef.current;
          if (session && threadId) {
            void fetchThread(session, threadId).then(detail => {
              if (!mountedRef.current || activeThreadIdRef.current !== threadId
                || authSessionRef.current?.user.id !== session.user.id
                || activeChatTerminalRef.current !== meta.clientRequestId) return;
              const persisted = detail.messages.find(message => message.role === 'assistant'
                && message.client_request_id === meta.clientRequestId);
              if (!persisted) return;
              setMessages(previous => previous.map(message => message.role === 'assistant'
                && message.clientRequestId === meta.clientRequestId
                ? { ...message, graphRevisionId: persisted.graph_revision_id ?? null }
                : message));
            }).catch(() => {
              if (mountedRef.current && activeThreadIdRef.current === threadId
                && authSessionRef.current?.user.id === session.user.id
                && activeChatTerminalRef.current === meta.clientRequestId) {
                setGraphNotice({ message: 'Could not refresh diagram history links. Reopen this chat to retry.' });
              }
            });
          }
        }
        break;

      case 'graph_data':
        if (meta.kind !== 'chat') break;
        {
          const nextGraph = normalizeGraphData(event.data);
          // An empty result must not erase the last accepted diagram.
          if (!nextGraph?.nodes.length) break;
          turnOutputRef.current.graph = graphStructureKey(nextGraph) !== turnOutputRef.current.initialGraphKey;
          durableGraphDataRef.current = nextGraph;
          setGraphCandidate(null);
          setGraphPreview(null);
          publishGraph(nextGraph);
        }
        break;

      case 'graph_preview':
        if (meta.kind !== 'chat') break;
        {
          const nextGraph = normalizeGraphData(event.data);
          setGraphCandidate(null);
          setGraphPreview(nextGraph);
        }
        break;

      case 'node_detail':
        if (meta.kind !== 'chat') break;
        setGraphData(prev => {
          if (!prev) return prev;
          if (event.graph_version && prev.version && event.graph_version !== prev.version) {
            return prev;
          }
          return {
            ...prev,
            nodes: prev.nodes.map(n =>
              n.id === event.node_id
                ? { ...n, detail: event.description, book_refs: event.book_refs }
                : n
            ),
          };
        });
        break;

      case 'suggested_questions':
        if (meta.kind !== 'node-selected') break;
        if (event.questions.length === 0) break;
        setSelectedNode(prev => {
          if (prev) {
            // Cache so the next click on this node skips the LLM call
            suggestionsCacheRef.current.set(prev.node.id, event.questions);
            const nextSelection = { ...prev, suggestions: event.questions };
            selectedNodeRef.current = nextSelection;
            return nextSelection;
          }
          return prev;
        });
        break;

      case 'retrieval_notice':
        if (meta.kind !== 'chat') break;
        setRetrievalNotice({
          requestId: event.request_id,
          message: event.message,
          requested: false,
        });
        break;

      case 'graph_notice':
        if (meta.kind !== 'chat') break;
        setGraphNotice({ message: event.message });
        break;

      case 'error':
        if (meta.kind === 'chat') {
          const analytics = activeChatAnalyticsRef.current;
          if (streamingIdRef.current) {
            const id = streamingIdRef.current;
            setMessages(prev => prev.map(m =>
              m.id === id ? { ...m, isStreaming: false } : m
            ));
            streamingIdRef.current = null;
          }
          setMessages(prev => [...prev, {
            id: makeId(), role: 'assistant',
            content: `Error: ${event.content}`, isStreaming: false,
          }]);
          setWorkerStatus(IDLE_WORKER_STATUS);
          setRetrievalNotice(null);
          setProviderNotice(null);
          setStreamStatus('connected');
          setGraphCandidate(null);
          setGraphPreview(null);
          publishGraph(durableGraphDataRef.current);
          if (analytics) {
            activeChatTerminalRef.current = analytics.clientRequestId;
            void trackEvent(
              'chat_stream_failed',
              {
                thread_id: analytics.threadId,
                client_request_id: analytics.clientRequestId,
                complexity: analytics.complexity,
                graph_mode: analytics.graphMode,
                research_enabled: analytics.researchEnabled,
                backend_readiness_state: analytics.backendReadinessState,
                has_selected_text_context: analytics.hasSelectedTextContext,
                error_code: event.content.slice(0, 80),
              },
              authSessionRef.current,
            );
          }
        }
        break;
    }
  }, [publishGraph]);

  useEffect(() => {
    const offEvent = agentTransport.onEvent(handleEvent);
    return () => { offEvent(); };
  }, [handleEvent]);

  const sendMessage = useCallback((
    content: string,
    opts?: SendOptions,
  ): boolean => {
    const targetThreadId = activeThreadIdRef.current;
    const session = authSessionRef.current;
    if (!mountedRef.current) return false;
    if (graphEditInFlightRef.current) return false;
    if (!session || !targetThreadId) {
      setMessages(prev => [...prev, {
        id: makeId(), role: 'assistant', content: 'Error: You must be signed in with an active thread.', isStreaming: false,
      }]);
      return false;
    }
    if (activeChatStreamIdRef.current && activeChatTerminalRef.current !== activeChatStreamIdRef.current) {
      const displayContent = opts?.displayContent ?? content;
      if (agentTransport.steerGeneration(content)) {
        setMessages(prev => [...prev, {
          id: makeId(),
          role: 'user',
          content: displayContent,
          isStreaming: false,
        }]);
        setWorkerStatus(prev => ({
          ...prev,
          orchestrator: 'Applying your follow-up…',
        }));
        return true;
      }
    }
    const userId = makeId();
    turnOutputRef.current = {
      text: false, graph: false, initialGraphKey: graphStructureKey(durableGraphDataRef.current),
    };
    setPaintGraceExpiredTurnId(null);
    setAnswerTurn({ userId, diagram: opts?.graphMode !== 'off' });
    setMessages(prev => [...prev, {
      id: userId,
      role: 'user',
      content: opts?.displayContent ?? content,
      isStreaming: false,
    }]);
    setRetrievalNotice(null);
    setGraphNotice(null);
    setGraphCandidate(null);
    setWorkflowProgress([]);
    activeExplanationMessageIdsRef.current = [];
    setStreamStatus('generating');
    setWorkerStatus(OPTIMISTIC_CHAT_STATUS);
    const clientRequestId = makeId();
    activeChatStreamIdRef.current = clientRequestId;
    activeChatTerminalRef.current = null;
    const analytics = {
      threadId: targetThreadId,
      clientRequestId,
      complexity: opts?.complexity ?? 'auto',
      graphMode: opts?.graphMode ?? 'on',
      researchEnabled: opts?.researchEnabled ?? false,
      backendReadinessState: opts?.backendReadinessState,
      hasSelectedTextContext: opts?.hasSelectedTextContext,
    };
    activeChatAnalyticsRef.current = analytics;
    void trackEvent(
      'chat_sent',
      {
        thread_id: analytics.threadId,
        client_request_id: analytics.clientRequestId,
        complexity: analytics.complexity,
        graph_mode: analytics.graphMode,
        research_enabled: analytics.researchEnabled,
        backend_readiness_state: analytics.backendReadinessState,
        has_selected_text_context: analytics.hasSelectedTextContext,
      },
      session,
    );
    void trackEvent(
      'chat_stream_started',
      {
        thread_id: analytics.threadId,
        client_request_id: analytics.clientRequestId,
        complexity: analytics.complexity,
        graph_mode: analytics.graphMode,
        research_enabled: analytics.researchEnabled,
        backend_readiness_state: analytics.backendReadinessState,
        has_selected_text_context: analytics.hasSelectedTextContext,
      },
      session,
    );

    agentTransport.sendMessage(session, targetThreadId, content, opts, clientRequestId).then(sawDone => {
      if (!sawDone && activeChatStreamIdRef.current === clientRequestId) {
        if (streamingIdRef.current) {
          const id = streamingIdRef.current;
          setMessages(prev => prev.map(m =>
            m.id === id ? { ...m, isStreaming: false } : m
          ));
          streamingIdRef.current = null;
        }
        setMessages(prev => [...prev, {
          id: makeId(),
          role: 'assistant',
          content: 'Connection closed before the response finished. Please try again.',
          isStreaming: false,
        }]);
        setWorkerStatus(IDLE_WORKER_STATUS);
        setRetrievalNotice(null);
        setProviderNotice(null);
        setGraphCandidate(null);
        setGraphPreview(null);
        publishGraph(durableGraphDataRef.current);
        setStreamStatus('connected');
        if (activeChatTerminalRef.current !== clientRequestId) {
          activeChatTerminalRef.current = clientRequestId;
          void trackEvent(
            'chat_stream_failed',
            {
              thread_id: analytics.threadId,
              client_request_id: analytics.clientRequestId,
              complexity: analytics.complexity,
              graph_mode: analytics.graphMode,
              research_enabled: analytics.researchEnabled,
              backend_readiness_state: analytics.backendReadinessState,
              has_selected_text_context: analytics.hasSelectedTextContext,
              error_code: 'stream_closed',
            },
            session,
          );
        }
      }
    }).catch(err => {
      if (activeChatStreamIdRef.current !== clientRequestId) {
        return;
      }
      // Network-level failure (not an SSE error event)
      if (streamingIdRef.current) {
        const id = streamingIdRef.current;
        setMessages(prev => prev.map(m =>
          m.id === id ? { ...m, isStreaming: false } : m
        ));
        streamingIdRef.current = null;
      }
      setMessages(prev => [...prev, {
        id: makeId(), role: 'assistant',
        content: err instanceof ChatTurnTimeoutError
          ? 'The connection timed out. Reopen this chat before retrying; your diagram may already be saved.'
          : 'Connection lost. Please try again.',
        isStreaming: false,
      }]);
      setWorkerStatus(IDLE_WORKER_STATUS);
      setRetrievalNotice(null);
      setProviderNotice(null);
      setGraphCandidate(null);
      setGraphPreview(null);
      publishGraph(durableGraphDataRef.current);
      setStreamStatus('connected');
      if (activeChatTerminalRef.current !== clientRequestId) {
        activeChatTerminalRef.current = clientRequestId;
        void trackEvent(
          'chat_stream_failed',
          {
            thread_id: analytics.threadId,
            client_request_id: analytics.clientRequestId,
            complexity: analytics.complexity,
            graph_mode: analytics.graphMode,
            research_enabled: analytics.researchEnabled,
            backend_readiness_state: analytics.backendReadinessState,
            has_selected_text_context: analytics.hasSelectedTextContext,
            error_code: err.message,
          },
          session,
        );
      }
    }).finally(() => {
      if (activeChatStreamIdRef.current === clientRequestId) {
        activeChatStreamIdRef.current = null;
      }
      if (activeChatAnalyticsRef.current?.clientRequestId === clientRequestId) {
        activeChatAnalyticsRef.current = null;
      }
    });
    return true;
  }, [publishGraph]);

  const startThreadAndSend = useCallback((thread: ThreadDetail, content: string, opts?: SendOptions): boolean => {
    if (!mountedRef.current || !authSession || authSessionRef.current?.user.id !== authSession.user.id
      || (activeThreadIdRef.current !== null && activeThreadIdRef.current !== activeThreadId
        && activeThreadIdRef.current !== thread.thread.id)) return false;
    resetThreadView();
    activeThreadIdRef.current = thread.thread.id;
    const graph = normalizeGraphData(thread.thread.graph_data);
    graphDataRef.current = graph;
    durableGraphDataRef.current = graph;
    lastGraphKeyRef.current = graphStructureKey(graph);
    setGraphData(graph);
    setMessages(mapThreadMessages(thread.messages));
    return sendMessage(content, opts);
  }, [activeThreadId, authSession, resetThreadView, sendMessage]);

  const requestSearchTool = useCallback(async () => {
    if (!authSession || !activeThreadId || !retrievalNotice || retrievalNotice.requested) {
      return;
    }

    setRetrievalNotice({ ...retrievalNotice, requested: true });
    void trackEvent(
      'search_tool_requested',
      {
        thread_id: activeThreadId,
        request_id: retrievalNotice.requestId,
      },
      authSession,
    );
    try {
      const result = await agentTransport.useSearchTool(authSession, activeThreadId, retrievalNotice.requestId);
      if (!result.ok) {
        setMessages(prev => [...prev, {
          id: makeId(),
          role: 'assistant',
          content: 'Search tool is no longer available for this response. Please ask again if you still want web context.',
          isStreaming: false,
        }]);
        setRetrievalNotice(null);
      }
    } catch {
      setMessages(prev => [...prev, {
        id: makeId(),
        role: 'assistant',
        content: 'Connection lost. Please try again.',
        isStreaming: false,
      }]);
      setRetrievalNotice(null);
    }
  }, [activeThreadId, authSession, retrievalNotice]);

  const selectNode = useCallback((node: GraphNode) => {
    const cached = suggestionsCacheRef.current.get(node.id);
    const nextSelection = {
      node,
      suggestions: cached ?? initialNodeSuggestions(node.label),
    };
    // Keep the synchronous ref and rendered state in lockstep so a nearby
    // graph event cannot clear a just-selected node before React commits.
    selectedNodeRef.current = nextSelection;
    setSelectedNode(nextSelection);
    if (!authSession || !activeThreadId) return;
    // Check cache — if we already have questions for this node, apply immediately
    // without hitting the backend (saves LLM cost + latency on repeat clicks)
    if (cached) {
      return;
    }
    const clientRequestId = makeId();
    activeNodeStreamIdRef.current = clientRequestId;
    agentTransport.sendNodeSelected(
      authSession,
      activeThreadId,
      node.id,
      node.label,
      node.detail ?? node.description ?? '',
      clientRequestId,
    ).catch(err => {
      if (activeNodeStreamIdRef.current === clientRequestId && !(err instanceof DOMException && err.name === 'AbortError')) {
        console.error('[sse] node-selected error:', err);
      }
    }).finally(() => {
      if (activeNodeStreamIdRef.current === clientRequestId) {
        activeNodeStreamIdRef.current = null;
      }
    });
  }, [activeThreadId, authSession]);

  const clearSelectedNode = useCallback(() => {
    const nodeRequestId = activeNodeStreamIdRef.current;
    activeNodeStreamIdRef.current = null;
    if (nodeRequestId) agentTransport.cancelNodeSelection(nodeRequestId);
    selectedNodeRef.current = null;
    setSelectedNode(null);
  }, []);

  const stopGeneration = useCallback(() => {
    const analytics = activeChatAnalyticsRef.current;
    const clientRequestId = activeChatStreamIdRef.current;
    activeChatStreamIdRef.current = null;
    if (clientRequestId) agentTransport.stopGeneration(clientRequestId);
    publishGraph(durableGraphDataRef.current);
    // Finalise any streaming message so it renders as complete
    if (streamingIdRef.current) {
      const id = streamingIdRef.current;
      setMessages(prev => prev.map(m =>
        m.id === id ? { ...m, isStreaming: false } : m
      ));
      streamingIdRef.current = null;
    }
    setWorkerStatus(IDLE_WORKER_STATUS);
    setProviderNotice(null);
    setGraphCandidate(null);
    setGraphPreview(null);
    setStreamStatus('connected');
    if (analytics) {
      activeChatTerminalRef.current = analytics.clientRequestId;
      void trackEvent(
        'chat_stopped',
        {
          thread_id: analytics.threadId,
          client_request_id: analytics.clientRequestId,
          complexity: analytics.complexity,
          graph_mode: analytics.graphMode,
          research_enabled: analytics.researchEnabled,
          backend_readiness_state: analytics.backendReadinessState,
          has_selected_text_context: analytics.hasSelectedTextContext,
        },
        authSession,
      );
    }
  }, [authSession, publishGraph]);

  // Keep storage complete while the learner waits for the committed diagram to paint.
  // D3 acknowledges its layout after fonts and two animation frames have settled.
  const waitingForGraphPaint = !!answerTurn?.diagram && !!graphData
    && renderedGraphKey !== graphStructureKey(graphData)
    && paintGraceExpiredTurnId !== answerTurn.userId;
  useEffect(() => {
    if (streamStatus === 'generating' || !waitingForGraphPaint || !answerTurn) return;
    // A missed canvas acknowledgement must not hide the terminal response forever.
    const timer = window.setTimeout(() => setPaintGraceExpiredTurnId(answerTurn.userId), GRAPH_PAINT_GRACE_MS);
    return () => window.clearTimeout(timer);
  }, [answerTurn, streamStatus, waitingForGraphPaint]);
  const answerPending = !!answerTurn?.diagram && (
    streamStatus === 'generating'
    || waitingForGraphPaint
  );
  const turnIndex = answerTurn ? messages.findIndex(message => message.id === answerTurn.userId) : -1;
  const visibleMessages = answerPending && turnIndex >= 0
    ? messages.filter((message, index) => index <= turnIndex || message.role !== 'assistant')
    : messages;

  return {
    messages,
    visibleMessages,
    answerPending,
    diagramRequested: answerTurn?.diagram ?? false,
    acknowledgeGraphRendered,
    graphData,
    isSavingGraphEdit,
    publishedGraphKey,
    graphPreview,
    graphCandidate,
    workflowProgress,
    workerStatus,
    retrievalNotice,
    graphNotice,
    selectedNode,
    selectNode,
    clearSelectedNode,
    streamStatus,
    providerNotice,
    hydrateThread,
    adoptRestoredGraph,
    startThreadAndSend,
    sendMessage,
    saveGraphEdit,
    requestSearchTool,
    stopGeneration,
  };
}
