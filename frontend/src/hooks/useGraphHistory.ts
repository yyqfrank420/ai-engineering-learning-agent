import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { AuthSession, GraphData, GraphHistory, GraphRevision } from '../types';
import { fetchGraphHistory, fetchGraphRevision, restoreGraphRevision } from '../services/api';

interface Options {
  session: AuthSession | null;
  threadId: string | null;
  graph: GraphData | null;
  blocked: boolean;
  flushLayout: () => Promise<void>;
  clearSelection: () => void;
  adoptGraph: (graph: GraphData, threadId: string, expectedVersion: string | null) => boolean;
}

export function useGraphHistory({ session, threadId, graph, blocked, flushLayout, clearSelection, adoptGraph }: Options) {
  const context = `${session?.user.id ?? ''}:${threadId ?? ''}:${graph?.version ?? ''}`;
  const hasGraph = !!graph;
  const [redoPath, setRedoPath] = useState<{ context: string; ids: string[] }>({ context, ids: [] });
  const redoIds = useMemo(() => redoPath.context === context ? redoPath.ids : [], [redoPath, context]);
  const currentSession = useRef(session);
  currentSession.current = session;
  const currentContext = useRef(context);
  currentContext.current = context;
  const operation = useRef(0);
  const inFlight = useRef<number | null>(null);
  const [state, setState] = useState<{
    context: string; history: GraphHistory | null; preview: GraphRevision | null; busy: boolean; error: string | null;
  }>({ context, history: null, preview: null, busy: false, error: null });
  const visible = state.context === context ? state : { history: null, preview: null, busy: false, error: null };
  const reload = useCallback(async () => {
    const activeSession = currentSession.current;
    setRedoPath(previous => previous.context === context ? previous : { context, ids: [] });
    if (!activeSession || !threadId || !hasGraph) return;
    const id = ++operation.current;
    setState({ context, history: null, preview: null, busy: true, error: null });
    try {
      const history = await fetchGraphHistory(activeSession, threadId);
      if (id === operation.current && context === currentContext.current) {
        setState({ context, history, preview: null, busy: false, error: null });
      }
    } catch (error) {
      if (id === operation.current && context === currentContext.current) {
        setState({ context, history: null, preview: null, busy: false, error: error instanceof Error ? error.message : 'Could not load diagram history.' });
      }
    }
  }, [threadId, hasGraph, context]);
  useEffect(() => {
    void reload();
    return () => { operation.current += 1; inFlight.current = null; };
  }, [reload]);

  const changeVersion = useCallback(async (revisionId: string, action: 'preview' | 'restore' | 'undo' | 'redo') => {
    if (blocked || visible.busy || inFlight.current || !session || !threadId || !graph) return;
    const id = ++operation.current;
    const expectedVersion = graph.version ?? null;
    const restore = action !== 'preview';
    const isCurrent = () => id === operation.current && context === currentContext.current;
    inFlight.current = id;
    setState(previous => ({ ...previous, busy: true, error: null }));
    try {
      await flushLayout();
      if (!isCurrent()) return;
      const revision = restore
        ? await restoreGraphRevision(session, threadId, revisionId, expectedVersion)
        : await fetchGraphRevision(session, threadId, revisionId);
      if (!isCurrent()) return;
      if (restore && !adoptGraph(revision.graph_data, threadId, expectedVersion)) {
        throw new Error('The diagram changed. Reload its history before restoring.');
      }
      if (restore) {
        const previousRevision = visible.history?.current_revision_id;
        const ids = action === 'undo' && previousRevision ? [previousRevision, ...redoIds]
          : action === 'redo' ? redoIds.slice(1) : [];
        setRedoPath({ context: `${session.user.id}:${threadId}:${revision.graph_data.version ?? ''}`, ids });
      }
      clearSelection();
      setState(previous => ({ ...previous, preview: restore ? null : revision, busy: false }));
      if (restore && (revision.graph_data.version ?? null) === expectedVersion) void reload();
    } catch (error) {
      if (isCurrent()) setState(previous => ({ ...previous, busy: false, error: error instanceof Error ? error.message : 'Could not change diagram version.' }));
    } finally {
      if (inFlight.current === id) inFlight.current = null;
    }
  }, [blocked, visible.busy, session, threadId, graph, context, flushLayout, adoptGraph, clearSelection, reload, visible.history, redoIds]);

  const returnToCurrent = useCallback(() => {
    if (blocked || inFlight.current) return;
    operation.current += 1;
    clearSelection();
    setState(previous => ({ ...previous, preview: null, error: null, busy: false }));
  }, [blocked, clearSelection]);
  const current = visible.history?.revisions.find(revision => revision.id === visible.history?.current_revision_id);
  const redo = visible.history?.revisions.filter(revision => revision.parent_revision_id === current?.id)
    .sort((a, b) => b.revision_number - a.revision_number)[0];
  return {
    ...visible,
    undoId: current?.parent_revision_id ?? null,
    redoId: redoIds[0] ?? redo?.id ?? null,
    undo: () => { if (current?.parent_revision_id) void changeVersion(current.parent_revision_id, 'undo'); },
    redo: () => { const id = redoIds[0] ?? redo?.id; if (id) void changeVersion(id, 'redo'); },
    previewRevision: (id: string) => void changeVersion(id, 'preview'),
    restoreRevision: (id: string) => void changeVersion(id, 'restore'),
    returnToCurrent,
    reload,
  };
}
