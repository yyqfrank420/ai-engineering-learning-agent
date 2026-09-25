import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import type { GraphContentEdit, GraphEdge, GraphNode, NodeType } from '../../types';
import { TYPE_STYLE } from '../../utils/graphColors';
import './NodeDetailPopup.css';

const NODE_TYPES: NodeType[] = [
  'client', 'service', 'datastore', 'queue', 'gateway',
  'network', 'external', 'control', 'decision',
];
const NODE_TYPE_LABELS: Record<NodeType, string> = {
  client: 'Client',
  service: 'Application service',
  datastore: 'Data store',
  queue: 'Queue',
  gateway: 'Gateway',
  network: 'Network',
  external: 'External system',
  control: 'Control',
  decision: 'Decision',
};
const EDGE_FLOWS: Array<NonNullable<GraphEdge['flow']>> = [
  'runtime', 'control', 'feedback', 'deployment',
];
const EDGE_FLOW_LABELS: Record<NonNullable<GraphEdge['flow']>, string> = {
  runtime: 'Runtime flow',
  control: 'Control flow',
  feedback: 'Feedback path',
  deployment: 'Deployment path',
};

type NodeFields = Pick<GraphNode, 'label' | 'type' | 'technology' | 'description'>;
type EdgeFields = Pick<GraphEdge, 'label' | 'technology' | 'description' | 'sync'> & {
  flow: NonNullable<GraphEdge['flow']>;
};
type Draft = { node: NodeFields; edges: Record<number, EdgeFields> };
type InvalidField = { field: 'name' | 'node-description' | 'edge-label' | 'edge-description'; edgeIndex?: number };

interface NodeDetailPopupProps {
  node: GraphNode;
  edges: GraphEdge[];
  onClose: () => void;
  onTellMeMore: (node: GraphNode) => void;
  onExpandGraph: (node: GraphNode) => void;
  onSave?: (edit: GraphContentEdit) => Promise<void>;
  onDirtyChange?: (dirty: boolean) => void;
  editingDisabled?: boolean;
  autoFocusName?: boolean;
  autoFocusEdgeIndex?: number | null;
  editRequestId?: number;
}

function incidentEdges(nodeId: string, edges: GraphEdge[]) {
  return edges.flatMap((edge, index) =>
    edge.source === nodeId || edge.target === nodeId ? [{ edge, index }] : [],
  );
}

function makeDraft(node: GraphNode, edges: GraphEdge[]): Draft {
  return {
    node: {
      label: node.label,
      type: node.type,
      technology: node.technology,
      description: node.description,
    },
    edges: Object.fromEntries(incidentEdges(node.id, edges).map(({ edge, index }) => [index, {
      label: edge.label,
      technology: edge.technology,
      description: edge.description,
      flow: edge.flow ?? (edge.type === 'loop' ? 'feedback' : 'runtime'),
      sync: edge.sync,
    }])),
  };
}

function editFromDraft(nodeId: string, before: Draft, after: Draft): GraphContentEdit {
  const nodeEdit: NonNullable<GraphContentEdit['nodes']>[number] = { id: nodeId };
  if (before.node.label !== after.node.label.trim()) nodeEdit.label = after.node.label.trim();
  if (before.node.type !== after.node.type) nodeEdit.type = after.node.type;
  if (before.node.technology !== after.node.technology.trim()) nodeEdit.technology = after.node.technology.trim();
  if (before.node.description !== after.node.description.trim()) nodeEdit.description = after.node.description.trim();

  const edgeEdits: NonNullable<GraphContentEdit['edges']> = [];
  for (const [indexText, current] of Object.entries(after.edges)) {
    const index = Number(indexText);
    const original = before.edges[index];
    if (!original) continue;
    const edgeEdit: NonNullable<GraphContentEdit['edges']>[number] = { index };
    if (original.label !== current.label.trim()) edgeEdit.label = current.label.trim();
    if (original.technology !== current.technology.trim()) edgeEdit.technology = current.technology.trim();
    if (original.description !== current.description.trim()) edgeEdit.description = current.description.trim();
    if (original.flow !== current.flow) edgeEdit.flow = current.flow;
    if (original.sync !== current.sync) edgeEdit.sync = current.sync;
    if (Object.keys(edgeEdit).length > 1) edgeEdits.push(edgeEdit);
  }

  return {
    ...(Object.keys(nodeEdit).length > 1 ? { nodes: [nodeEdit] } : {}),
    ...(edgeEdits.length ? { edges: edgeEdits } : {}),
  };
}

