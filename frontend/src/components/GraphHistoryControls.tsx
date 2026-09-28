import type { GraphHistory } from '../types';
import './GraphHistoryControls.css';

interface Props {
  history: GraphHistory | null;
  previewId: string | null;
  undoId: string | null;
  redoId: string | null;
  disabled: boolean;
  busy: boolean;
  error: string | null;
  onUndo: () => void;
  onRedo: () => void;
  onPreview: (id: string) => void;
  onRestore: (id: string) => void;
  onReturn: () => void;
  onReload: () => void;
}

export function GraphHistoryControls({ history, previewId, undoId, redoId, disabled, busy, error, onUndo, onRedo, onPreview, onRestore, onReturn, onReload }: Props) {
  const locked = disabled || busy;
  return <div className="graph-history">
    <div className="graph-history-toolbar" role="group" aria-label="Diagram history">
      <button aria-label="Undo diagram change" title="Undo diagram change" disabled={locked || !undoId} onClick={onUndo}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 5-5 5 5 5M4 10h9a6 6 0 0 1 6 6v3" /></svg>
      </button>
      <button aria-label="Redo diagram change" title="Redo diagram change" disabled={locked || !redoId} onClick={onRedo}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 5 5 5-5 5m5-5h-9a6 6 0 0 0-6 6v3" /></svg>
      </button>
      <select aria-label="Preview diagram version" disabled={locked || !history?.revisions.length} value={previewId ?? history?.current_revision_id ?? ''} onChange={event => event.target.value === history?.current_revision_id ? onReturn() : onPreview(event.target.value)}>
        {!history?.revisions.length && <option value="">{busy ? 'Loading history…' : 'Diagram history'}</option>}
        {history?.revisions.map(revision => <option key={revision.id} value={revision.id}>{revision.revision_number} · {revision.label}{revision.id === history.current_revision_id ? ' (current)' : ''}</option>)}
      </select>
      {busy && <span role="status">Updating history…</span>}
    </div>
    {previewId && <div className="graph-history-preview" role="status">
      <span>Preview only · Saved positions</span>
      <button disabled={locked} onClick={onReturn}>Return to current</button>
      <button disabled={locked} onClick={() => onRestore(previewId)}>Restore this version</button>
    </div>}
    {error && <div className="graph-history-error" role="alert"><span>{error}</span><button disabled={locked} onClick={onReload}>Reload history</button></div>}
  </div>;
}
