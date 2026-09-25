import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { AuthSession, GraphData } from '../types';
import { GraphEditApiError, saveGraphContentEdit } from './api';

const session: AuthSession = {
  access_token: 'access-token',
  refresh_token: 'refresh-token',
  user: { id: 'user-1', email: 'user@example.com' },
};

const graph: GraphData = {
  graph_type: 'architecture',
  title: 'Edited architecture',
  nodes: [],
  edges: [],
  sequence: [],
  version: 'next-version',
};

describe('graph content edit API', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => vi.unstubAllGlobals());

  it('sends a versioned patch and returns the canonical saved graph', async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ graph_data: graph }) });
    const edit = {
      nodes: [{ id: 'service', label: 'Renamed service' }],
      edges: [{ index: 0, description: 'A revised data flow.' }],
    };

    await expect(saveGraphContentEdit(session, 'thread-1', 'old-version', edit)).resolves.toEqual(graph);
    expect(fetchMock).toHaveBeenCalledWith('/api/threads/thread-1/graph', expect.objectContaining({
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer access-token',
      },
      body: JSON.stringify({ ...edit, expected_version: 'old-version' }),
    }));
    expect(fetchMock.mock.calls[0][1].signal).toBeInstanceOf(AbortSignal);
  });

  it.each([
    [404, 'This conversation no longer exists.'],
    [409, 'The diagram changed. Reload it before saving your edit.'],
    [413, 'The edited diagram is too large to save.'],
    [422, 'The diagram edit contains invalid values.'],
  ])('reports a readable typed error for HTTP %i', async (status, message) => {
    fetchMock.mockResolvedValue({ ok: false, status, json: async () => ({}) });
    await expect(saveGraphContentEdit(session, 'thread-1', null, { nodes: [{ id: 'x', label: 'X' }] }))
      .rejects.toMatchObject({ name: 'GraphEditApiError', status, message });
  });

  it('uses server error detail and rejects malformed success responses', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 409,
      json: async () => ({ detail: 'Generation is still running.' }),
    });
    await expect(saveGraphContentEdit(session, 'thread-1', 'old', {}))
      .rejects.toEqual(new GraphEditApiError('Generation is still running.', 409));

    fetchMock.mockResolvedValueOnce({ ok: true, json: async () => ({ graph_data: null }) });
    await expect(saveGraphContentEdit(session, 'thread-1', 'old', {}))
      .rejects.toThrow('The diagram save returned an invalid graph.');
  });

  it('reports a timeout without retrying the mutating request', async () => {
    fetchMock.mockRejectedValue(new DOMException('expired', 'TimeoutError'));
    await expect(saveGraphContentEdit(session, 'thread-1', 'old', {}))
      .rejects.toThrow('Saving the diagram timed out. Your edit is still open; check the saved diagram before retrying.');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
