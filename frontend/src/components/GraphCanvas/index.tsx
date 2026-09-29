// ─────────────────────────────────────────────────────────────────────────────
// File: frontend/src/components/GraphCanvas/index.tsx
// Purpose: Graph pane container. Composes D3Graph, NodeDetailPopup, and
//          SequenceBar. Manages which node popup is open.
// ─────────────────────────────────────────────────────────────────────────────

import { useState, useEffect, useLayoutEffect, useMemo, useRef, useImperativeHandle, useCallback } from 'react';
import type { Ref } from 'react';
import type { AuthSession, GraphContentEdit, GraphData, GraphNode, GraphViewState, SelectedNode } from '../../types';
import { useGraph } from '../../hooks/useGraph';
import { graphStructureKey } from '../../utils/graphStructureKey';
import { D3Graph } from './D3Graph';
import { architectureRegions } from './architectureRegions';
import { GlossaryDrawer } from './GlossaryDrawer';
import { NodeDetailPopup } from './NodeDetailPopup';
import { SequenceBar } from './SequenceBar';
import { updateThreadGraph } from '../../services/api';

export interface GraphCanvasHandle {
  flushPendingLayout(): Promise<void>;
}

interface GraphCanvasProps {
  ref?: Ref<GraphCanvasHandle>;
  historyPreview?: boolean;
  layoutLocked?: boolean;
  graphData: GraphData | null;
  animateSequence: boolean;
  authSession: AuthSession | null;
  activeThreadId: string | null;
  onNodeClick: (node: GraphNode) => void;
  onTellMeMore: (node: GraphNode) => void;
  onExpandGraph: (node: GraphNode) => void;
  selectedNode: SelectedNode | null;
  onClosePopup: () => void;
  sourceTexts: string[];
  isPreview?: boolean;
  isAcceptedGraph?: boolean;
  isBuilding?: boolean;
  onGraphReady?: (key: string) => void;
  onSaveGraphEdit?: (edit: GraphContentEdit) => Promise<void>;
  editingDisabled?: boolean;
  onEditDraftChange?: (dirty: boolean) => void;
}

function sameGraphViewState(a: GraphViewState | null | undefined, b: GraphViewState | null | undefined): boolean {
  if (!a || !b) return a === b;
  if (a.layoutVersion !== b.layoutVersion) return false;
  if (a.viewport.x !== b.viewport.x || a.viewport.y !== b.viewport.y || a.viewport.k !== b.viewport.k) {
    return false;
  }
  const aEntries = Object.entries(a.nodePositions);
  const bEntries = Object.entries(b.nodePositions);
  if (aEntries.length !== bEntries.length) return false;
  if (!aEntries.every(([nodeId, pos]) => {
    const other = b.nodePositions[nodeId];
    return !!other && other.x === pos.x && other.y === pos.y;
  })) return false;
  const aPadding = a.zonePadding ?? {};
  const bPadding = b.zonePadding ?? {};
  const aZones = Object.keys(aPadding);
  if (aZones.length !== Object.keys(bPadding).length) return false;
  return aZones.every(zoneId => {
    const left = aPadding[zoneId];
    const right = bPadding[zoneId];
    return !!right && left.top === right.top && left.right === right.right
      && left.bottom === right.bottom && left.left === right.left;
  });
}

