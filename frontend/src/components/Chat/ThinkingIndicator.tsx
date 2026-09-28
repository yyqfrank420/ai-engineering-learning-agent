import type { WorkflowProgress } from '../../types';

interface ThinkingIndicatorProps {
  workflowProgress?: WorkflowProgress[];
  isGenerating?: boolean;
}

const phaseLabels: Record<WorkflowProgress['phase'], string> = {
  evidence: 'Reading sources…',
  architect: 'Building diagram…',
  challenger: 'Checking diagram…',
  integrate: 'Building diagram…',
  render: 'Building diagram…',
  review: 'Checking diagram…',
  revise: 'Refining diagram…',
  explain: 'Writing answer…',
};

export function ThinkingIndicator({
  workflowProgress = [],
  isGenerating = false,
}: ThinkingIndicatorProps) {
  if (!isGenerating) return null;

  const latest = workflowProgress.at(-1);
  const label = latest?.status === 'active' || latest?.status === 'retry'
    ? phaseLabels[latest.phase] ?? 'Working…'
    : latest?.phase === 'explain' && latest.status === 'complete'
      ? 'Preparing answer…'
      : 'Working…';

  return (
    <div role="status" aria-live="polite" aria-atomic="true"
      style={{ padding: '8px 16px', color: '#94a3b8', fontSize: 12 }}>
      {label}
    </div>
  );
}
