import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { AuthSession, GraphData } from '../types';
import {
  captureAnalyticsEvent,
  checkDiagramIntent,
  createThread,
  deleteThread,
  fetchDashboardFailures,
  fetchDashboardFunnel,
  fetchDashboardLLMPerformance,
  fetchDashboardOverview,
  fetchDashboardTrends,
  fetchLatestThread,
  fetchThread,
  listThreads,
  prepareBackend,
  updateThreadGraph,
} from './api';


const session: AuthSession = {
  access_token: 'access-token',
  refresh_token: 'refresh-token',
  user: { id: 'user-1', email: 'user@example.com' },
};

const graph: GraphData = {
  graph_type: 'architecture',
  title: 'Saved graph',
  nodes: [],
  edges: [],
  sequence: [],
};

function response(data: unknown, options: { ok?: boolean; status?: number; jsonError?: Error } = {}) {
  return {
    ok: options.ok ?? true,
    status: options.status ?? 200,
    json: options.jsonError
      ? vi.fn().mockRejectedValue(options.jsonError)
      : vi.fn().mockResolvedValue(data),
  } as unknown as Response;
}


describe('API service boundary', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  function mockIntentTransport(responseDelay?: number) {
    vi.useFakeTimers();
    const deadline = vi.spyOn(AbortSignal, 'timeout').mockImplementation(timeout => {
      const controller = new AbortController();
      setTimeout(() => controller.abort(new DOMException('signal timed out', 'TimeoutError')), timeout);
      return controller.signal;
    });
    fetchMock.mockImplementation((_url, init) => new Promise<Response>((resolve, reject) => {
      const signal = init.signal as AbortSignal;
      signal.addEventListener('abort', () => reject(signal.reason), { once: true });
      if (responseDelay !== undefined) setTimeout(() => resolve(response({ action: 'new_chat' })), responseDelay);
    }));
    return deadline;
  }

  it('accepts a canonical intent response after the former five-second deadline', async () => {
    const deadline = mockIntentTransport(8470);
    const pending = checkDiagramIntent(session, 'thread-1', 'Explain RAG');
    await vi.advanceTimersByTimeAsync(5001);
    expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(3469);
    await expect(pending).resolves.toBe('new_chat');
    expect(deadline).toHaveBeenCalledExactlyOnceWith(15_000);
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith('/api/threads/thread-1/diagram-intent', expect.objectContaining({
      method: 'POST', body: JSON.stringify({ message: 'Explain RAG' }),
    }));
  });

  it('aborts intent checking at fifteen seconds with a draft-preserving error and no retry', async () => {
    const deadline = mockIntentTransport();
    const pending = checkDiagramIntent(session, 'thread-1', 'Explain RAG');
    const rejected = expect(pending).rejects.toThrow('Checking your request timed out. Your draft is saved. Please try again.');
    await vi.advanceTimersByTimeAsync(14_999);
    expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await rejected;
    expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(true);
    expect(deadline).toHaveBeenCalledExactlyOnceWith(15_000);
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it.each([
    new DOMException('cancelled', 'AbortError'),
    new TypeError('Failed to fetch'),
    Object.assign(new Error('unrelated timeout'), { name: 'TimeoutError' }),
  ])('preserves non-deadline intent errors', async error => {
    fetchMock.mockRejectedValueOnce(error);
    await expect(checkDiagramIntent(session, 'thread-1', 'Explain RAG')).rejects.toBe(error);
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it('sends authenticated thread operations and returns their typed payloads', async () => {
    const thread = { thread: { id: 'thread-1' }, messages: [] };
    fetchMock
      .mockResolvedValueOnce(response(thread))
      .mockResolvedValueOnce(response(thread))
      .mockResolvedValueOnce(response(thread))
      .mockResolvedValueOnce(response({ threads: [{ id: 'thread-1' }] }))
      .mockResolvedValueOnce(response(null))
      .mockResolvedValueOnce(response(null));

    await expect(fetchLatestThread(session)).resolves.toEqual(thread);
    await expect(fetchThread(session, 'thread-1')).resolves.toEqual(thread);
    await expect(createThread(session, 'Architecture review')).resolves.toEqual(thread);
    await expect(listThreads(session)).resolves.toEqual([{ id: 'thread-1' }]);
    await expect(deleteThread(session, 'thread-1')).resolves.toBeUndefined();
    await expect(updateThreadGraph(session, 'thread-1', graph)).resolves.toBeUndefined();

    expect(fetchMock).toHaveBeenCalledTimes(6);
    for (const [, init] of fetchMock.mock.calls) {
      expect(init?.headers).toMatchObject({
        'Content-Type': 'application/json',
        Authorization: 'Bearer access-token',
      });
    }
    expect(fetchMock.mock.calls[2][1]).toMatchObject({
      method: 'POST',
      body: JSON.stringify({ title: 'Architecture review' }),
    });
    expect(fetchMock.mock.calls[4][1]).toMatchObject({ method: 'DELETE' });
    expect(fetchMock.mock.calls[5][1]).toMatchObject({
      method: 'PUT',
      body: JSON.stringify({ graph_data: graph }),
    });
    expect(fetchMock.mock.calls[5][1].signal).toBeInstanceOf(AbortSignal);
  });

  it('bounds layout saves and leaves failures available for the editor to report', async () => {
    fetchMock.mockRejectedValueOnce(new DOMException('expired', 'TimeoutError'));

    await expect(updateThreadGraph(session, 'thread-1', graph))
      .rejects.toThrow('Saving the diagram layout timed out. Check the saved diagram before retrying.');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each([
    ['latest thread', () => fetchLatestThread(session), 'Failed to load latest thread'],
    ['thread', () => fetchThread(session, 'thread-1'), 'Failed to load thread'],
    ['create thread', () => createThread(session), 'Failed to create thread'],
    ['list threads', () => listThreads(session), 'Failed to list threads'],
    ['delete thread', () => deleteThread(session, 'thread-1'), 'Failed to delete thread'],
    ['update graph', () => updateThreadGraph(session, 'thread-1', graph), 'Failed to update thread graph'],
  ])('rejects a failed %s response', async (_label, request, message) => {
    fetchMock.mockResolvedValueOnce(response({}, { ok: false, status: 500 }));

    await expect(request()).rejects.toThrow(message);
  });

  it('preserves bounded preparing responses and reports structured prepare failures', async () => {
    fetchMock
      .mockResolvedValueOnce(response({ status: 'preparing', step: 'index' }, { ok: false, status: 503 }))
      .mockResolvedValueOnce(response({
        status: 'failed',
        detail: { step: 'artifact', status: 'Artifact signature rejected' },
      }, { ok: false, status: 500 }))
      .mockResolvedValueOnce(response({ status: 'ready', faiss_loaded: true }));

    await expect(prepareBackend()).resolves.toEqual({ status: 'preparing', step: 'index' });

    await expect(prepareBackend()).rejects.toMatchObject({
      message: 'Artifact signature rejected',
      step: 'artifact',
    });

    await expect(prepareBackend()).resolves.toEqual({ status: 'ready', faiss_loaded: true });
  });

  it('forwards preparation cancellation to fetch', async () => {
    const controller = new AbortController();
    fetchMock.mockImplementationOnce((_url, options) => new Promise((_resolve, reject) => {
      options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
    }));
    const pending = prepareBackend(controller.signal);
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    expect(fetchMock.mock.calls[0][1].signal).toBe(controller.signal);
  });

  it('reports plain and fallback prepare errors with an actionable step', async () => {
    fetchMock
      .mockResolvedValueOnce(response({ detail: 'Database unavailable', step: 'database' }, { ok: false }))
      .mockResolvedValueOnce(response({ status: '', detail: null }, { ok: false }));

    await expect(prepareBackend()).rejects.toMatchObject({
      message: 'Database unavailable',
      step: 'database',
    });

    await expect(prepareBackend()).rejects.toMatchObject({
      message: 'Backend is still warming up',
      step: 'unknown',
    });
  });

  it('captures public and authenticated analytics without leaking refresh tokens', async () => {
    fetchMock.mockResolvedValue(response(null));

    await captureAnalyticsEvent('auth_viewed', 'anon-1', { mode: 'email' });
    await captureAnalyticsEvent('thread_selected', 'anon-1', { thread_id: 'thread-1' }, session);

    expect(fetchMock.mock.calls[0][1].headers).toEqual({ 'Content-Type': 'application/json' });
    expect(fetchMock.mock.calls[1][1].headers).toEqual({
      'Content-Type': 'application/json',
      Authorization: 'Bearer access-token',
    });
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({
      anonymous_id: 'anon-1',
      event_type: 'thread_selected',
      properties: { thread_id: 'thread-1' },
    });
    expect(JSON.stringify(fetchMock.mock.calls)).not.toContain('refresh-token');
  });

  it('rejects failed analytics capture', async () => {
    fetchMock.mockResolvedValueOnce(response({}, { ok: false }));

    await expect(captureAnalyticsEvent('auth_viewed', 'anon-1', {})).rejects.toThrow(
      'Failed to capture analytics event',
    );
  });

  it('loads every dashboard view through the authenticated internal boundary', async () => {
    const payloads = [
      { window_hours: 24 },
      { bucket: 'hour', points: [] },
      { window_days: 7, steps: [] },
      { recent_failed_requests: [] },
      { operations: [] },
    ];
    payloads.forEach(payload => fetchMock.mockResolvedValueOnce(response(payload)));

    await expect(fetchDashboardOverview(session)).resolves.toEqual(payloads[0]);
    await expect(fetchDashboardTrends(session, 'hour')).resolves.toEqual(payloads[1]);
    await expect(fetchDashboardFunnel(session)).resolves.toEqual(payloads[2]);
    await expect(fetchDashboardFailures(session)).resolves.toEqual(payloads[3]);
    await expect(fetchDashboardLLMPerformance(session)).resolves.toEqual(payloads[4]);

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/api/internal/dashboard/overview',
      '/api/internal/dashboard/trends?bucket=hour',
      '/api/internal/dashboard/funnel',
      '/api/internal/dashboard/failures',
      '/api/internal/dashboard/llm-performance',
    ]);
  });

  it('uses the dashboard error detail and a stable fallback when decoding fails', async () => {
    fetchMock
      .mockResolvedValueOnce(response({ detail: 'Admin access required' }, { ok: false, status: 403 }))
      .mockResolvedValueOnce(response({}, { ok: false, jsonError: new Error('invalid JSON') }));

    await expect(fetchDashboardOverview(session)).rejects.toThrow('Admin access required');
    await expect(fetchDashboardFunnel(session)).rejects.toThrow('Internal dashboard request failed');
  });
});
