import type { WorkerStatus, WorkflowProgress } from '../../types';
import { WorkflowActivity } from '../WorkflowActivity';

interface ThinkingIndicatorProps {
  workerStatus: WorkerStatus;
  workflowProgress?: WorkflowProgress[];
  isGenerating?: boolean;
}

export function ThinkingIndicator({
  workerStatus,
  workflowProgress = [],
  isGenerating = false,
}: ThinkingIndicatorProps) {
  if (!isGenerating) {
    if (workflowProgress.length === 0) return null;
    return <details style={{ padding: '8px 16px', color: '#94a3b8', fontSize: 12 }}>
      <summary style={{ cursor: 'pointer' }}>View activity</summary>
      <WorkflowActivity progress={workflowProgress} limit={8} />
    </details>;
  }

  return (
    <div role="status" aria-live="polite" aria-atomic="false"
      style={{ padding: '8px 16px', color: '#94a3b8', fontSize: 12 }}>
      <span>Working…</span>
      <WorkflowActivity progress={workflowProgress} workerStatus={workerStatus} />
    </div>
  );
}
