import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { AuthSession, GraphData, ServerEvent, ThreadDetail } from '../types';

const mocks = vi.hoisted(() => ({
  eventHandler: null as null | ((event: ServerEvent, meta: { kind: 'chat' | 'node-selected'; clientRequestId: string }) => void),
  sendMessage: vi.fn(),
  sendNodeSelected: vi.fn(),
  isChatActive: vi.fn(),
  steerGeneration: vi.fn(),
  stopGeneration: vi.fn(),
  acceptPreview: vi.fn(),
  cancelNodeSelection: vi.fn(),
  useSearchTool: vi.fn(),
  trackEvent: vi.fn(),
  saveGraphContentEdit: vi.fn(),
  fetchThread: vi.fn(),
}));

vi.mock('../services/api', () => ({
  saveGraphContentEdit: mocks.saveGraphContentEdit,
  fetchThread: mocks.fetchThread,
}));

vi.mock('../services/agentTransport', async importOriginal => ({
  ...await importOriginal<typeof import('../services/agentTransport')>(),
  createClientRequestId: () => crypto.randomUUID(),
  agentTransport: {
    onEvent: vi.fn((handler: NonNullable<typeof mocks.eventHandler>) => {
      mocks.eventHandler = handler;
      return vi.fn();
    }),
    sendMessage: mocks.sendMessage,
    sendNodeSelected: mocks.sendNodeSelected,
    isChatActive: mocks.isChatActive,
    steerGeneration: mocks.steerGeneration,
    stopGeneration: mocks.stopGeneration,
    acceptPreview: mocks.acceptPreview,
    cancelNodeSelection: mocks.cancelNodeSelection,
    useSearchTool: mocks.useSearchTool,
  },
}));

vi.mock('../services/analytics', () => ({
  trackEvent: mocks.trackEvent,
}));

import { useAgentStream } from './useAgentStream';
import { ChatTurnTimeoutError } from '../services/agentTransport';
import { graphStructureKey } from '../utils/graphStructureKey';

const session: AuthSession = {
  access_token: 'token',
  refresh_token: 'refresh',
  user: { id: 'user-1', email: 'user@example.com' },
};

const diagramCriteria = {
  viewport_width: 1440,
  viewport_height: 960,
  minimum_text_px: 11,
} as const;

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function graph(version = '1'): GraphData {
  return {
    graph_type: 'concept',
    title: 'Agent Map',
    version,
    nodes: [
      {
        id: 'agent',
        label: 'Agent',
        type: 'service',
        technology: 'LLM',
        description: 'Plans tool use.',
        detail: null,
      },
    ],
    edges: [],
    sequence: [],
  };
}

function Harness({
  auth = session,
  threadId = 'thread-1',
}: {
  auth?: AuthSession | null;
  threadId?: string | null;
}) {
  const agent = useAgentStream(auth, threadId);
  return (
    <div>
      <div data-testid="status">{agent.streamStatus}</div>
      <div data-testid="messages">{agent.messages.map((message) => `${message.role}:${message.content}:${message.isStreaming ? 'streaming' : 'done'}`).join('|')}</div>
      <div data-testid="worker">{JSON.stringify(agent.workerStatus)}</div>
      <div data-testid="provider">{agent.providerNotice ?? ''}</div>
      <div data-testid="retrieval">{agent.retrievalNotice?.message ?? ''}</div>
      <div data-testid="retrieval-requested">{agent.retrievalNotice?.requested ? 'yes' : 'no'}</div>
      <div data-testid="graph-notice">{agent.graphNotice?.message ?? ''}</div>
      <div data-testid="graph-title">{agent.graphData?.title ?? ''}</div>
      <div data-testid="preview-title">{agent.graphPreview?.title ?? ''}</div>
      <div data-testid="candidate-title">{agent.graphCandidate?.data.title ?? ''}</div>
      <div data-testid="candidate-node-type">{agent.graphCandidate?.data.nodes[0]?.type ?? ''}</div>
      <div data-testid="candidate-criteria">{JSON.stringify(agent.graphCandidate?.criteria ?? null)}</div>
      <div data-testid="progress">{JSON.stringify(agent.workflowProgress)}</div>
      <div data-testid="node-detail">{agent.graphData?.nodes[0]?.detail ?? ''}</div>
      <div data-testid="selected">{agent.selectedNode ? `${agent.selectedNode.node.id}:${agent.selectedNode.suggestions.join(',')}` : ''}</div>
      <button onClick={() => agent.sendMessage('hello', { complexity: 'production', graphMode: 'on', researchEnabled: true })}>send</button>
      <button onClick={() => agent.requestSearchTool()}>search</button>
      <button onClick={() => agent.selectNode(graph().nodes[0])}>node</button>
      <button onClick={() => {
        if (agent.graphPreview?.nodes[0]) {
          agent.selectNode(agent.graphPreview.nodes[0]);
        }
      }}>preview node</button>
      <button onClick={() => agent.stopGeneration()}>stop</button>
      <button onClick={() => agent.hydrateThread({ messages: [{ id: 'm1', role: 'user', content: 'old' }], graphData: graph('2') })}>hydrate</button>
    </div>
  );
}

