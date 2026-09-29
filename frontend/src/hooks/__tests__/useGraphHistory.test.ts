import { useState } from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useGraphHistory } from '../useGraphHistory';
import { fetchGraphHistory, fetchGraphRevision, restoreGraphRevision } from '../../services/api';
import type { AuthSession, GraphData, GraphHistory, GraphRevision } from '../../types';
vi.mock('../../services/api', () => ({ fetchGraphHistory: vi.fn(), fetchGraphRevision: vi.fn(), restoreGraphRevision: vi.fn() }));
const graph: GraphData = { graph_type: 'architecture', title: 'Current', nodes: [], edges: [], sequence: [], version: 'v2' };
const session = { user: { id: 'user' } } as AuthSession;
const history: GraphHistory = { current_revision_id: 'r2', revisions: [
  { id: 'r1', parent_revision_id: null, revision_number: 1, label: 'Original', created_at: '', node_count: 1, edge_count: 0 },
  { id: 'r2', parent_revision_id: 'r1', revision_number: 2, label: 'Current', created_at: '', node_count: 2, edge_count: 1 },
  { id: 'r3', parent_revision_id: 'r2', revision_number: 3, label: 'Child', created_at: '', node_count: 3, edge_count: 2 },
  { id: 'r4', parent_revision_id: 'r2', revision_number: 4, label: 'Newer branch', created_at: '', node_count: 4, edge_count: 3 },
] };
const revision: GraphRevision = { revision_id: 'r1', graph_data: { ...graph, version: 'v1' } };
const options = () => ({ session, threadId: 'thread', graph, blocked: false, flushLayout: vi.fn().mockResolvedValue(undefined), clearSelection: vi.fn(), adoptGraph: vi.fn().mockReturnValue(true) });
describe('useGraphHistory', () => {
  beforeEach(() => { vi.resetAllMocks(); vi.mocked(fetchGraphHistory).mockResolvedValue(history); vi.mocked(fetchGraphRevision).mockResolvedValue(revision); vi.mocked(restoreGraphRevision).mockResolvedValue(revision); });
  it('uses parent links and newest child; previews without adopting canonical state', async () => {
    const props = options(); const { result } = renderHook(() => useGraphHistory(props));
    await waitFor(() => expect(result.current.history).toEqual(history));
    expect(result.current.undoId).toBe('r1'); expect(result.current.redoId).toBe('r4');
    act(() => result.current.previewRevision('r1'));
    await waitFor(() => expect(result.current.preview).toEqual(revision));
    expect(props.flushLayout).toHaveBeenCalledOnce(); expect(props.adoptGraph).not.toHaveBeenCalled();
    act(() => result.current.returnToCurrent()); expect(result.current.preview).toBeNull();
  });
  it('flushes before restore and adopts with thread and expected version', async () => {
    const props = options(); const { result } = renderHook(() => useGraphHistory(props));
    await waitFor(() => expect(result.current.history).toEqual(history));
    act(() => result.current.restoreRevision('r1'));
    await waitFor(() => expect(props.adoptGraph).toHaveBeenCalledWith(revision.graph_data, 'thread', 'v2'));
    expect(props.flushLayout.mock.invocationCallOrder[0]).toBeLessThan(vi.mocked(restoreGraphRevision).mock.invocationCallOrder[0]);
  });
  it('stops before restore when layout save fails', async () => {
    const props = options();props.flushLayout.mockRejectedValue(new Error('Layout save failed'));
    const { result } = renderHook(() => useGraphHistory(props));await waitFor(() => expect(result.current.history).toEqual(history));
    act(() => result.current.restoreRevision('r1'));await waitFor(() => expect(result.current.error).toBe('Layout save failed'));
    expect(restoreGraphRevision).not.toHaveBeenCalled();expect(props.adoptGraph).not.toHaveBeenCalled();
  });
  it('ignores a preview response after changing thread', async () => {
    let resolve!: (revision: GraphRevision) => void;vi.mocked(fetchGraphRevision).mockReturnValue(new Promise(done => {resolve = done}));
    const props = options();const { result, rerender } = renderHook(({threadId}) => useGraphHistory({...props,threadId}), {initialProps:{threadId:'thread'}});
    await waitFor(() => expect(result.current.history).toEqual(history));act(() => result.current.previewRevision('r1'));await waitFor(() => expect(fetchGraphRevision).toHaveBeenCalled());
    rerender({threadId:'other'});await act(async () => resolve(revision));expect(result.current.preview).toBeNull();expect(props.adoptGraph).not.toHaveBeenCalled();
  });
  it('keeps a preview operation alive when flushing updates only layout identity', async () => {
    const props = options();
    const { result } = renderHook(() => {
      const [current, setCurrent] = useState(graph);
      return useGraphHistory({ ...props, graph: current, flushLayout: async () => {
        setCurrent({ ...graph, view_state: { layoutVersion: 1, viewport: { x: 4, y: 5, k: 1 }, nodePositions: {} } });
      } });
    });
    await waitFor(() => expect(result.current.history).toEqual(history));
    act(() => result.current.previewRevision('r1'));
    await waitFor(() => expect(result.current.preview).toEqual(revision));
    expect(fetchGraphHistory).toHaveBeenCalledOnce();
  });
  it('releases an old operation lock on thread change even if its request hangs', async () => {
    vi.mocked(fetchGraphRevision).mockImplementationOnce(() => new Promise(() => {}));
    const props = options();
    const { result, rerender } = renderHook(({threadId}) => useGraphHistory({...props,threadId}), {initialProps:{threadId:'thread'}});
    await waitFor(() => expect(result.current.history).toEqual(history));
    act(() => result.current.previewRevision('r1'));
    await waitFor(() => expect(fetchGraphRevision).toHaveBeenCalledOnce());
    rerender({threadId:'other'});
    await waitFor(() => expect(result.current.busy).toBe(false));
    act(() => result.current.previewRevision('r1'));
    await waitFor(() => expect(result.current.preview).toEqual(revision));
    expect(fetchGraphRevision).toHaveBeenLastCalledWith(session, 'other', 'r1');
  });
  it('redos the branch just undone and clears that path after explicit restore or new content', async () => {
    let active = 'r3';
    let version = 2;
    vi.mocked(fetchGraphHistory).mockImplementation(async () => ({ ...history, current_revision_id: active }));
    vi.mocked(restoreGraphRevision).mockImplementation(async (_session, _thread, id) => {
      active = id;
      return { revision_id: id, graph_data: { ...graph, version: `v${++version}` } };
    });
    const props = options();
    const { result } = renderHook(() => {
      const [current, setCurrent] = useState(graph);
      const controls = useGraphHistory({ ...props, graph: current, adoptGraph: restored => { setCurrent(restored); return true; } });
      return { ...controls, generate: () => { active = 'r2'; setCurrent({ ...graph, version: 'generated' }); } };
    });
    await waitFor(() => expect(result.current.history?.current_revision_id).toBe('r3'));
    act(() => result.current.undo());
    await waitFor(() => expect(result.current.history?.current_revision_id).toBe('r2'));
    expect(result.current.redoId).toBe('r3'); // r4 is the newer sibling, but was not undone.
    act(() => result.current.undo());
    await waitFor(() => expect(result.current.history?.current_revision_id).toBe('r1'));
    act(() => result.current.redo());
    await waitFor(() => expect(result.current.history?.current_revision_id).toBe('r2'));
    expect(result.current.redoId).toBe('r3');
    act(() => result.current.redo());
    await waitFor(() => expect(result.current.history?.current_revision_id).toBe('r3'));
    act(() => result.current.undo());
    await waitFor(() => expect(result.current.redoId).toBe('r3'));
    await waitFor(() => expect(result.current.busy).toBe(false));
    act(() => result.current.restoreRevision('r2'));
    await waitFor(() => expect(result.current.busy).toBe(false));
    expect(result.current.redoId).toBe('r4');
    act(() => result.current.restoreRevision('r3'));
    await waitFor(() => expect(result.current.history?.current_revision_id).toBe('r3'));
    act(() => result.current.undo());
    await waitFor(() => expect(result.current.redoId).toBe('r3'));
    act(() => result.current.generate());
    await waitFor(() => expect(result.current.history?.current_revision_id).toBe('r2'));
    expect(result.current.redoId).toBe('r4');
  });
  it('surfaces history failures and retries', async () => {
    vi.mocked(fetchGraphHistory).mockRejectedValueOnce(new Error('History unavailable'));
    const props = options();const {result}=renderHook(()=>useGraphHistory(props));await waitFor(()=>expect(result.current.error).toBe('History unavailable'));
    await act(async()=>result.current.reload());expect(result.current.history).toEqual(history);expect(result.current.error).toBeNull();
  });
});