export function NodeDetailPopup({
  node,
  edges,
  onClose,
  onTellMeMore,
  onExpandGraph,
  onSave,
  onDirtyChange,
  editingDisabled = false,
  autoFocusName = false,
  autoFocusEdgeIndex = null,
  editRequestId,
}: NodeDetailPopupProps) {
  const [editing, setEditing] = useState(Boolean(onSave) && (autoFocusName || autoFocusEdgeIndex !== null));
  const [selection, setSelection] = useState({ node, edges });
  const [baseline, setBaseline] = useState(() => makeDraft(node, edges));
  const [draft, setDraft] = useState(() => makeDraft(node, edges));
  const [expandedEdge, setExpandedEdge] = useState<number | null>(autoFocusEdgeIndex);
  const [showDiscard, setShowDiscard] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [invalidField, setInvalidField] = useState<InvalidField | null>(null);
  const [saved, setSaved] = useState(false);
  const panelRef = useRef<HTMLElement>(null);
  const editButtonRef = useRef<HTMLButtonElement>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const nodeDescriptionRef = useRef<HTMLTextAreaElement>(null);
  const edgeLabelRef = useRef<HTMLInputElement>(null);
  const edgeDescriptionRef = useRef<HTMLTextAreaElement>(null);
  const savingRef = useRef(false);
  const wasEditingRef = useRef(editing);
  const previousFocusName = useRef(autoFocusName);
  const previousFocusEdge = useRef(autoFocusEdgeIndex);
  const previousEditRequestId = useRef(editRequestId);
  const onDirtyChangeRef = useRef(onDirtyChange);
  const edit = editFromDraft(selection.node.id, baseline, draft);
  const dirty = Boolean(edit.nodes?.length || edit.edges?.length);
  const shownNode = dirty && node.id !== selection.node.id ? selection.node : node;
  const shownEdges = dirty && node.id !== selection.node.id ? selection.edges : edges;
  const connections = incidentEdges(shownNode.id, shownEdges);
  const canEdit = Boolean(onSave) && !editingDisabled;
  const showExpandGraph = shownNode.type !== 'decision';

  useEffect(() => { onDirtyChangeRef.current = onDirtyChange; }, [onDirtyChange]);
  useEffect(() => { onDirtyChange?.(dirty); }, [dirty, onDirtyChange]);
  useEffect(() => () => { onDirtyChangeRef.current?.(false); }, []);

  useEffect(() => {
    if (dirty || saving) return;
    const nextDraft = makeDraft(node, edges);
    const nodeChanged = selection.node.id !== node.id;
    if (!nodeChanged && JSON.stringify(nextDraft) === JSON.stringify(baseline)) return;
    setSelection({ node, edges });
    setBaseline(nextDraft);
    setDraft(nextDraft);
    if (nodeChanged) {
      setEditing(Boolean(onSave) && (autoFocusName || autoFocusEdgeIndex !== null));
      setExpandedEdge(autoFocusEdgeIndex);
      setShowDiscard(false);
      setError(null);
      setInvalidField(null);
      setSaved(false);
    }
  }, [node, edges, selection.node.id, baseline, dirty, saving, autoFocusName, autoFocusEdgeIndex, onSave]);

  useEffect(() => {
    const requested = editRequestId === undefined
      ? (autoFocusName && !previousFocusName.current)
        || (autoFocusEdgeIndex !== null && autoFocusEdgeIndex !== previousFocusEdge.current)
      : editRequestId !== previousEditRequestId.current;
    if (requested && canEdit) {
      if (!dirty) {
        const nextDraft = makeDraft(node, edges);
        setSelection({ node, edges });
        setBaseline(nextDraft);
        setDraft(nextDraft);
      }
      if (autoFocusEdgeIndex === null || autoFocusEdgeIndex in (dirty ? draft.edges : makeDraft(node, edges).edges)) {
        setEditing(true);
        setExpandedEdge(autoFocusEdgeIndex);
      }
    }
    previousFocusName.current = autoFocusName;
    previousFocusEdge.current = autoFocusEdgeIndex;
    previousEditRequestId.current = editRequestId;
  }, [editRequestId, autoFocusName, autoFocusEdgeIndex, canEdit, dirty, draft.edges, node, edges]);

  useEffect(() => {
    if (!editing) return;
    if (expandedEdge !== null) edgeLabelRef.current?.focus();
    else nameRef.current?.focus();
  }, [editing, expandedEdge]);

  useEffect(() => {
    if (invalidField?.field === 'node-description') nodeDescriptionRef.current?.focus();
    if (invalidField?.field === 'edge-description') edgeDescriptionRef.current?.focus();
  }, [invalidField, expandedEdge]);

  useEffect(() => {
    if (wasEditingRef.current && !editing) {
      (editButtonRef.current ?? panelRef.current)?.focus();
    }
    wasEditingRef.current = editing;
  }, [editing]);

  const beginEditing = () => {
    if (!canEdit) return;
    const nextDraft = makeDraft(node, edges);
    setSelection({ node, edges });
    setBaseline(nextDraft);
    setDraft(nextDraft);
    setExpandedEdge(null);
    setError(null);
    setInvalidField(null);
    setSaved(false);
    setEditing(true);
  };

  const cancelEditing = () => {
    if (saving) return;
    const nextDraft = makeDraft(shownNode, shownEdges);
    setBaseline(nextDraft);
    setDraft(nextDraft);
    setEditing(false);
    setExpandedEdge(null);
    setShowDiscard(false);
    setError(null);
    setInvalidField(null);
  };

  const requestClose = () => {
    if (saving) return;
    if (dirty) {
      setShowDiscard(true);
      return;
    }
    onClose();
  };

  const updateNode = <K extends keyof NodeFields>(field: K, value: NodeFields[K]) => {
    setDraft(previous => ({ ...previous, node: { ...previous.node, [field]: value } }));
    setError(null);
    setInvalidField(null);
    setSaved(false);
  };

  const updateEdge = <K extends keyof EdgeFields>(index: number, field: K, value: EdgeFields[K]) => {
    setDraft(previous => ({
      ...previous,
      edges: { ...previous.edges, [index]: { ...previous.edges[index], [field]: value } },
    }));
    setError(null);
    setInvalidField(null);
    setSaved(false);
  };

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!onSave || !dirty || savingRef.current || editingDisabled) return;
    if (!draft.node.label.trim()) {
      setInvalidField({ field: 'name' });
      nameRef.current?.focus();
      return;
    }
    const blankEdgeLabel = Object.entries(draft.edges).find(([, edge]) => !edge.label.trim());
    if (blankEdgeLabel) {
      const edgeIndex = Number(blankEdgeLabel[0]);
      setExpandedEdge(edgeIndex);
      setInvalidField({ field: 'edge-label', edgeIndex });
      return;
    }
    if (edit.nodes?.some(change => change.description === '')) {
      setInvalidField({ field: 'node-description' });
      return;
    }
    const blankEdgeDescription = edit.edges?.find(change => change.description === '');
    if (blankEdgeDescription) {
      setExpandedEdge(blankEdgeDescription.index);
      setInvalidField({ field: 'edge-description', edgeIndex: blankEdgeDescription.index });
      return;
    }
    savingRef.current = true;
    setSaving(true);
    setError(null);
    setInvalidField(null);
    try {
      await onSave(edit);
      setBaseline(draft);
      setEditing(false);
      setExpandedEdge(null);
      setSaved(true);
    } catch (cause) {
      setError(cause instanceof Error && cause.message ? cause.message : 'Changes could not be saved. Try again.');
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  };

  const sourceDetail = <>
    {shownNode.detail && <section className="node-inspector__source-detail" aria-label="Source detail">{shownNode.detail}</section>}
    {shownNode.book_refs && shownNode.book_refs.length > 0 && <section className="node-inspector__references" aria-label="Book references">
      <h3>Book refs</h3>
      <div>{shownNode.book_refs.map((ref, index) => <span key={`${ref}:${index}`}>{ref}</span>)}</div>
    </section>}
  </>;

  return <section ref={panelRef} tabIndex={-1} className="node-inspector" aria-label="Node details"
    style={{ borderTopColor: TYPE_STYLE[shownNode.type]?.badge ?? '#6b7280' }}>
    <header className="node-inspector__header">
      <div className="node-inspector__identity">
        <div className="node-inspector__badges">
          <span className="node-inspector__type" style={{ color: TYPE_STYLE[shownNode.type]?.badge ?? '#8b949e' }}>
            {shownNode.type.toUpperCase()}
          </span>
          {shownNode.tier && shownNode.design_origin !== 'applied' && <span className="node-inspector__tier">{shownNode.tier.toUpperCase()}</span>}
        </div>
        <h2>{shownNode.label}</h2>
        {!editing && shownNode.technology && <p className="node-inspector__subtitle">{shownNode.technology}</p>}
      </div>
      <button type="button" className="node-inspector__icon-button" onClick={requestClose}
        aria-label="Close node detail" disabled={saving}>
        <svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><path d="m4 4 8 8M12 4l-8 8" /></svg>
      </button>
    </header>

    {showDiscard && <div className="node-inspector__discard" role="alert">
      <p>Discard unsaved changes?</p>
      <div className="node-inspector__actions">
        <button type="button" onClick={() => setShowDiscard(false)}>Keep editing</button>
        <button type="button" onClick={() => { cancelEditing(); onClose(); }}>Discard and close</button>
      </div>
    </div>}

    {!editing ? <div className="node-inspector__body">
      {shownNode.description && <p className="node-inspector__description">{shownNode.description}</p>}
      {canEdit && <button ref={editButtonRef} type="button" className="node-inspector__edit-button" onClick={beginEditing}>Edit details</button>}
      {saved && <p className="node-inspector__status" role="status">Changes saved</p>}
      {sourceDetail}
      <div className="node-inspector__learning-actions">
        <button type="button" onClick={() => onTellMeMore(shownNode)}>Tell me more</button>
        {showExpandGraph && <button type="button" onClick={() => onExpandGraph(shownNode)}>Expand graph</button>}
      </div>
      <p className="node-inspector__hint">{showExpandGraph
        ? 'Ask the chat to explain this part or expand the nearby graph structure.'
        : 'Ask the chat to explain this constraint more clearly.'}</p>
      {connections.length > 0 && <section className="node-inspector__connections" aria-label="Connections">
        <h3>Connections</h3>
        {connections.map(({ edge, index }) => <div className="node-inspector__connection-summary" key={index}>
          <span aria-hidden="true">{edge.source === shownNode.id ? '→' : '←'}</span>
          <span>{edge.label}</span>
          {edge.technology && <small>{edge.technology}</small>}
          {edge.sync === 'async' && <small>ASYNC</small>}
        </div>)}
      </section>}
    </div> : <form className="node-inspector__form" onSubmit={save}>
      <label>Name<input ref={nameRef} aria-label="Name" value={draft.node.label} maxLength={60}
        aria-invalid={invalidField?.field === 'name'} disabled={saving || editingDisabled}
        onChange={event => updateNode('label', event.target.value)} />
        {invalidField?.field === 'name' && <span className="node-inspector__field-error" role="alert">Name is required.</span>}
      </label>
      <div className="node-inspector__form-row">
        <label>Type<select value={draft.node.type} disabled={saving || editingDisabled}
          onChange={event => updateNode('type', event.target.value as NodeType)}>
          {NODE_TYPES.map(type => <option key={type} value={type}>{NODE_TYPE_LABELS[type]}</option>)}
        </select></label>
        <label>Technology<input value={draft.node.technology} maxLength={100}
          disabled={saving || editingDisabled} onChange={event => updateNode('technology', event.target.value)} /></label>
      </div>
      <label>Description<textarea ref={nodeDescriptionRef} aria-label="Description" value={draft.node.description} maxLength={220} rows={3}
        aria-invalid={invalidField?.field === 'node-description'} disabled={saving || editingDisabled}
        onChange={event => updateNode('description', event.target.value)} />
        {invalidField?.field === 'node-description' && <span className="node-inspector__field-error" role="alert">Description is required.</span>}
      </label>
      {sourceDetail}
      {connections.length > 0 && <section className="node-inspector__connections" aria-label="Connections">
        <h3>Connections</h3>
        {connections.map(({ edge, index }) => {
          const current = draft.edges[index];
          if (!current) return null;
          const open = expandedEdge === index;
          return <div className="node-inspector__connection-editor" key={index}>
            <button type="button" className="node-inspector__connection-toggle" aria-expanded={open}
              aria-controls={`node-connection-${index}`}
              aria-label={`${edge.source === shownNode.id ? 'Outgoing' : 'Incoming'} connection: ${current.label}`}
              onClick={() => setExpandedEdge(open ? null : index)}>
              <span className="node-inspector__connection-direction">{edge.source === shownNode.id ? 'Outgoing' : 'Incoming'}</span>
              <span className="node-inspector__connection-name">{current.label || 'Untitled connection'}</span>
              <span aria-hidden="true">{open ? '−' : '+'}</span>
            </button>
            {open && <div id={`node-connection-${index}`} className="node-inspector__connection-fields">
              <label>Label<input ref={edgeLabelRef} aria-label="Label" value={current.label} maxLength={100}
                aria-invalid={invalidField?.field === 'edge-label' && invalidField.edgeIndex === index}
                disabled={saving || editingDisabled} onChange={event => updateEdge(index, 'label', event.target.value)} />
                {invalidField?.field === 'edge-label' && invalidField.edgeIndex === index && <span className="node-inspector__field-error" role="alert">Connection label is required.</span>}
              </label>
              <label>Technology<input value={current.technology} maxLength={100}
                disabled={saving || editingDisabled} onChange={event => updateEdge(index, 'technology', event.target.value)} /></label>
              <label>Description<textarea ref={edgeDescriptionRef} aria-label="Description" value={current.description} maxLength={220} rows={2}
                aria-invalid={invalidField?.field === 'edge-description' && invalidField.edgeIndex === index}
                disabled={saving || editingDisabled} onChange={event => updateEdge(index, 'description', event.target.value)} />
                {invalidField?.field === 'edge-description' && invalidField.edgeIndex === index && <span className="node-inspector__field-error" role="alert">Connection description is required.</span>}
              </label>
              <div className="node-inspector__form-row">
                <label>Flow<select value={current.flow} disabled={saving || editingDisabled}
                  onChange={event => updateEdge(index, 'flow', event.target.value as EdgeFields['flow'])}>
                  {EDGE_FLOWS.map(flow => <option key={flow} value={flow}>{EDGE_FLOW_LABELS[flow]}</option>)}
                </select></label>
                <label>Timing<select value={current.sync} disabled={saving || editingDisabled}
                  onChange={event => updateEdge(index, 'sync', event.target.value as GraphEdge['sync'])}>
                  <option value="sync">Synchronous</option><option value="async">Asynchronous</option>
                </select></label>
              </div>
            </div>}
          </div>;
        })}
      </section>}
      {error && <p className="node-inspector__error" role="alert">{error}</p>}
      <div className="node-inspector__learning-actions">
        <button type="button" disabled={dirty || saving} onClick={() => onTellMeMore(shownNode)}>Tell me more</button>
        {showExpandGraph && <button type="button" disabled={dirty || saving} onClick={() => onExpandGraph(shownNode)}>Expand graph</button>}
      </div>
      {dirty ? <div className="node-inspector__save-actions">
        <button type="button" onClick={cancelEditing} disabled={saving}>Cancel</button>
        <button type="submit" className="node-inspector__save" disabled={saving || editingDisabled}>
          {saving ? 'Saving…' : 'Save changes'}
        </button>
      </div> : <button type="button" className="node-inspector__done" onClick={cancelEditing}>Done</button>}
    </form>}
  </section>;
}