describe('useAgentStream', () => {
  it('marks only the last failed response block and retries the original request with current graph version', async () => {
    const firstTurn = deferred<boolean>();
    mocks.sendMessage.mockReturnValueOnce(firstTurn.promise).mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useAgentStream(session, 'retry-thread'));
    act(() => result.current.hydrateThread({ messages: [], graphData: graph('old') }));
    act(() => result.current.sendMessage('Expanded original request', {
      complexity: 'production', graphMode: 'on', diagramRequested: true, researchEnabled: true,
      graphAction: 'extend', expectedGraphVersion: 'old', displayContent: 'Expand this',
    }));
    const firstId = mocks.sendMessage.mock.calls[0][4] as string;
    mocks.steerGeneration.mockReturnValueOnce(true);
    act(() => result.current.sendMessage('Keep the existing diagram and add approvals'));
    expect(mocks.steerGeneration).toHaveBeenCalledWith('Keep the existing diagram and add approvals');
    const emit = (event: ServerEvent) => act(() => mocks.eventHandler?.(event, { kind: 'chat', clientRequestId: firstId }));
    emit({ type: 'response_delta', content: 'Earlier explanation' });
    emit({ type: 'explanation_block', block_id: 'final', title: 'Diagram unchanged', content: 'Failed to update', related_node_ids: [], evidence_refs: [] });
    emit({ type: 'generation_failed' });
    emit({ type: 'done' });
    await act(async () => { firstTurn.resolve(true); });
    expect(result.current.messages.filter(message => message.retryRequest)).toHaveLength(1);
    const failed = result.current.messages.find(message => message.retryRequest)!;
    expect(failed.content).toBe('Failed to update');
    expect(result.current.messages.find(message => message.content === 'Earlier explanation')?.retryRequest).toBeUndefined();
    mocks.fetchThread.mockResolvedValueOnce({ thread: { graph_data: graph('old') }, messages: [{
      id: 'saved-failure', role: 'assistant', content: 'Failed to update', created_at: '',
      client_request_id: firstId, retry_request: {
        content: 'Expanded original request', complexity: 'production', graph_mode: 'on',
        diagram_requested: true, research_enabled: true, graph_action: 'extend', expected_graph_version: 'old',
      },
    }] });
    await act(async () => { await result.current.retryMessage(failed, 'current'); });
    expect(mocks.sendMessage).toHaveBeenCalledTimes(2);
    expect(mocks.sendMessage).toHaveBeenNthCalledWith(2, session, 'retry-thread', 'Expanded original request', expect.objectContaining({
      complexity: 'production', graphMode: 'on', diagramRequested: true, researchEnabled: true,
      graphAction: 'extend', expectedGraphVersion: 'current', retrySourceRequestId: firstId,
    }), expect.any(String));
    expect(mocks.sendMessage.mock.calls[1][4]).not.toBe(firstId);
  });

  it('keeps successful and stopped turns without retry metadata', () => {
    mocks.sendMessage.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useAgentStream(session, 'retry-exclusions'));
    act(() => result.current.sendMessage('First'));
    const firstId = mocks.sendMessage.mock.calls[0][4] as string;
    act(() => mocks.eventHandler?.({ type: 'response_delta', content: 'Done' }, { kind: 'chat', clientRequestId: firstId }));
    act(() => mocks.eventHandler?.({ type: 'done' }, { kind: 'chat', clientRequestId: firstId }));
    expect(result.current.messages.some(message => message.retryRequest)).toBe(false);
    act(() => result.current.sendMessage('Second'));
    const secondId = mocks.sendMessage.mock.calls[1][4] as string;
    act(() => mocks.eventHandler?.({ type: 'stopped' }, { kind: 'chat', clientRequestId: secondId }));
    expect(result.current.messages.some(message => message.retryRequest)).toBe(false);
  });

  it('reconciles uncertain transport failure before replaying the same request id', async () => {
    mocks.sendMessage.mockRejectedValueOnce(new Error('Lost connection')).mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useAgentStream(session, 'retry-uncertain'));
    act(() => result.current.sendMessage('Original request', { graphMode: 'on', researchEnabled: true,
      graphAction: 'extend', expectedGraphVersion: 'original-version' }));
    await waitFor(() => expect(result.current.messages.some(message => message.retryClientRequestId)).toBe(true));
    const failed = result.current.messages.find(message => message.retryClientRequestId)!;
    mocks.fetchThread.mockResolvedValueOnce({ thread: { id: 'retry-uncertain', title: 'Retry', graph_data: null,
      created_at: '', updated_at: '', last_seen_at: '' }, messages: [] });
    await act(async () => { await result.current.retryMessage(failed, 'newer-version'); });
    expect(mocks.fetchThread).toHaveBeenCalledWith(session, 'retry-uncertain');
    expect(mocks.sendMessage.mock.calls[1][4]).toBe(failed.retryClientRequestId);
    expect(mocks.sendMessage.mock.calls[1][2]).toBe('Original request');
    expect(mocks.sendMessage.mock.calls[1][3].expectedGraphVersion).toBe('original-version');
    expect(mocks.sendMessage.mock.calls[1][3].retrySourceRequestId).toBeUndefined();
    expect(result.current.messages.filter(message => message.role === 'user')).toHaveLength(1);
  });

  it('replays acknowledged steering in order across repeated disconnects', async () => {
    const first = deferred<boolean>();
    const second = deferred<boolean>();
    mocks.sendMessage.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
      .mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useAgentStream(session, 'steering-replay'));
    act(() => result.current.sendMessage('Original request'));
    const requestId = mocks.sendMessage.mock.calls[0][4] as string;
    const emit = (event: ServerEvent) => act(() => mocks.eventHandler?.(event, { kind: 'chat', clientRequestId: requestId }));
    emit({ type: 'steer_applied', steer_count: 2, content: 'out of order' });
    emit({ type: 'steer_applied', steer_count: 1, content: 'Canonical first' });
    emit({ type: 'steer_applied', steer_count: 1, content: 'duplicate' });
    emit({ type: 'command_rejected', reason: 'Rejected correction' });
    emit({ type: 'steer_applied', steer_count: 2, content: 'Canonical second' });
    await act(async () => first.reject(new Error('Socket dropped')));
    const failure = result.current.messages.find(message => message.retryRequest)!;
    expect(failure.retryRequest?.steeringUpdates).toEqual(['Canonical first', 'Canonical second']);
    await act(async () => { await result.current.retryMessage(failure, null); });
    expect(mocks.sendMessage.mock.calls[1][4]).toBe(requestId);
    expect(mocks.sendMessage.mock.calls[1][2]).toBe('Original request');
    expect(mocks.sendMessage.mock.calls[1][3].steeringUpdates).toEqual(['Canonical first', 'Canonical second']);
    expect(result.current.messages.find(message => message.role === 'user')?.content)
      .toBe('Original request\n\nUser steering update 1:\nCanonical first\n\nUser steering update 2:\nCanonical second');
    expect(result.current.messages.some(message => message.retryRequest)).toBe(false);
    await act(async () => second.reject(new Error('Dropped again')));
    const secondFailure = result.current.messages.find(message => message.retryRequest)!;
    await act(async () => { await result.current.retryMessage(secondFailure, null); });
    expect(mocks.sendMessage.mock.calls[2][3].steeringUpdates).toEqual(['Canonical first', 'Canonical second']);
    expect(mocks.sendMessage.mock.calls[2][4]).toBe(requestId);
  });

  it('loads a successful saved response after disconnect without another generation call', async () => {
    mocks.sendMessage.mockRejectedValueOnce(new Error('Socket dropped'));
    const { result } = renderHook(() => useAgentStream(session, 'saved-response'));
    act(() => result.current.sendMessage('Original request'));
    await waitFor(() => expect(result.current.messages.some(message => message.retryRequest)).toBe(true));
    const failure = result.current.messages.find(message => message.retryRequest)!;
    mocks.fetchThread.mockResolvedValueOnce({ thread: { graph_data: graph('saved') }, messages: [{
      id: 'saved-answer', role: 'assistant', content: 'Saved answer', created_at: '',
      client_request_id: failure.retryClientRequestId,
    }] });
    await act(async () => { await result.current.retryMessage(failure, null); });
    expect(mocks.sendMessage).toHaveBeenCalledTimes(1);
    expect(result.current.messages.map(message => message.content)).toEqual(['Saved answer']);
    expect(result.current.graphData?.version).toBe('saved');
  });

  it('reconciles a generation failure whose persistence fails with one retry owner', async () => {
    const first = deferred<boolean>();
    mocks.sendMessage.mockReturnValueOnce(first.promise).mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useAgentStream(session, 'persistence-failed'));
    act(() => result.current.sendMessage('Original request'));
    const requestId = mocks.sendMessage.mock.calls[0][4] as string;
    const emit = (event: ServerEvent) => act(() => mocks.eventHandler?.(event, { kind: 'chat', clientRequestId: requestId }));
    emit({ type: 'response_delta', content: 'Failure explanation' });
    emit({ type: 'generation_failed' });
    const originalFailure = result.current.messages.find(message => message.retryRequest)!;
    expect(originalFailure.retryClientRequestId).toBe(requestId);
    emit({ type: 'error', content: 'Could not save response' });
    expect(result.current.messages.filter(message => message.retryRequest)).toHaveLength(1);
    await act(async () => first.resolve(true));
    await act(async () => { await result.current.retryMessage(originalFailure, null); });
    expect(mocks.fetchThread).toHaveBeenCalledWith(session, 'persistence-failed');
    expect(mocks.sendMessage.mock.calls[1][4]).toBe(requestId);
    expect(mocks.sendMessage.mock.calls[1][3].retrySourceRequestId).toBeUndefined();
    expect(result.current.messages.some(message => message.retryRequest)).toBe(false);
  });

  it('preserves a source-derived retry reference when replaying an uncertain turn', async () => {
    mocks.sendMessage.mockRejectedValueOnce(new Error('Lost connection')).mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useAgentStream(session, 'source-replay'));
    act(() => result.current.sendMessage('Original request', {
      graphMode: 'on', graphAction: 'extend', expectedGraphVersion: 'old',
      retrySourceRequestId: 'saved-failure',
    }));
    await waitFor(() => expect(result.current.messages.some(message => message.retryClientRequestId)).toBe(true));
    const failed = result.current.messages.find(message => message.retryClientRequestId)!;
    mocks.fetchThread.mockResolvedValueOnce({ thread: { id: 'source-replay', title: 'Retry', graph_data: null,
      created_at: '', updated_at: '', last_seen_at: '' }, messages: [] });
    await act(async () => { await result.current.retryMessage(failed, 'new'); });
    expect(mocks.sendMessage.mock.calls[1][4]).toBe(failed.retryClientRequestId);
    expect(mocks.sendMessage.mock.calls[1][3]).toMatchObject({
      retrySourceRequestId: 'saved-failure', expectedGraphVersion: 'old',
    });
  });

  it('turns an uncertain committed failure into a new source-referenced retry', async () => {
    mocks.sendMessage.mockRejectedValueOnce(new Error('Lost connection')).mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useAgentStream(session, 'committed-failure'));
    act(() => result.current.sendMessage('Original request', { graphMode: 'on', graphAction: 'extend',
      expectedGraphVersion: 'old' }));
    await waitFor(() => expect(result.current.messages.some(message => message.retryClientRequestId)).toBe(true));
    const failed = result.current.messages.find(message => message.retryClientRequestId)!;
    const committedRetry = {
      content: 'Original request\n\nUser steering update 1:\nSaved correction', complexity: 'auto' as const, graph_mode: 'on' as const,
      diagram_requested: false, research_enabled: false, graph_action: 'extend' as const,
      expected_graph_version: 'old',
    };
    mocks.fetchThread.mockResolvedValueOnce({ thread: { id: 'committed-failure', title: 'Retry', graph_data: null,
      created_at: '', updated_at: '', last_seen_at: '' }, messages: [
        { id: 'user', role: 'user', content: 'Original request', created_at: '' },
        { id: 'assistant', role: 'assistant', content: 'Generation failed', created_at: '',
          client_request_id: failed.retryClientRequestId, retry_request: committedRetry },
      ] });
    await act(async () => { await result.current.retryMessage(failed, 'current'); });
    expect(mocks.sendMessage.mock.calls[1][2]).toBe(committedRetry.content);
    expect(mocks.sendMessage.mock.calls[1][3].steeringUpdates).toBeUndefined();
    expect(mocks.sendMessage.mock.calls[1][4]).not.toBe(failed.retryClientRequestId);
    expect(mocks.sendMessage.mock.calls[1][3]).toMatchObject({
      retrySourceRequestId: failed.retryClientRequestId, expectedGraphVersion: 'current',
    });
  });
  it('publishes an accepted overview when only graph detail level changes', () => {
    mocks.sendMessage.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useAgentStream(session, 'overview-promotion'));
    act(() => result.current.sendMessage('Draw a system'));
    const clientRequestId = mocks.sendMessage.mock.calls.at(-1)![4] as string;
    const emit = (event: ServerEvent) => act(() => mocks.eventHandler?.(event, { kind: 'chat', clientRequestId }));

    emit({ type: 'graph_data', data: graph() });
    expect(result.current.graphData?.detail_level).toBeUndefined();
    emit({ type: 'graph_data', data: { ...graph(), detail_level: 'overview' } });
    expect(result.current.graphData?.detail_level).toBe('overview');
    expect(result.current.publishedGraphKey).toBe(graphStructureKey(result.current.graphData));
  });

  it.each(['none', 'whitespace', 'reset', 'preview', 'existing', 'empty-graph'] as const)(
    'rejects an empty completed turn with %s output', scenario => {
      mocks.sendMessage.mockReturnValue(new Promise(() => {}));
      const { result } = renderHook(() => useAgentStream(session, 'empty-response'));
      act(() => result.current.hydrateThread({ messages: [], graphData: graph('previous') }));
      act(() => result.current.acknowledgeGraphRendered(graphStructureKey(result.current.graphData)));
      act(() => result.current.sendMessage('Draw the next system'));
      const clientRequestId = mocks.sendMessage.mock.calls.at(-1)![4] as string;
      const emit = (event: ServerEvent) => act(() => mocks.eventHandler?.(event, { kind: 'chat', clientRequestId }));
      if (scenario === 'whitespace') emit({ type: 'response_delta', content: ' \n ' });
      if (scenario === 'reset') {
        emit({ type: 'response_delta', content: 'Discarded answer' });
        emit({ type: 'response_reset' });
      }
      if (scenario === 'preview') emit({ type: 'graph_preview', data: graph('preview') });
      if (scenario === 'existing') emit({ type: 'graph_data', data: graph('previous') });
      if (scenario === 'empty-graph') {
        emit({ type: 'graph_data', data: { ...graph('empty'), nodes: [] } });
        emit({ type: 'graph_data', data: null });
      }
      emit({ type: 'done' });
      emit({ type: 'done' });
      expect(result.current.visibleMessages.filter(message => message.content.includes('could not be completed'))).toHaveLength(1);
      expect(result.current.graphData).toEqual(graph('previous'));
      expect(result.current.streamStatus).toBe('connected');
      expect(mocks.trackEvent).toHaveBeenCalledWith('chat_stream_failed', expect.objectContaining({ error_code: 'empty_response' }), session);
      expect(mocks.trackEvent).not.toHaveBeenCalledWith('chat_stream_completed', expect.anything(), expect.anything());
      expect(mocks.sendMessage).toHaveBeenCalledTimes(1);
    },
  );

  it('does not count output preceding a response reset as a successful new turn', () => {
    mocks.sendMessage.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useAgentStream(session, 'reset-output'));
    act(() => result.current.sendMessage('Draw a system'));
    const clientRequestId = mocks.sendMessage.mock.calls.at(-1)![4] as string;
    act(() => {
      mocks.eventHandler?.({ type: 'graph_data', data: graph() }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({ type: 'response_delta', content: 'Superseded answer' }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({ type: 'response_reset' }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({ type: 'done' }, { kind: 'chat', clientRequestId });
    });
    expect(result.current.messages.map(message => message.content)).not.toContain('Superseded answer');
    expect(result.current.messages.map(message => message.content)).toContain('The response could not be completed. Please try again.');
    expect(result.current.graphData).toEqual(graph());
    expect(mocks.trackEvent).toHaveBeenCalledWith('chat_stream_failed', expect.objectContaining({ error_code: 'empty_response' }), session);
    expect(mocks.trackEvent).not.toHaveBeenCalledWith('chat_stream_completed', expect.anything(), expect.anything());
  });

  it.each(['text', 'explanation', 'graph'] as const)('accepts useful current-turn %s output', output => {
    mocks.sendMessage.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useAgentStream(session, 'useful-response'));
    act(() => result.current.sendMessage('Draw a system'));
    const clientRequestId = mocks.sendMessage.mock.calls.at(-1)![4] as string;
    act(() => {
      if (output === 'graph') mocks.eventHandler?.({ type: 'graph_data', data: graph() }, { kind: 'chat', clientRequestId });
      else if (output === 'text') mocks.eventHandler?.({ type: 'response_delta', content: 'Available answer' }, { kind: 'chat', clientRequestId });
      else mocks.eventHandler?.({ type: 'explanation_block', block_id: 'one', title: 'Overview', content: 'Available explanation', related_node_ids: [], evidence_refs: [] }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({ type: 'done' }, { kind: 'chat', clientRequestId });
    });
    expect(result.current.messages.some(message => message.content.includes('could not be completed'))).toBe(false);
    expect(mocks.trackEvent).toHaveBeenCalledWith('chat_stream_completed', expect.anything(), session);
  });

  describe('graph paint grace period', () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    it.each(['done', 'error', 'stop', 'disconnect'] as const)('reveals text after %s even if the canvas never acknowledges', async terminal => {
      const pending = deferred<boolean>();
      mocks.sendMessage.mockReturnValue(pending.promise);
      const { result } = renderHook(() => useAgentStream(session, 'missing-paint'));
      act(() => result.current.sendMessage('Draw a system'));
      const clientRequestId = mocks.sendMessage.mock.calls.at(-1)![4] as string;
      act(() => {
        mocks.eventHandler?.({ type: 'graph_data', data: graph() }, { kind: 'chat', clientRequestId });
        mocks.eventHandler?.({ type: 'response_delta', content: 'Available answer' }, { kind: 'chat', clientRequestId });
        vi.advanceTimersByTime(10000);
      });
      expect(result.current.answerPending).toBe(true);
      await act(async () => {
        if (terminal === 'stop') result.current.stopGeneration();
        else if (terminal === 'disconnect') pending.resolve(false);
        else mocks.eventHandler?.(terminal === 'error' ? { type: 'error', content: 'Unavailable' } : { type: 'done' }, { kind: 'chat', clientRequestId });
      });
      act(() => vi.advanceTimersByTime(2999));
      expect(result.current.answerPending).toBe(true);
      act(() => vi.advanceTimersByTime(1));
      expect(result.current.answerPending).toBe(false);
      expect(result.current.visibleMessages.map(message => message.content)).toContain('Available answer');
      expect(result.current.graphData).toEqual(graph());
      expect(mocks.sendMessage).toHaveBeenCalledTimes(1);
    });

    it.each(['thread', 'hydrate', 'unmount', 'acknowledge', 'next-turn'] as const)('cleans up the pending paint timer on %s', cleanup => {
      mocks.sendMessage.mockReturnValue(new Promise(() => {}));
      const { result, rerender, unmount } = renderHook(({ threadId }) => useAgentStream(session, threadId), { initialProps: { threadId: 'one' } });
      act(() => result.current.sendMessage('Draw a system'));
      const clientRequestId = mocks.sendMessage.mock.calls.at(-1)![4] as string;
      act(() => {
        mocks.eventHandler?.({ type: 'graph_data', data: graph() }, { kind: 'chat', clientRequestId });
        mocks.eventHandler?.({ type: 'done' }, { kind: 'chat', clientRequestId });
      });
      expect(vi.getTimerCount()).toBe(1);
      act(() => {
        if (cleanup === 'thread') rerender({ threadId: 'two' });
        if (cleanup === 'hydrate') result.current.hydrateThread({ messages: [], graphData: graph() });
        if (cleanup === 'unmount') unmount();
        if (cleanup === 'acknowledge') result.current.acknowledgeGraphRendered(graphStructureKey(result.current.graphData));
        if (cleanup === 'next-turn') result.current.sendMessage('Draw another system');
      });
      expect(vi.getTimerCount()).toBe(0);
      if (cleanup === 'next-turn') {
        act(() => vi.advanceTimersByTime(10000));
        expect(result.current.answerPending).toBe(true);
      }
    });
  });

  it('holds the answer through stream completion until the committed graph paints', () => {
    mocks.sendMessage.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useAgentStream(session, 'ordering'));
    act(() => result.current.sendMessage('Draw a retrieval system'));
    const clientRequestId = mocks.sendMessage.mock.calls.at(-1)![4] as string;
    const emit = (event: ServerEvent) => act(() => mocks.eventHandler?.(event, { kind: 'chat', clientRequestId }));
    emit({ type: 'response_delta', content: 'The answer' });
    expect(result.current.visibleMessages.map(message => message.content)).not.toContain('The answer');
    expect(result.current.messages.map(message => message.content)).toContain('The answer');
    emit({ type: 'graph_data', data: graph() });
    emit({ type: 'done' });
    expect(result.current.answerPending).toBe(true);
    act(() => result.current.acknowledgeGraphRendered('stale-graph'));
    expect(result.current.answerPending).toBe(true);
    act(() => result.current.acknowledgeGraphRendered(graphStructureKey(result.current.graphData)));
    expect(result.current.answerPending).toBe(false);
    expect(result.current.visibleMessages.map(message => message.content)).toContain('The answer');
    expect(result.current.diagramRequested).toBe(true);
  });

  it.each(['done', 'error', 'stop', 'disconnect'] as const)('releases an answer without a graph on %s', async terminal => {
    const pending = deferred<boolean>();
    mocks.sendMessage.mockReturnValue(pending.promise);
    const { result } = renderHook(() => useAgentStream(session, 'no-graph'));
    act(() => result.current.sendMessage('Draw a system'));
    const clientRequestId = mocks.sendMessage.mock.calls.at(-1)![4] as string;
    act(() => mocks.eventHandler?.({ type: 'response_delta', content: 'Available explanation' }, { kind: 'chat', clientRequestId }));
    expect(result.current.answerPending).toBe(true);
    await act(async () => {
      if (terminal === 'stop') result.current.stopGeneration();
      else if (terminal === 'disconnect') pending.resolve(false);
      else mocks.eventHandler?.(terminal === 'error' ? { type: 'error', content: 'Failed' } : { type: 'done' }, { kind: 'chat', clientRequestId });
    });
    expect(result.current.answerPending).toBe(false);
    expect(result.current.visibleMessages.map(message => message.content)).toContain('Available explanation');
    expect(result.current.diagramRequested).toBe(true);
  });

  it('streams text-only answers and resets presentation when switching threads', () => {
    mocks.sendMessage.mockReturnValue(new Promise(() => {}));
    const { result, rerender } = renderHook(({ threadId }) => useAgentStream(session, threadId), { initialProps: { threadId: 'one' } });
    act(() => result.current.sendMessage('Explain retrieval', { graphMode: 'off' }));
    const clientRequestId = mocks.sendMessage.mock.calls.at(-1)![4] as string;
    act(() => mocks.eventHandler?.({ type: 'response_delta', content: 'Text only' }, { kind: 'chat', clientRequestId }));
    expect(result.current.answerPending).toBe(false);
    expect(result.current.visibleMessages.map(message => message.content)).toContain('Text only');
    rerender({ threadId: 'two' });
    expect(result.current.diagramRequested).toBe(false);
    expect(result.current.visibleMessages).toEqual([]);
  });

  it('reveals matching validated blocks as a preview paints without committing or ending the stream', () => {
    mocks.sendMessage.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useAgentStream(session, 'progressive-preview'));
    act(() => result.current.sendMessage('Draw a system'));
    const clientRequestId = mocks.sendMessage.mock.calls.at(-1)![4] as string;
    const emit = (event: ServerEvent) => act(() => mocks.eventHandler?.(event, { kind: 'chat', clientRequestId }));
    const block = (content: string, version: string): ServerEvent => ({ type: 'explanation_block', block_id: content, title: 'How it works', content, related_node_ids: [], evidence_refs: [], graph_version: version });
    emit({ type: 'graph_preview', data: graph('preview') });
    emit(block('First validated block', 'preview'));
    expect(result.current.visibleMessages).toHaveLength(1);
    act(() => result.current.acknowledgeGraphRendered(graphStructureKey(result.current.graphPreview)));
    expect(result.current.visibleMessages.map(message => message.content)).toContain('First validated block');
    emit(block('Second validated block', 'preview'));
    emit(block('Wrong graph block', 'other'));
    emit({ type: 'response_delta', content: 'Unversioned partial' });
    expect(result.current.visibleMessages.map(message => message.content)).toEqual(['Draw a system', 'First validated block', 'Second validated block']);
    expect(result.current.graphData).toBeNull();
    expect(result.current.publishedGraphKey).toBeNull();
    expect(result.current.streamStatus).toBe('generating');
    expect(result.current.answerPending).toBe(true);
    emit({ type: 'graph_data', data: graph('rollback') });
    expect(result.current.visibleMessages).toHaveLength(1);
    emit({ type: 'response_reset' });
    expect(result.current.messages.map(message => message.content)).toEqual(['Draw a system']);
  });

  it('matches explanation visibility to the retained connected graph during a component-only edit', () => {
    mocks.sendMessage.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useAgentStream(session, 'progressive-edit'));
    const existing: GraphData = { ...graph('existing'), edges: [{ source: 'agent', target: 'agent', label: 'flow', technology: '', sync: 'sync', description: '' }] };
    act(() => result.current.hydrateThread({ messages: [], graphData: existing }));
    act(() => result.current.sendMessage('Extend this diagram'));
    const clientRequestId = mocks.sendMessage.mock.calls.at(-1)![4] as string;
    const emit = (event: ServerEvent) => act(() => mocks.eventHandler?.(event, { kind: 'chat', clientRequestId }));
    emit({ type: 'graph_preview', data: { ...graph('components'), edges: [] } });
    act(() => result.current.acknowledgeGraphRendered(graphStructureKey(result.current.graphPreview)));
    emit({ type: 'explanation_block', block_id: 'one', title: 'Components', content: 'Hidden component preview', related_node_ids: [], evidence_refs: [], graph_version: 'components' });
    expect(result.current.visibleMessages).toHaveLength(1);
    act(() => result.current.acknowledgeGraphRendered(graphStructureKey(result.current.graphData)));
    emit({ type: 'explanation_block', block_id: 'two', title: 'Existing', content: 'Visible existing diagram', related_node_ids: [], evidence_refs: [], graph_version: 'existing' });
    expect(result.current.visibleMessages.map(message => message.content)).toEqual(['Extend this diagram', 'Visible existing diagram']);
  });

  it('holds unversioned explanations until that graph is committed and the stream ends', () => {
    mocks.sendMessage.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useAgentStream(session, 'preview-handoff'));
    act(() => result.current.sendMessage('Draw a system'));
    const clientRequestId = mocks.sendMessage.mock.calls.at(-1)![4] as string;
    const emit = (event: ServerEvent) => act(() => mocks.eventHandler?.(event, { kind: 'chat', clientRequestId }));
    emit({ type: 'graph_preview', data: graph() });
    act(() => result.current.acknowledgeGraphRendered(graphStructureKey(result.current.graphPreview)));
    emit({ type: 'explanation_block', block_id: 'one', title: 'How it works', content: 'The walkthrough', related_node_ids: ['agent'], evidence_refs: [] });
    expect(result.current.visibleMessages.map(message => message.content)).not.toContain('The walkthrough');
    emit({ type: 'graph_data', data: graph() });
    expect(result.current.answerPending).toBe(true);
    emit({ type: 'done' });
    expect(result.current.answerPending).toBe(false);
    expect(result.current.visibleMessages.map(message => message.content)).toContain('The walkthrough');
  });

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.eventHandler = null;
    mocks.sendMessage.mockResolvedValue(true);
    mocks.sendNodeSelected.mockResolvedValue(true);
    mocks.isChatActive.mockReturnValue(false);
    mocks.steerGeneration.mockReturnValue(false);
    mocks.useSearchTool.mockResolvedValue({ ok: true, status: 'search_requested' });
    mocks.saveGraphContentEdit.mockReset();
    mocks.fetchThread.mockResolvedValue({ messages: [] });
  });

  it('keeps canonical graph unchanged until an edit saves and retains the saved graph after a later stream error', async () => {
    const save = deferred<GraphData>();
    mocks.saveGraphContentEdit.mockReturnValue(save.promise);
    const { result } = renderHook(() => useAgentStream(session, 'thread-1'));
    act(() => result.current.hydrateThread({ messages: [], graphData: graph('original') }));
    act(() => result.current.selectNode(graph('original').nodes[0]));

    let savePromise!: Promise<void>;
    act(() => {
      savePromise = result.current.saveGraphEdit({ nodes: [{ id: 'agent', label: 'Edited Agent' }] });
    });
    expect(mocks.saveGraphContentEdit).toHaveBeenCalledWith(
      session,
      'thread-1',
      'original',
      { nodes: [{ id: 'agent', label: 'Edited Agent' }] },
    );
    expect(result.current.graphData?.nodes[0].label).toBe('Agent');
    expect(result.current.isSavingGraphEdit).toBe(true);
    act(() => result.current.sendMessage('new request'));
    expect(mocks.sendMessage).not.toHaveBeenCalled();

    await act(async () => {
      save.resolve({ ...graph('edited'), nodes: [{ ...graph('edited').nodes[0], label: 'Edited Agent' }] });
      await savePromise;
    });
    expect(result.current.graphData?.version).toBe('edited');
    expect(result.current.selectedNode?.node.label).toBe('Edited Agent');
    expect(result.current.isSavingGraphEdit).toBe(false);

    act(() => result.current.sendMessage('new request'));
    const clientRequestId = mocks.sendMessage.mock.calls.at(-1)?.[4] as string;
    act(() => mocks.eventHandler?.({ type: 'error', content: 'later failure' }, { kind: 'chat', clientRequestId }));
    expect(result.current.graphData?.nodes[0].label).toBe('Edited Agent');
  });

  it('preserves the graph and allows retry after an edit save fails', async () => {
    mocks.saveGraphContentEdit.mockRejectedValueOnce(new Error('The diagram changed.'));
    mocks.saveGraphContentEdit.mockResolvedValueOnce({ ...graph('retry'), title: 'Saved on retry' });
    const { result } = renderHook(() => useAgentStream(session, 'thread-1'));
    act(() => result.current.hydrateThread({ messages: [], graphData: graph('original') }));

    await expect(result.current.saveGraphEdit({ nodes: [{ id: 'agent', label: 'Attempt' }] })).rejects.toThrow('The diagram changed.');
    expect(result.current.graphData?.version).toBe('original');
    expect(result.current.isSavingGraphEdit).toBe(false);
    await act(async () => result.current.saveGraphEdit({ nodes: [{ id: 'agent', label: 'Retry' }] }));
    expect(result.current.graphData?.version).toBe('retry');
  });

  it('preserves an explicitly edited decision type with authorization text after save and hydration', async () => {
    const editedNode = {
      ...graph('saved').nodes[0],
      label: 'Authorization gate',
      description: 'Authorization determines access.',
      type: 'decision' as const,
      user_edited_fields: ['type'],
    };
    const savedGraph = { ...graph('saved'), nodes: [editedNode] };
    mocks.saveGraphContentEdit.mockResolvedValue(savedGraph);
    const { result } = renderHook(() => useAgentStream(session, 'thread-1'));
    act(() => result.current.hydrateThread({ messages: [], graphData: graph('original') }));

    await act(async () => result.current.saveGraphEdit({
      nodes: [{ id: 'agent', type: 'decision', description: 'Authorization determines access.' }],
    }));
    expect(result.current.graphData?.nodes[0].type).toBe('decision');
    act(() => result.current.hydrateThread({ messages: [], graphData: savedGraph }));
    expect(result.current.graphData?.nodes[0].type).toBe('decision');
  });

  it('ignores an edit response after switching threads', async () => {
    const save = deferred<GraphData>();
    mocks.saveGraphContentEdit.mockReturnValue(save.promise);
    const { result, rerender } = renderHook(({ threadId }) => useAgentStream(session, threadId), {
      initialProps: { threadId: 'thread-a' },
    });
    act(() => result.current.hydrateThread({ messages: [], graphData: graph('a') }));

    let savePromise!: Promise<void>;
    act(() => {
      savePromise = result.current.saveGraphEdit({ nodes: [{ id: 'agent', label: 'A edited' }] });
    });
    rerender({ threadId: 'thread-b' });
    act(() => result.current.hydrateThread({ messages: [], graphData: graph('b') }));
    await act(async () => {
      save.resolve({ ...graph('a-edited'), title: 'A edited' });
      await savePromise;
    });
    expect(result.current.graphData?.version).toBe('b');
    expect(result.current.isSavingGraphEdit).toBe(false);
  });

  it('rejects overlapping graph edits and edits during active generation', async () => {
    const save = deferred<GraphData>();
    mocks.saveGraphContentEdit.mockReturnValue(save.promise);
    mocks.sendMessage.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useAgentStream(session, 'thread-1'));
    act(() => result.current.hydrateThread({ messages: [], graphData: graph('original') }));

    let firstSave!: Promise<void>;
    act(() => {
      firstSave = result.current.saveGraphEdit({ nodes: [{ id: 'agent', label: 'First' }] });
    });
    await expect(result.current.saveGraphEdit({ nodes: [{ id: 'agent', label: 'Second' }] }))
      .rejects.toThrow('Wait for the current diagram edit');
    expect(mocks.saveGraphContentEdit).toHaveBeenCalledTimes(1);

    await act(async () => {
      save.resolve(graph('saved'));
      await firstSave;
    });
    act(() => result.current.sendMessage('generate'));
    await expect(result.current.saveGraphEdit({ nodes: [{ id: 'agent', label: 'During generation' }] }))
      .rejects.toThrow('Wait for diagram generation');
    expect(mocks.saveGraphContentEdit).toHaveBeenCalledTimes(1);
  });

  it('streams chat events into messages, graph state, notices, and completion analytics', async () => {
    render(<Harness />);

    fireEvent.click(screen.getByText('send'));
    const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;

    expect(screen.getByTestId('status').textContent).toBe('generating');
    expect(mocks.trackEvent).toHaveBeenCalledWith(
      'chat_sent',
      expect.objectContaining({ complexity: 'production', graph_mode: 'on', research_enabled: true }),
      session,
    );

    act(() => {
      mocks.eventHandler?.({ type: 'worker_status', worker: 'rag', status: 'Searching book…' }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({ type: 'response_delta', content: 'Hello ' }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({ type: 'response_delta', content: 'world' }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({ type: 'provider_switch', provider: 'openai' }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({ type: 'retrieval_notice', request_id: 'req-1', message: 'Weak match' }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({ type: 'graph_data', data: graph('1') }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({ type: 'graph_notice', message: 'No graph available' }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({
        type: 'node_detail',
        node_id: 'agent',
        description: 'Detailed agent description',
        book_refs: ['Chapter 6, p.329'],
        graph_version: '1',
      }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({ type: 'done' }, { kind: 'chat', clientRequestId });
    });

    expect(screen.getByTestId('messages').textContent).toContain('assistant:Hello world:done');
    expect(screen.getByTestId('worker').textContent).toContain('"rag":null');
    expect(screen.getByTestId('provider').textContent).toBe('');
    expect(screen.getByTestId('retrieval').textContent).toBe('');
    expect(screen.getByTestId('graph-notice').textContent).toBe('No graph available');
    expect(screen.getByTestId('graph-title').textContent).toBe('Agent Map');
    expect(screen.getByTestId('node-detail').textContent).toBe('Detailed agent description');
    expect(screen.getByTestId('status').textContent).toBe('connected');
    expect(mocks.trackEvent).toHaveBeenCalledWith(
      'chat_stream_completed',
      expect.objectContaining({ thread_id: 'thread-1', client_request_id: clientRequestId }),
      session,
    );
  });

  it('ignores stale chat events from an old client request id', () => {
    render(<Harness />);

    fireEvent.click(screen.getByText('send'));

    act(() => {
      mocks.eventHandler?.({ type: 'response_delta', content: 'stale' }, { kind: 'chat', clientRequestId: 'old' });
    });

    expect(screen.getByTestId('messages').textContent).toContain('user:hello:done');
    expect(screen.getByTestId('messages').textContent).not.toContain('stale');
  });

  it('records SSE error events and resets stream state', () => {
    render(<Harness />);

    fireEvent.click(screen.getByText('send'));
    const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;

    act(() => {
      mocks.eventHandler?.({ type: 'response_delta', content: 'partial' }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({ type: 'error', content: 'backend failed' }, { kind: 'chat', clientRequestId });
    });

    expect(screen.getByTestId('messages').textContent).toContain('assistant:partial:done');
    expect(screen.getByTestId('messages').textContent).toContain('assistant:Error: backend failed:done');
    expect(screen.getByTestId('status').textContent).toBe('connected');
    expect(mocks.trackEvent).toHaveBeenCalledWith(
      'chat_stream_failed',
      expect.objectContaining({ error_code: 'backend failed' }),
      session,
    );
  });

  it('does not count an error followed by done as a completed stream', () => {
    render(<Harness />);
    fireEvent.click(screen.getByText('send'));
    const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;

    act(() => {
      mocks.eventHandler?.({ type: 'error', content: 'rejected' }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({ type: 'done' }, { kind: 'chat', clientRequestId });
    });
    expect(screen.getByTestId('messages').textContent).not.toContain('could not be completed');

    expect(mocks.trackEvent).toHaveBeenCalledWith(
      'chat_stream_failed',
      expect.objectContaining({ error_code: 'rejected' }),
      session,
    );
    expect(mocks.trackEvent).not.toHaveBeenCalledWith(
      'chat_stream_completed',
      expect.anything(),
      expect.anything(),
    );
  });

  it('adds connection-closed and network-failure messages from sendMessage promise outcomes', async () => {
    mocks.sendMessage.mockResolvedValueOnce(false);
    render(<Harness />);
    fireEvent.click(screen.getByText('send'));

    await waitFor(() => {
      expect(screen.getByTestId('messages').textContent).toContain('Connection closed before the response finished');
    });

    mocks.sendMessage.mockRejectedValueOnce(new Error('offline'));
    fireEvent.click(screen.getByText('send'));

    await waitFor(() => {
      expect(screen.getByTestId('messages').textContent).toContain('Connection lost. Retry will first check whether your response was saved.');
      expect(screen.getByTestId('messages').textContent).not.toContain('offline');
    });
  });

  it('offers safe retry for a timed-out started turn without exposing error details', async () => {
    const timeout = new ChatTurnTimeoutError();
    timeout.message = 'private transport diagnostic';
    mocks.sendMessage.mockRejectedValueOnce(timeout);
    render(<Harness />);
    fireEvent.click(screen.getByText('send'));

    await waitFor(() => {
      expect(screen.getByTestId('messages').textContent).toContain(
        'The connection timed out. Retry will first check whether your response was saved.',
      );
      expect(screen.getByTestId('messages').textContent).not.toContain('private transport diagnostic');
      expect(screen.getByTestId('messages').textContent).not.toContain('Connection lost. Retry will first check whether your response was saved.');
      expect(screen.getByTestId('status').textContent).toBe('connected');
    });
    expect(mocks.sendMessage).toHaveBeenCalledTimes(1);
  });

  it('requests the optional search tool', async () => {
    render(<Harness />);

    fireEvent.click(screen.getByText('send'));
    const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;
    act(() => {
      mocks.eventHandler?.({ type: 'retrieval_notice', request_id: 'req-1', message: 'Weak match' }, { kind: 'chat', clientRequestId });
    });

    fireEvent.click(screen.getByText('search'));
    await waitFor(() => {
      expect(mocks.useSearchTool).toHaveBeenCalledWith(session, 'thread-1', 'req-1');
      expect(screen.getByTestId('retrieval-requested').textContent).toBe('yes');
    });
  });

  it('handles expired optional search tool requests', async () => {
    mocks.useSearchTool.mockResolvedValueOnce({ ok: false, status: 'expired' });
    render(<Harness />);

    fireEvent.click(screen.getByText('send'));
    const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;
    act(() => {
      mocks.eventHandler?.({ type: 'retrieval_notice', request_id: 'req-2', message: 'Still weak' }, { kind: 'chat', clientRequestId });
    });
    fireEvent.click(screen.getByText('search'));

    await waitFor(() => {
      expect(screen.getByTestId('messages').textContent).toContain('Search tool is no longer available');
    });
  });

  it('shows a connection error when requesting the search tool fails', async () => {
    mocks.useSearchTool.mockRejectedValueOnce(new Error('offline'));
    render(<Harness />);

    fireEvent.click(screen.getByText('send'));
    const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;
    act(() => {
      mocks.eventHandler?.({ type: 'retrieval_notice', request_id: 'req-3', message: 'Weak match' }, { kind: 'chat', clientRequestId });
    });
    fireEvent.click(screen.getByText('search'));

    await waitFor(() => {
      expect(screen.getByTestId('messages').textContent).toContain('Connection lost. Please try again.');
      expect(screen.getByTestId('messages').textContent).not.toContain('offline');
      expect(screen.getByTestId('retrieval').textContent).toBe('');
    });
  });

  it('hydrates thread state and resets it when active thread changes', () => {
    const { rerender } = render(<Harness threadId="thread-1" />);

    fireEvent.click(screen.getByText('hydrate'));
    expect(screen.getByTestId('messages').textContent).toContain('user:old');
    expect(screen.getByTestId('graph-title').textContent).toBe('Agent Map');

    rerender(<Harness threadId="thread-2" />);

    expect(screen.getByTestId('messages').textContent).toBe('');
    expect(screen.getByTestId('graph-title').textContent).toBe('');
  });

  it('streams node-selected suggestions and reuses cached suggestions on repeat click', async () => {
    render(<Harness />);

    fireEvent.click(screen.getByText('node'));
    const clientRequestId = mocks.sendNodeSelected.mock.calls[0][5] as string;

    expect(screen.getByTestId('selected').textContent).toBe(
      'agent:Explain Agent clearly,Expand graph around Agent,Compare Agent trade-offs',
    );

    act(() => {
      mocks.eventHandler?.({ type: 'suggested_questions', questions: ['Explain', 'Expand'] }, { kind: 'node-selected', clientRequestId });
    });

    expect(screen.getByTestId('selected').textContent).toBe('agent:Explain,Expand');

    fireEvent.click(screen.getByText('node'));

    expect(mocks.sendNodeSelected).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('selected').textContent).toBe('agent:Explain,Expand');
  });

  it('keeps immediate node suggestions when model refinement is empty', () => {
    render(<Harness />);

    fireEvent.click(screen.getByText('node'));
    const clientRequestId = mocks.sendNodeSelected.mock.calls[0][5] as string;
    act(() => {
      mocks.eventHandler?.({ type: 'suggested_questions', questions: [] }, { kind: 'node-selected', clientRequestId });
    });

    expect(screen.getByTestId('selected').textContent).toBe(
      'agent:Explain Agent clearly,Expand graph around Agent,Compare Agent trade-offs',
    );
  });

  it('logs node-selected request failures', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    mocks.sendNodeSelected.mockRejectedValueOnce(new Error('node offline'));
    render(<Harness />);

    fireEvent.click(screen.getByText('node'));

    await waitFor(() => {
      expect(consoleError).toHaveBeenCalledWith('[sse] node-selected error:', expect.any(Error));
    });
    consoleError.mockRestore();
  });

  it('keeps thinking chunks separate by operation, resets attempts, and bounds recent text', () => {
    const { result } = renderHook(() => useAgentStream(session, 'thread-1'));
    act(() => { result.current.sendMessage('design'); });
    const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;
    const emit = (event: ServerEvent) => act(() => mocks.eventHandler?.(event, { kind: 'chat', clientRequestId }));
    for (const content of ['hel', 'lo ', '<script>plain</script>']) {
      emit({ type: 'thinking_delta', operation_id: 'one', phase: 'components', content });
    }
    emit({ type: 'thinking_delta', operation_id: 'two', phase: 'review', content: 'parallel' });
    emit({ type: 'thinking_delta', operation_id: 'one', phase: 'components', content: ' latest' });
    expect(result.current.thinkingProgress.map(item => item.operationId)).toEqual(['two', 'one']);
    expect(result.current.thinkingProgress[1].content).toBe('hello <script>plain</script> latest');
    emit({ type: 'thinking_delta', operation_id: 'one', phase: 'review', content: 'wrong phase' });
    expect(result.current.thinkingProgress[1].phase).toBe('components');
    emit({ type: 'thinking_delta', operation_id: 'one', phase: 'components', content: 'fresh', reset: true });
    expect(result.current.thinkingProgress[1].content).toBe('fresh');
    emit({ type: 'thinking_delta', operation_id: 'one', phase: 'components', content: 'x'.repeat(8001) });
    expect(result.current.thinkingProgress[1].content).toBe('x'.repeat(8000));
    for (let index = 0; index < 9; index++) {
      emit({ type: 'thinking_delta', operation_id: `bounded-${index}`, phase: 'review', content: `${index}` });
    }
    expect(result.current.thinkingProgress).toHaveLength(8);
    expect(result.current.thinkingProgress[0].operationId).toBe('bounded-1');
    expect(result.current.messages).toHaveLength(1);
  });

  it.each(['done', 'error', 'stop', 'response_reset', 'thread'] as const)('clears transient thinking on %s', terminal => {
    const { result, rerender } = renderHook(({ threadId }) => useAgentStream(session, threadId), { initialProps: { threadId: 'thread-1' } });
    act(() => { result.current.sendMessage('design'); });
    const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;
    const event: ServerEvent = { type: 'thinking_delta', operation_id: 'operation', phase: 'review', content: 'Transient only' };
    const emit = (value: ServerEvent, kind: 'chat' | 'node-selected' = 'chat', requestId = clientRequestId) => act(() => mocks.eventHandler?.(value, { kind, clientRequestId: requestId }));
    emit({ type: 'thinking_delta', content: 'unscoped' });
    act(() => result.current.selectNode(graph().nodes[0]));
    const nodeRequestId = mocks.sendNodeSelected.mock.calls[0][5] as string;
    emit(event, 'node-selected', nodeRequestId);
    emit(event, 'chat', 'stale-request');
    expect(result.current.thinkingProgress).toEqual([]);
    emit(event);
    expect(result.current.thinkingProgress).toHaveLength(1);
    if (terminal === 'stop') act(() => result.current.stopGeneration());
    else if (terminal === 'thread') rerender({ threadId: 'other' });
    else if (terminal === 'error') emit({ type: 'error', content: 'failed' });
    else emit({ type: terminal });
    expect(result.current.thinkingProgress).toEqual([]);
    if (terminal !== 'response_reset') {
      emit(event);
      expect(result.current.thinkingProgress).toEqual([]);
    }
  });

  it.each(['missing', 'unpainted', 'retained', 'same-version', 'components', 'connections'] as const)(
    'accepts only the exact painted review preview: %s', scenario => {
      mocks.acceptPreview.mockReturnValue(true);
      const { result } = renderHook(() => useAgentStream(session, 'thread-1'));
      const durable: GraphData = { ...graph('saved'), edges: [{ source: 'agent', target: 'agent', label: 'flow', technology: '', sync: 'sync', description: '' }] };
      if (scenario === 'retained' || scenario === 'missing' || scenario === 'same-version') {
        act(() => result.current.hydrateThread({ messages: [], graphData: durable }));
      }
      act(() => { result.current.sendMessage('design'); });
      const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;
      const emit = (event: ServerEvent) => act(() => mocks.eventHandler?.(event, { kind: 'chat', clientRequestId }));
      const candidate: GraphData = { ...graph(scenario === 'same-version' || scenario === 'missing' ? 'saved' : 'candidate'), edges: scenario === 'connections' ? durable.edges : [] };
      if (scenario !== 'missing') emit({ type: 'graph_preview', data: candidate });
      if (scenario !== 'unpainted') {
        act(() => result.current.acknowledgeGraphRendered(graphStructureKey(
          scenario === 'retained' || scenario === 'missing' || scenario === 'same-version' ? durable : candidate,
        )));
      }
      emit({ type: 'graph_review_status', status: 'reviewing', graph_version: candidate.version!, stage: scenario === 'connections' ? 'connections' : 'components' });
      act(() => result.current.stopGeneration());
      if (scenario === 'components' || scenario === 'connections') {
        expect(mocks.acceptPreview).toHaveBeenCalledExactlyOnceWith(clientRequestId, 'candidate');
        expect(mocks.stopGeneration).not.toHaveBeenCalled();
        expect(result.current.isFinishingDiagram).toBe(true);
      } else {
        expect(mocks.acceptPreview).not.toHaveBeenCalled();
        expect(mocks.stopGeneration).toHaveBeenCalledExactlyOnceWith(clientRequestId);
        expect(result.current.graphData).toEqual(scenario === 'unpainted' ? null : durable);
        expect(result.current.graphPreview).toBeNull();
        expect(result.current.isFinishingDiagram).toBe(false);
      }
    },
  );

  it('accepts review once and keeps receiving synthesis until done', () => {
    mocks.acceptPreview.mockReturnValue(true);
    const { result } = renderHook(() => useAgentStream(session, 'thread-1'));
    act(() => { result.current.sendMessage('design'); });
    const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;
    const emit = (event: ServerEvent) => act(() => mocks.eventHandler?.(event, { kind: 'chat', clientRequestId }));
    emit({ type: 'graph_preview', data: graph('v1') });
    act(() => result.current.acknowledgeGraphRendered(graphStructureKey(result.current.graphPreview)));
    emit({ type: 'graph_review_status', status: 'reviewing', graph_version: 'v1', stage: 'connections' });
    act(() => { result.current.stopGeneration(); result.current.stopGeneration(); });
    expect(mocks.acceptPreview).toHaveBeenCalledExactlyOnceWith(clientRequestId, 'v1');
    expect(mocks.stopGeneration).not.toHaveBeenCalled();
    expect(result.current.isFinishingDiagram).toBe(true);
    expect(result.current.sendMessage('interrupt acceptance')).toBe(false);
    expect(mocks.steerGeneration).not.toHaveBeenCalled();
    expect(result.current.streamStatus).toBe('generating');
    expect(result.current.graphPreview?.version).toBe('v1');
    emit({ type: 'graph_review_status', status: 'accepted', graph_version: 'v1', stage: 'connections' });
    emit({ type: 'graph_review_status', status: 'closed', graph_version: 'v1', stage: 'connections' });
    emit({ type: 'response_delta', content: 'Finished answer' });
    emit({ type: 'done' });
    expect(result.current.messages.some(message => message.content === 'Finished answer')).toBe(true);
    expect(result.current.isFinishingDiagram).toBe(false);
  });

  it('shows an acceptance rejection without cancelling and cancels on unmount', () => {
    mocks.acceptPreview.mockReturnValue(true);
    const { result, unmount } = renderHook(() => useAgentStream(session, 'thread-1'));
    act(() => { result.current.sendMessage('design'); });
    const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;
    act(() => mocks.eventHandler?.({ type: 'graph_preview', data: graph('v1') }, { kind: 'chat', clientRequestId }));
    act(() => result.current.acknowledgeGraphRendered(graphStructureKey(result.current.graphPreview)));
    act(() => mocks.eventHandler?.({ type: 'graph_review_status', status: 'reviewing', graph_version: 'v1', stage: 'connections' }, { kind: 'chat', clientRequestId }));
    act(() => result.current.stopGeneration());
    act(() => mocks.eventHandler?.({ type: 'command_rejected', command_type: 'accept_preview', reason: 'Review already ended' }, { kind: 'chat', clientRequestId }));
    expect(result.current.isFinishingDiagram).toBe(false);
    expect(result.current.graphNotice?.message).toBe('Review already ended');
    expect(result.current.streamStatus).toBe('generating');
    expect(mocks.stopGeneration).not.toHaveBeenCalled();
    unmount();
    expect(mocks.stopGeneration).toHaveBeenCalledWith(clientRequestId);
  });

  it('stops generation and records stop analytics', () => {
    render(<Harness />);

    fireEvent.click(screen.getByText('send'));
    const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;
    act(() => {
      mocks.eventHandler?.({ type: 'response_delta', content: 'partial' }, { kind: 'chat', clientRequestId });
    });
    fireEvent.click(screen.getByText('stop'));

    expect(mocks.stopGeneration).toHaveBeenCalledWith(clientRequestId);
    expect(screen.getByTestId('messages').textContent).toContain('assistant:partial:done');
    expect(screen.getByTestId('status').textContent).toBe('connected');
    expect(mocks.trackEvent).toHaveBeenCalledWith(
      'chat_stopped',
      expect.objectContaining({ thread_id: 'thread-1', client_request_id: clientRequestId }),
      session,
    );
  });

  it('cancels request-scoped work when the active thread changes and ignores late events', async () => {
    const chat = deferred<boolean>();
    const node = deferred<boolean>();
    mocks.sendMessage.mockReturnValueOnce(chat.promise);
    mocks.sendNodeSelected.mockReturnValueOnce(node.promise);
    const { rerender } = render(<Harness threadId="thread-a" />);

    fireEvent.click(screen.getByText('send'));
    const chatRequestId = mocks.sendMessage.mock.calls[0][4] as string;
    act(() => {
      mocks.eventHandler?.({ type: 'response_delta', content: 'private A draft' }, { kind: 'chat', clientRequestId: chatRequestId });
    });
    fireEvent.click(screen.getByText('node'));
    const nodeRequestId = mocks.sendNodeSelected.mock.calls[0][5] as string;

    rerender(<Harness threadId="thread-b" />);

    expect(mocks.stopGeneration).toHaveBeenCalledWith(chatRequestId);
    expect(mocks.cancelNodeSelection).toHaveBeenCalledWith(nodeRequestId);
    expect(screen.getByTestId('messages').textContent).toBe('');
    act(() => {
      mocks.eventHandler?.({ type: 'response_delta', content: 'late A' }, { kind: 'chat', clientRequestId: chatRequestId });
      mocks.eventHandler?.({ type: 'graph_data', data: graph('late-a') }, { kind: 'chat', clientRequestId: chatRequestId });
      mocks.eventHandler?.({ type: 'done' }, { kind: 'chat', clientRequestId: chatRequestId });
      chat.resolve(false);
      node.resolve(false);
    });

    await waitFor(() => {
      expect(screen.getByTestId('messages').textContent).toBe('');
      expect(screen.getByTestId('graph-title').textContent).toBe('');
      expect(screen.getByTestId('status').textContent).toBe('connected');
    });
  });

  it('freezes a stopped partial and rejects late reset, delta, and done events', async () => {
    const chat = deferred<boolean>();
    mocks.sendMessage.mockReturnValueOnce(chat.promise);
    render(<Harness />);
    fireEvent.click(screen.getByText('send'));
    const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;
    act(() => {
      mocks.eventHandler?.({ type: 'response_delta', content: 'keep this partial' }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({
        type: 'graph_candidate',
        evaluation_id: 'eval-stop',
        graph_version: 'candidate-stop',
        criteria: diagramCriteria,
        data: graph('candidate-stop'),
      }, { kind: 'chat', clientRequestId });
    });

    fireEvent.click(screen.getByText('stop'));
    expect(screen.getByTestId('candidate-title').textContent).toBe('');
    act(() => {
      mocks.eventHandler?.({ type: 'response_reset' }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({ type: 'response_delta', content: 'late mutation' }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({ type: 'done' }, { kind: 'chat', clientRequestId });
      chat.resolve(false);
    });

    await waitFor(() => {
      expect(screen.getByTestId('messages').textContent).toContain('assistant:keep this partial:done');
      expect(screen.getByTestId('messages').textContent).not.toContain('late mutation');
      expect(screen.getByTestId('messages').textContent).not.toContain('Connection closed before');
      expect(screen.getByTestId('status').textContent).toBe('connected');
    });
  });

  it('clears private candidates after premature close and network rejection', async () => {
    const closed = deferred<boolean>();
    mocks.sendMessage.mockReturnValueOnce(closed.promise);
    render(<Harness />);
    fireEvent.click(screen.getByText('send'));
    const firstRequestId = mocks.sendMessage.mock.calls[0][4] as string;
    act(() => {
      mocks.eventHandler?.({
        type: 'graph_candidate',
        evaluation_id: 'eval-close',
        graph_version: 'candidate-close',
        criteria: diagramCriteria,
        data: graph('candidate-close'),
      }, { kind: 'chat', clientRequestId: firstRequestId });
      mocks.eventHandler?.({
        type: 'graph_preview',
        data: { ...graph('preview-close'), title: 'Closing preview' },
      }, { kind: 'chat', clientRequestId: firstRequestId });
      closed.resolve(false);
    });
    await waitFor(() => {
      expect(screen.getByTestId('candidate-title').textContent).toBe('');
      expect(screen.getByTestId('graph-title').textContent).toBe('');
      expect(screen.getByTestId('preview-title').textContent).toBe('');
    });

    const rejected = deferred<boolean>();
    mocks.sendMessage.mockReturnValueOnce(rejected.promise);
    fireEvent.click(screen.getByText('send'));
    const secondRequestId = mocks.sendMessage.mock.calls[1][4] as string;
    act(() => {
      mocks.eventHandler?.({
        type: 'graph_candidate',
        evaluation_id: 'eval-reject',
        graph_version: 'candidate-reject',
        criteria: diagramCriteria,
        data: graph('candidate-reject'),
      }, { kind: 'chat', clientRequestId: secondRequestId });
      mocks.eventHandler?.({
        type: 'graph_preview',
        data: { ...graph('preview-reject'), title: 'Rejected preview' },
      }, { kind: 'chat', clientRequestId: secondRequestId });
      rejected.reject(new Error('offline'));
    });
    await waitFor(() => {
      expect(screen.getByTestId('candidate-title').textContent).toBe('');
      expect(screen.getByTestId('graph-title').textContent).toBe('');
      expect(screen.getByTestId('preview-title').textContent).toBe('');
    });
  });

  it('steers the active WebSocket run instead of opening a second run', () => {
    mocks.steerGeneration.mockReturnValue(true);
    render(<Harness />);

    fireEvent.click(screen.getByText('send'));
    fireEvent.click(screen.getByText('send'));

    expect(mocks.sendMessage).toHaveBeenCalledTimes(1);
    expect(mocks.steerGeneration).toHaveBeenCalledWith('hello');
    expect(screen.getByTestId('messages').textContent).toContain('user:hello:done');
    expect(screen.getByTestId('messages').textContent).not.toContain('Steer:');
  });

  it('discards partial assistant output when a steer restarts the workflow', () => {
    render(<Harness />);
    fireEvent.click(screen.getByText('send'));
    const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;

    act(() => {
      mocks.eventHandler?.({ type: 'response_delta', content: 'obsolete draft' }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({ type: 'response_reset' }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({ type: 'response_delta', content: 'revised answer' }, { kind: 'chat', clientRequestId });
    });

    expect(screen.getByTestId('messages').textContent).not.toContain('obsolete draft');
    expect(screen.getByTestId('messages').textContent).toContain('revised answer');
  });

  it('displays previews separately and keeps only authoritative graph data across restarts', () => {
    render(<Harness />);
    fireEvent.click(screen.getByText('hydrate'));
    fireEvent.click(screen.getByText('send'));
    const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;

    act(() => {
      mocks.eventHandler?.({
        type: 'graph_preview',
        data: { ...graph('preview'), title: 'Preview graph' },
      }, { kind: 'chat', clientRequestId });
    });
    expect(screen.getByTestId('graph-title').textContent).toBe('Agent Map');
    expect(screen.getByTestId('preview-title').textContent).toBe('Preview graph');

    act(() => {
      mocks.eventHandler?.({ type: 'response_reset' }, { kind: 'chat', clientRequestId });
    });
    expect(screen.getByTestId('graph-title').textContent).toBe('Agent Map');
    expect(screen.getByTestId('preview-title').textContent).toBe('');

    act(() => {
      mocks.eventHandler?.({
        type: 'graph_data',
        data: { ...graph('committed'), title: 'Committed graph' },
      }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({
        type: 'graph_preview',
        data: { ...graph('later-preview'), title: 'Later preview' },
      }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({ type: 'error', content: 'failed' }, { kind: 'chat', clientRequestId });
    });
    expect(screen.getByTestId('graph-title').textContent).toBe('Committed graph');
    expect(screen.getByTestId('preview-title').textContent).toBe('');
  });

  it('clears previews on every terminal chat event', () => {
    render(<Harness />);
    fireEvent.click(screen.getByText('send'));
    const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;

    const preview = (title: string) => {
      act(() => {
        mocks.eventHandler?.({
          type: 'graph_preview',
          data: { ...graph(title), title },
        }, { kind: 'chat', clientRequestId });
      });
      expect(screen.getByTestId('preview-title').textContent).toBe(title);
    };

    preview('Reset preview');
    act(() => {
      mocks.eventHandler?.({ type: 'response_reset' }, { kind: 'chat', clientRequestId });
    });
    expect(screen.getByTestId('preview-title').textContent).toBe('');

    preview('Stopped preview');
    act(() => {
      mocks.eventHandler?.({ type: 'stopped' }, { kind: 'chat', clientRequestId });
    });
    expect(screen.getByTestId('preview-title').textContent).toBe('');

    preview('Done preview');
    act(() => {
      mocks.eventHandler?.({ type: 'done' }, { kind: 'chat', clientRequestId });
    });
    expect(screen.getByTestId('preview-title').textContent).toBe('');

    preview('Error preview');
    act(() => {
      mocks.eventHandler?.({ type: 'error', content: 'failed' }, { kind: 'chat', clientRequestId });
    });
    expect(screen.getByTestId('preview-title').textContent).toBe('');
  });

  it('clears a preview-only selection after rollback while keeping authoritative graph', () => {
    render(<Harness />);
    fireEvent.click(screen.getByText('hydrate'));
    fireEvent.click(screen.getByText('send'));
    const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;
    const previewGraph = {
      ...graph('preview-only'),
      title: 'Transient preview',
      nodes: [
        {
          id: 'preview-node',
          label: 'Transient',
          type: 'service' as const,
          technology: 'LLM',
          description: 'Draft-only node',
          detail: null,
        },
      ],
    };

    act(() => {
      mocks.eventHandler?.({
        type: 'graph_preview',
        data: previewGraph,
      }, { kind: 'chat', clientRequestId });
    });
    expect(screen.getByTestId('preview-title').textContent).toBe('Transient preview');

    fireEvent.click(screen.getByText('preview node'));
    expect(screen.getByTestId('selected').textContent).toContain('preview-node:');

    act(() => {
      mocks.eventHandler?.({ type: 'response_reset' }, { kind: 'chat', clientRequestId });
    });
    expect(screen.getByTestId('preview-title').textContent).toBe('');
    expect(screen.getByTestId('graph-title').textContent).toBe('Agent Map');
    expect(screen.getByTestId('selected').textContent).toBe('');
  });

  it('publishes accepted output immediately and resets only the active explanation', () => {
    render(<Harness />);
    fireEvent.click(screen.getByText('send'));
    const firstRequestId = mocks.sendMessage.mock.calls[0][4] as string;
    act(() => {
      mocks.eventHandler?.({
        type: 'explanation_block', block_id: 'old', title: 'Earlier',
        content: 'Earlier explanation', related_node_ids: [], evidence_refs: [],
      }, { kind: 'chat', clientRequestId: firstRequestId });
      mocks.eventHandler?.({ type: 'done' }, { kind: 'chat', clientRequestId: firstRequestId });
    });
    fireEvent.click(screen.getByText('send'));
    const clientRequestId = mocks.sendMessage.mock.calls[1][4] as string;
    act(() => {
      mocks.eventHandler?.({ type: 'graph_data', data: graph('accepted') }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({
        type: 'explanation_block', block_id: 'new', title: 'Current',
        content: 'Current explanation', related_node_ids: ['agent'], evidence_refs: [],
      }, { kind: 'chat', clientRequestId });
    });
    expect(screen.getByTestId('graph-title').textContent).toBe('Agent Map');
    expect(screen.getByTestId('messages').textContent).toContain('Current explanation');
    act(() => {
      mocks.eventHandler?.({ type: 'response_reset' }, { kind: 'chat', clientRequestId });
    });
    expect(screen.getByTestId('messages').textContent).not.toContain('Current explanation');
    expect(screen.getByTestId('messages').textContent).toContain('Earlier explanation');
    expect(screen.getByTestId('graph-title').textContent).toBe('Agent Map');
  });

  it('renders the exact private candidate without legacy node-type normalization', () => {
    render(<Harness />);
    fireEvent.click(screen.getByText('send'));
    const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;
    const candidate = graph('candidate-v1');
    candidate.nodes[0] = {
      ...candidate.nodes[0],
      label: 'Access control decision',
      type: 'decision',
    };

    act(() => {
      mocks.eventHandler?.({
        type: 'graph_candidate',
        evaluation_id: 'eval-exact',
        graph_version: 'candidate-v1',
        criteria: diagramCriteria,
        data: candidate,
      }, { kind: 'chat', clientRequestId });
    });

    expect(screen.getByTestId('candidate-node-type').textContent).toBe('decision');
  });

  it.each([
    undefined,
    { viewport_width: 1440, viewport_height: 960 },
    { ...diagramCriteria, minimum_text_px: Number.NaN },
    { ...diagramCriteria, viewport_width: 1280 },
    { ...diagramCriteria, extra: true },
  ])('fails closed for unsupported private render criteria: %j', criteria => {
    render(<Harness />);
    fireEvent.click(screen.getByText('send'));
    const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;

    act(() => {
      mocks.eventHandler?.({
        type: 'graph_candidate',
        evaluation_id: 'eval-missing-criteria',
        graph_version: 'candidate-v1',
        criteria,
        data: graph('candidate-v1'),
      } as unknown as ServerEvent, { kind: 'chat', clientRequestId });
    });

    expect(screen.getByTestId('candidate-title').textContent).toBe('');
  });

  it('shows an auth/thread error when sending without prerequisites', () => {
    render(<Harness auth={null} threadId={null} />);

    fireEvent.click(screen.getByText('send'));

    expect(screen.getByTestId('messages').textContent).toContain('Error: You must be signed in with an active thread.');
    expect(mocks.sendMessage).not.toHaveBeenCalled();
  });

  it('adopts a restored canonical graph without replacing messages', () => {
    const { result } = renderHook(() => useAgentStream(session, 'thread-1'));
    act(() => result.current.hydrateThread({ messages: [{ id: 'saved', role: 'assistant', content: 'Original answer' }], graphData: graph('1') }));
    act(() => result.current.selectNode(graph('1').nodes[0]));
    let accepted = false;
    act(() => { accepted = result.current.adoptRestoredGraph(graph('restored'), 'thread-1', '1'); });
    expect(accepted).toBe(true);
    expect(result.current.graphData?.version).toBe('restored');
    expect(result.current.selectedNode).toBeNull();
    expect(result.current.messages[0].content).toBe('Original answer');
    expect(result.current.adoptRestoredGraph(graph('stale'), 'thread-1', '1')).toBe(false);
    expect(result.current.adoptRestoredGraph(graph('wrong'), 'other-thread', 'restored')).toBe(false);
    mocks.sendMessage.mockReturnValue(new Promise(() => {}));
    act(() => result.current.sendMessage('new request'));
    expect(result.current.adoptRestoredGraph(graph('busy'), 'thread-1', 'restored')).toBe(false);
  });

  it('starts a created thread synchronously and survives matching thread hydration', () => {
    mocks.sendMessage.mockReturnValue(new Promise(() => {}));
    const detail: ThreadDetail = { thread: { id: 'thread-new', title: 'New', graph_data: null,
      created_at: '', updated_at: '', last_seen_at: '' }, messages: [] };
    const { result, rerender } = renderHook(({ threadId }) => useAgentStream(session, threadId), {
      initialProps: { threadId: 'thread-old' },
    });
    let accepted = false;
    act(() => { accepted = result.current.startThreadAndSend(detail, 'Fresh design', { graphAction: 'new' }); });
    expect(accepted).toBe(true);
    expect(mocks.sendMessage.mock.calls[0][1]).toBe('thread-new');
    rerender({ threadId: 'thread-new' });
    act(() => result.current.hydrateThread({ threadId: 'thread-new', messages: [], graphData: null }));
    expect(mocks.stopGeneration).not.toHaveBeenCalled();
    expect(result.current.messages.map(message => message.content)).toEqual(['Fresh design']);
    expect(result.current.streamStatus).toBe('generating');
  });

  it('rejects stale fresh-thread handoffs after a newer selection or account change', () => {
    const detail: ThreadDetail = { thread: { id: 'created', title: 'New', graph_data: null,
      created_at: '', updated_at: '', last_seen_at: '' }, messages: [] };
    const { result, rerender, unmount } = renderHook(({ auth, threadId }) => useAgentStream(auth, threadId), {
      initialProps: { auth: session, threadId: 'original' },
    });
    const oldHandoff = result.current.startThreadAndSend;
    rerender({ auth: session, threadId: 'selected' });
    expect(oldHandoff(detail, 'ignored')).toBe(false);
    const oldAccountHandoff = result.current.startThreadAndSend;
    rerender({ auth: { ...session, user: { ...session.user, id: 'other-user' } }, threadId: 'selected' });
    expect(oldAccountHandoff(detail, 'ignored')).toBe(false);
    const lastHandoff = result.current.startThreadAndSend;
    unmount();
    expect(lastHandoff(detail, 'ignored')).toBe(false);
    expect(mocks.sendMessage).not.toHaveBeenCalled();
  });

  it('decorates streamed cards with durable revision IDs without replacing content', async () => {
    mocks.sendMessage.mockReturnValue(new Promise(() => {}));
    const persisted = deferred<ThreadDetail>();
    mocks.fetchThread.mockReturnValueOnce(persisted.promise);
    const { result } = renderHook(() => useAgentStream(session, 'thread-1'));
    act(() => result.current.sendMessage('Question'));
    const clientRequestId = mocks.sendMessage.mock.calls[0][4];
    act(() => {
      mocks.eventHandler!({ type: 'explanation_block', block_id: 'block', title: 'Kept title', content: 'Styled text',
        related_node_ids: ['agent'], evidence_refs: [], graph_version: '1' }, { kind: 'chat', clientRequestId });
      mocks.eventHandler!({ type: 'done' }, { kind: 'chat', clientRequestId });
    });
    const localId = result.current.messages[1].id;
    await act(async () => { persisted.resolve({ messages: [{ id: 'durable-id', role: 'assistant', content: 'Stored flattened text',
      created_at: '', client_request_id: clientRequestId, graph_revision_id: 'revision-1' }] } as ThreadDetail); });
    expect(result.current.messages[1]).toMatchObject({ id: localId, title: 'Kept title', content: 'Styled text',
      kind: 'explanation', graphRevisionId: 'revision-1' });
  });

  it('ignores metadata arriving after the next send', async () => {
    mocks.sendMessage.mockReturnValue(new Promise(() => {}));
    const persisted = deferred<ThreadDetail>();
    mocks.fetchThread.mockReturnValueOnce(persisted.promise);
    const { result } = renderHook(() => useAgentStream(session, 'thread-1'));
    act(() => result.current.sendMessage('First'));
    const clientRequestId = mocks.sendMessage.mock.calls[0][4];
    act(() => {
      mocks.eventHandler!({ type: 'response_delta', content: 'First answer' }, { kind: 'chat', clientRequestId });
      mocks.eventHandler!({ type: 'done' }, { kind: 'chat', clientRequestId });
      result.current.sendMessage('Second');
    });
    await act(async () => { persisted.resolve({ messages: [{ id: 'old', role: 'assistant', content: 'Old', created_at: '',
      client_request_id: clientRequestId, graph_revision_id: 'revision-old' }] } as ThreadDetail); });
    expect(result.current.messages.map(message => message.content)).toEqual(['First', 'First answer', 'Second']);
    expect(result.current.messages[1].graphRevisionId).toBeUndefined();
  });

});
