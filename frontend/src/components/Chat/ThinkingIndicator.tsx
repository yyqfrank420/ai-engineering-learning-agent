import type { WorkerStatus, WorkflowProgress } from '../../types';
import { WorkflowActivity } from '../WorkflowActivity';

interface ThinkingIndicatorProps {
  workerStatus: WorkerStatus;
  workflowProgress?: WorkflowProgress[];
  isGenerating?: boolean;
  explanationPaused?: boolean;
  onTogglePause?: () => void;
}

export function ThinkingIndicator({
  workerStatus,
  workflowProgress = [],
  isGenerating = false,
  explanationPaused = false,
  onTogglePause,
}: ThinkingIndicatorProps) {
  if (!isGenerating && !explanationPaused) {
    if (workflowProgress.length === 0) return null;
    return <details style={{ padding: '8px 16px', color: '#94a3b8', fontSize: 12 }}>
      <summary style={{ cursor: 'pointer' }}>View activity</summary>
      <WorkflowActivity progress={workflowProgress} limit={8} />
    </details>;
  }

  return (
    <div style={{ padding: '8px 16px', color: '#94a3b8', fontSize: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <span role="status">{explanationPaused ? 'Paused' : 'Working…'}</span>
        {onTogglePause && <button type="button" onClick={onTogglePause}
          aria-label={explanationPaused ? 'Resume reveal' : 'Pause reveal'}
          title={explanationPaused ? 'Resume reveal' : 'Pause reveal'}
          style={{ background: 'none', border: 0, color: 'inherit', cursor: 'pointer', padding: 4 }}>
          {explanationPaused ? 'Resume' : <svg aria-hidden="true" width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><rect x="4" y="3" width="3" height="10" rx="1" /><rect x="9" y="3" width="3" height="10" rx="1" /></svg>}
        </button>}
      </div>
      <WorkflowActivity progress={workflowProgress} />
      <details style={{ marginTop: 4 }}>
        <summary style={{ cursor: 'pointer', fontSize: 11 }}>Details</summary>
        <ul style={{ paddingLeft: 16, lineHeight: 1.5 }}>
          {workflowProgress.map(item => <li key={item.phase}>{item.title}: {item.detail}</li>)}
          {Object.entries(workerStatus).filter(([, status]) => status !== null).map(([worker, status]) => (
            <li key={worker}>{status}</li>
          ))}
        </ul>
      </details>
    </div>
  );
}