export function GraphCanvas({
  ref,
  historyPreview = false,
  layoutLocked = false,
  graphData,
  animateSequence,
  authSession,
  activeThreadId,
  onNodeClick,
  onTellMeMore,
  onExpandGraph,
  selectedNode,
  onClosePopup,
  sourceTexts,
  isPreview = false,
  isAcceptedGraph = !isPreview,
  isBuilding = false,
  onGraphReady,
  onSaveGraphEdit,
  editingDisabled = false,
  onEditDraftChange,
}: GraphCanvasProps) {
  const { currentStep, isAutoPlaying, totalSteps, hasSequence, activeNodeIds, stepDescription, goToStep } = useGraph(graphData, animateSequence);
  const [sequenceDismissal, setSequenceDismissal] = useState<{ key: string; dismissed: boolean } | null>(null);
  const [viewStateCache, setViewStateCache] = useState<Record<string, GraphViewState>>({});
  const [pendingPersistViewState, setPendingPersistViewState] = useState<{
    graphKey: string;
    viewState: GraphViewState;
  } | null>(null);
  const [editTarget, setEditTarget] = useState<{
    nodeId: string;
    focus: 'name' | 'edge';
    edgeIndex?: number;
    requestId: number;
  } | null>(null);
  const editRequestCounterRef = useRef(0);
  const [inspectionRequestId, setInspectionRequestId] = useState(0);
  const [isSavingGraphContent, setIsSavingGraphContent] = useState(false);
  const savingGraphContentRef = useRef(false);
  const editDirtyRef = useRef(false);
  const canvasRef = useRef<HTMLDivElement>(null);
  const inspectorRef = useRef<HTMLDivElement>(null);
  const [inspectionViewport, setInspectionViewport] = useState<{
    nodeId: string;
    width: number;
    height: number;
  }>();
  const layoutWritesRef = useRef<Promise<void>>(Promise.resolve());
  const layoutFlushRef = useRef<{ key: string | null; promise: Promise<void> } | null>(null);
  const latestViewStateRef = useRef<{
    threadId: string;
    graphKey: string;
    viewState: GraphViewState;
  } | null>(null);
  const previousGraphRef = useRef<string | null>(null);
  const persistTimerRef = useRef<ReturnType<typeof window.setTimeout> | null>(null);
  const pendingLayoutRef = useRef<{ graphKey: string; viewState: GraphViewState } | null>(null);
  const [layoutError, setLayoutError] = useState<string | null>(null);
  const graphContentKey = useMemo(() => graphStructureKey(graphData), [graphData]);
  const sequenceDismissed = sequenceDismissal?.key === graphContentKey && sequenceDismissal.dismissed;
  const graphViewKey = useMemo(() => {
    if (!graphData || !activeThreadId) return null;
    return [
      activeThreadId,
      historyPreview ? 'history' : 'live',
      graphData.version ?? '',
      graphData.graph_type,
      graphData.title,
      graphData.nodes.map((node) => `${node.id}:${node.label}:${node.type}:${node.tier ?? ''}:${node.lane ?? ''}`).join('|'),
      graphData.edges.map((edge) => `${edge.source}->${edge.target}:${edge.label}:${edge.sync}:${edge.flow ?? ''}`).join('|'),
      (graphData.groups ?? []).map((group) => `${group.id}:${group.kind ?? ''}:${group.nodeIds.join(',')}`).join('|'),
      graphData.sequence.map((step) => `${step.step}:${step.nodes.join(',')}`).join('|'),
    ].join('::');
  }, [activeThreadId, graphData, historyPreview]);
  const currentGraphRef = useRef(graphViewKey);
  useLayoutEffect(() => {
    currentGraphRef.current = graphViewKey;
    return () => { currentGraphRef.current = null; };
  }, [graphViewKey]);
  const persistedViewState = historyPreview ? graphData?.view_state ?? null
    : graphViewKey ? viewStateCache[graphViewKey] ?? graphData?.view_state ?? null : null;
  const canEdit = Boolean(onSaveGraphEdit && authSession && activeThreadId
    && !historyPreview && !isPreview && !isBuilding && !editingDisabled && !isSavingGraphContent);
  const inspectedNode = historyPreview ? undefined : editTarget
    ? graphData?.nodes.find(node => node.id === editTarget.nodeId)
    : selectedNode && (graphData?.nodes.find(node => node.id === selectedNode.node.id) ?? selectedNode.node);
  const inspectedNodeId = inspectedNode && graphData?.nodes.some(node => node.id === inspectedNode.id)
    ? inspectedNode.id : null;
  const visibleInspectionViewport = inspectionViewport?.nodeId === inspectedNodeId
    ? inspectionViewport : undefined;

  const persistLayout = useCallback((session: AuthSession, threadId: string, data: GraphData, viewState: GraphViewState) => {
    const write = layoutWritesRef.current.catch(() => undefined).then(() =>
      updateThreadGraph(session, threadId, { ...data, view_state: viewState }));
    layoutWritesRef.current = write;
    return write;
  }, []);

  const flushLayout = useCallback(() => {
    const key = graphViewKey;
    if (layoutFlushRef.current?.key === key) return layoutFlushRef.current.promise;
    const run = async () => {
      if (persistTimerRef.current !== null) window.clearTimeout(persistTimerRef.current);
      persistTimerRef.current = null;
      try {
        await layoutWritesRef.current.catch(() => undefined);
        if (currentGraphRef.current !== key) throw new Error('The diagram changed while saving its layout.');
        while (pendingLayoutRef.current?.graphKey === key) {
          if (historyPreview || isPreview || !authSession || !activeThreadId || !graphData) {
            throw new Error('This diagram layout cannot be saved.');
          }
          const pending = pendingLayoutRef.current;
          await persistLayout(authSession, activeThreadId, graphData, pending.viewState);
          if (currentGraphRef.current !== key) throw new Error('The diagram changed while saving its layout.');
          if (pendingLayoutRef.current === pending) pendingLayoutRef.current = null;
        }
        setLayoutError(null);
      } catch (error) {
        if (currentGraphRef.current === key) setLayoutError('Could not save the diagram layout. Retry before continuing.');
        throw error;
      }
    };
    const promise = run().finally(() => {
      if (layoutFlushRef.current?.promise === promise) layoutFlushRef.current = null;
    });
    layoutFlushRef.current = { key, promise };
    return promise;
  }, [graphViewKey, historyPreview, isPreview, authSession, activeThreadId, graphData, persistLayout]);
  useImperativeHandle(ref, () => ({
    async flushPendingLayout() {
      if (editDirtyRef.current || savingGraphContentRef.current) {
        throw new Error('Save or cancel the diagram edit before continuing.');
      }
      await flushLayout();
    },
  }));

  const focusInspector = () => inspectorRef.current?.querySelector<HTMLElement>('input, textarea, select')?.focus();
  const focusCanvasNode = (nodeId: string) => {
    window.requestAnimationFrame(() => {
      const node = Array.from(canvasRef.current?.querySelectorAll<SVGGElement>('g.node') ?? [])
        .find(element => element.getAttribute('data-node-id') === nodeId);
      node?.focus();
    });
  };
  const handleEditDraftChange = (dirty: boolean) => {
    editDirtyRef.current = dirty;
    onEditDraftChange?.(dirty);
  };
  const openNodeEditor = (node: GraphNode) => {
    if (!canEdit) return;
    if (editDirtyRef.current) { focusInspector(); return; }
    onClosePopup();
    setEditTarget({ nodeId: node.id, focus: 'name', requestId: ++editRequestCounterRef.current });
  };
  const openEdgeEditor = (edgeIndex: number) => {
    if (!canEdit || !graphData || edgeIndex < 0 || edgeIndex >= graphData.edges.length) return;
    if (editDirtyRef.current) { focusInspector(); return; }
    onClosePopup();
    setEditTarget({ nodeId: graphData.edges[edgeIndex].source, focus: 'edge', edgeIndex,
      requestId: ++editRequestCounterRef.current });
  };
  const handleNodeClick = (node: GraphNode) => {
    if (historyPreview) return;
    if (editDirtyRef.current) { focusInspector(); return; }
    setEditTarget(null);
    // A fresh inspection resets a pristine editor, including same-node selections.
    setInspectionRequestId(previous => previous + 1);
    onNodeClick(node);
  };
  const closeEditor = () => {
    if (editTarget) {
      const nodeId = editTarget.nodeId;
      setEditTarget(null);
      handleEditDraftChange(false);
      focusCanvasNode(nodeId);
      return;
    }
    onClosePopup();
  };
  const saveGraphEdit = async (edit: GraphContentEdit) => {
    if (!canEdit || !onSaveGraphEdit || !graphData || !authSession || !activeThreadId || !graphViewKey) {
      throw new Error('Editing is unavailable for this diagram.');
    }
    if (savingGraphContentRef.current) throw new Error('A diagram edit is already saving.');
    savingGraphContentRef.current = true;
    setIsSavingGraphContent(true);
    setPendingPersistViewState(null);
    const latest = latestViewStateRef.current;
    const currentViewState = latest?.threadId === activeThreadId && latest.graphKey === graphViewKey
      ? latest.viewState : persistedViewState;
    try {
      if (currentViewState) pendingLayoutRef.current = { graphKey: graphViewKey, viewState: currentViewState };
      await flushLayout();
      await onSaveGraphEdit(edit);
    } finally {
      savingGraphContentRef.current = false;
      setIsSavingGraphContent(false);
    }
  };

  useLayoutEffect(() => {
    if (previousGraphRef.current === graphViewKey) return;
    previousGraphRef.current = graphViewKey;
    setEditTarget(null);
    editDirtyRef.current = false;
    onEditDraftChange?.(false);
    latestViewStateRef.current = null;
    pendingLayoutRef.current = null;
    setLayoutError(null);
    setPendingPersistViewState(null);
  }, [graphViewKey, onEditDraftChange]);

  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    const panel = inspectorRef.current?.querySelector<HTMLElement>('.node-inspector');
    if (!canvas || !panel || !inspectedNodeId) {
      setInspectionViewport(current => current === undefined ? current : undefined);
      return;
    }

    const measure = () => {
      const canvasBox = canvas.getBoundingClientRect();
      const panelBox = panel.getBoundingClientRect();
      if (![canvasBox.left, canvasBox.top, canvasBox.width, canvasBox.height,
        panelBox.left, panelBox.top, panelBox.width, panelBox.height].every(Number.isFinite)
        || canvasBox.width <= 0 || canvasBox.height <= 0 || panelBox.width <= 0 || panelBox.height <= 0) {
        setInspectionViewport(current => current === undefined ? current : undefined);
        return;
      }

      const bottomPanel = panelBox.width >= canvasBox.width - 26;
      const next = {
        nodeId: inspectedNodeId,
        width: bottomPanel ? canvasBox.width
          : Math.min(canvasBox.width, Math.max(0, panelBox.left - canvasBox.left - 12)),
        height: bottomPanel
          ? Math.min(canvasBox.height, Math.max(0, panelBox.top - canvasBox.top - 12))
          : canvasBox.height,
      };
      setInspectionViewport(current => current?.nodeId === next.nodeId
        && current.width === next.width && current.height === next.height ? current : next);
    };

    measure();
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', measure);
      return () => window.removeEventListener('resize', measure);
    }
    const observer = new ResizeObserver(measure);
    observer.observe(canvas);
    observer.observe(panel);
    return () => observer.disconnect();
  }, [activeThreadId, graphContentKey, inspectedNodeId, inspectionRequestId]);

  useEffect(() => {
    if (
      isPreview
      || historyPreview
      || !authSession
      || !activeThreadId
      || !graphData
      || !graphViewKey
      || pendingPersistViewState?.graphKey !== graphViewKey
    ) {
      return;
    }

    const timer = window.setTimeout(() => {
      persistTimerRef.current = null;
      if (savingGraphContentRef.current) return;
      void flushLayout().catch(() => undefined);
    }, 400);
    persistTimerRef.current = timer;

    return () => {
      window.clearTimeout(timer);
    };
  }, [activeThreadId, authSession, graphData, graphViewKey, isPreview, historyPreview, pendingPersistViewState, flushLayout]);

  if (!graphData) {
    return (
      <div style={{
        flex: 1,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#0a0f1a',
        color: '#8b949e',
        fontSize: '0.8rem',
        flexDirection: 'column',
        gap: '1.1rem',
        padding: '2rem',
      }}>
        {!isBuilding && <p role="status">No diagram is available yet.</p>}
      </div>
    );
  }

  const [title, subtitle] = splitGraphTitle(graphData.title);
  const zoneCount = graphData.design_origin === 'applied'
    ? architectureRegions(graphData.nodes, graphData.groups ?? []).length
    : (graphData.groups?.length ?? 0);

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', position: 'relative' }}>
      {/* Graph title */}
      <div style={{
        padding: '0.65rem 1rem',
        fontSize: '0.75rem',
        color: '#6e7681',
        borderBottom: '1px solid #21262d',
        background: 'linear-gradient(180deg, rgba(16,22,34,0.98), rgba(10,15,26,0.98))',
        display: 'flex',
        alignItems: 'center',
        columnGap: '0.65rem',
        rowGap: '0.38rem',
        flexWrap: 'wrap',
        minHeight: 48,
      }}>
        <span style={{ color: '#a78bfa', fontSize: '0.88rem' }}>◈</span>
        <div title={graphData.title} style={{
          flex: '1 1 300px',
          minWidth: 0,
          lineHeight: 1.25,
        }}>
          <div style={{ color: '#d8dee9', fontWeight: 680, overflowWrap: 'anywhere' }}>
            {title}
          </div>
          {subtitle && (
            <div style={{ color: '#8490a0', fontSize: '0.62rem', marginTop: 2, overflowWrap: 'anywhere' }}>
              {subtitle}
            </div>
          )}
          {isAcceptedGraph && graphData.detail_level === 'overview' && (
            <div style={{ display: 'flex', alignItems: 'baseline', flexWrap: 'wrap', gap: '0.3rem', marginTop: 3, fontSize: '0.65rem', lineHeight: 1.35 }}>
              <span style={{ color: '#c4b5fd', fontWeight: 700 }}>Overview</span>
              <span style={{ color: '#aeb8c8' }}>Core workflow. Supporting detail is simplified.</span>
            </div>
          )}
        </div>
        <span style={{
          color: '#8490a0',
          fontSize: '0.62rem',
          padding: '0.18rem 0.45rem',
          borderRadius: 999,
          border: '1px solid rgba(148,163,184,0.16)',
          background: 'rgba(148,163,184,0.06)',
          flexShrink: 0,
          whiteSpace: 'nowrap',
        }}>
          {graphData.nodes.length} components
          {zoneCount > 0 ? ` · ${zoneCount} zones` : ''}
        </span>

        {/* Re-open sequence bar when dismissed */}
        {hasSequence && sequenceDismissed && (
          <button
            onClick={() => setSequenceDismissal({ key: graphContentKey, dismissed: false })}
            title="Show walkthrough steps"
            style={{
              marginLeft: 'auto',
              display: 'flex', alignItems: 'center', gap: '0.3rem',
              background: 'rgba(167,139,250,0.08)',
              border: '1px solid rgba(167,139,250,0.2)',
              borderRadius: '5px',
              color: '#a78bfa',
              fontSize: '0.65rem',
              cursor: 'pointer',
              padding: '2px 7px',
              whiteSpace: 'nowrap',
            }}
          >
            ▶ {totalSteps} steps
          </button>
        )}
      </div>

      {layoutError && <div role="alert" style={{ padding: '8px 16px', color: '#ffc4cb' }}>
        {layoutError} <button type="button" onClick={() => void flushLayout().catch(() => undefined)}>Retry layout save</button>
      </div>}
      {/* D3 canvas */}
      <div ref={canvasRef} className="graph-canvas__surface" style={{ flex: 1, position: 'relative', overflow: 'hidden' }}>
        <div inert={isSavingGraphContent} aria-busy={isSavingGraphContent}
          style={{ width: '100%', height: '100%', opacity: isBuilding ? 0.56 : 1, transition: 'opacity 180ms ease' }}>
          <D3Graph
            key={`${graphViewKey ?? graphContentKey}:${historyPreview}`}
            layoutReadOnly={historyPreview || layoutLocked}
            navigation
            onLayoutReady={onGraphReady}
            graphData={graphData}
            currentStep={currentStep}
            activeNodeIds={activeNodeIds}
            inspectionViewport={visibleInspectionViewport}
            onNodeClick={handleNodeClick}
            onNodeEdit={canEdit ? openNodeEditor : undefined}
            onEditConnection={canEdit ? openEdgeEditor : undefined}
            initialViewState={persistedViewState ?? undefined}
            onViewStateChange={(viewState) => {
              if (isPreview || historyPreview || layoutLocked || !graphViewKey) return;
              if (activeThreadId) latestViewStateRef.current = { threadId: activeThreadId, graphKey: graphViewKey, viewState };
              if (savingGraphContentRef.current) return;
              const existingViewState = viewStateCache[graphViewKey] ?? graphData.view_state ?? null;
              if (sameGraphViewState(existingViewState, viewState)) {
                return;
              }
              setViewStateCache(prev => ({ ...prev, [graphViewKey]: viewState }));
              pendingLayoutRef.current = { graphKey: graphViewKey, viewState };
              setPendingPersistViewState(pendingLayoutRef.current);
            }}
          />
        </div>

        {/* Node detail popup — resolve live node from graphData so enrichment
            updates (node_detail events) are reflected without a re-click */}
        {inspectedNode && (
          <div ref={inspectorRef}>
            <NodeDetailPopup
              key={inspectionRequestId}
              node={inspectedNode}
              nodes={graphData.nodes}
              edges={graphData.edges}
              onClose={closeEditor}
              onTellMeMore={onTellMeMore}
              onExpandGraph={onExpandGraph}
              onSave={canEdit ? saveGraphEdit : undefined}
              editingDisabled={editingDisabled || isSavingGraphContent || isPreview || isBuilding}
              autoFocusName={editTarget?.focus === 'name'}
              autoFocusEdgeIndex={editTarget?.focus === 'edge' ? editTarget.edgeIndex : null}
              editRequestId={editTarget?.requestId}
              onDirtyChange={handleEditDraftChange}
            />
          </div>
        )}

        <div hidden={Boolean(inspectedNode)}>
          <GlossaryDrawer
            graphData={graphData}
            sourceTexts={sourceTexts}
            bottomOffset={hasSequence ? '4.75rem' : '1rem'}
          />
        </div>
      </div>

      {/* Sequence bar (only when there are steps and not dismissed) */}
      {hasSequence && !sequenceDismissed && (
        <SequenceBar
          currentStep={currentStep}
          totalSteps={totalSteps}
          autoPlaying={isAutoPlaying}
          stepDescription={stepDescription}
          onStepChange={goToStep}
          onDismiss={() => {
            goToStep(-1);
            setSequenceDismissal({ key: graphContentKey, dismissed: true });
          }}
        />
      )}
    </div>
  );
}

function splitGraphTitle(value: string): [string, string | null] {
  const separator = value.match(/\s(?:—|–)\s|:\s/);
  if (!separator?.index) return [value, null];
  const title = value.slice(0, separator.index).trim();
  const subtitle = value.slice(separator.index + separator[0].length).trim();
  return title && subtitle ? [title, subtitle] : [value, null];
}
