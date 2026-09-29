import type { ThinkingProgress, WorkflowProgress } from '../../types';
import './ThinkingIndicator.css';

interface ThinkingIndicatorProps {
  workflowProgress?: WorkflowProgress[];
  thinkingProgress?: readonly ThinkingProgress[];
  isGenerating?: boolean;
  isFinishingDiagram?: boolean;
}

const phaseLabels: Record<string, [active: string, complete: string]> = {
  context: ['Understanding the request…', 'Request understood'],
  book: ['Searching the book…', 'Book search finished'],
  web: ['Searching the web…', 'Web search finished'],
  evidence: ['Reading sources…', 'Sources reviewed'],
  architect: ['Planning the diagram…', 'Diagram planned'],
  challenger: ['Checking design assumptions…', 'Design assumptions checked'],
  components: ['Building components…', 'Components prepared'],
  connections: ['Connecting components…', 'Connections prepared'],
  integrate: ['Combining the diagram…', 'Diagram combined'],
  render: ['Checking diagram layout…', 'Layout checked'],
  review: ['Reviewing the diagram…', 'Diagram checked'],
  revise: ['Refining the diagram…', 'Diagram refined'],
  explain: ['Writing the answer…', 'Answer prepared'],
  synthesis: ['Writing the answer…', 'Answer prepared'],
};

const thinkingLabels: Record<string, string> = {
  components: 'Components', connections: 'Connections', review: 'Review',
  explain: 'Answer', synthesis: 'Answer', architect: 'Diagram plan',
  challenger: 'Design review', revise: 'Revision', context: 'Request',
};

export function ThinkingIndicator({
  workflowProgress = [],
  thinkingProgress = [],
  isGenerating = false,
  isFinishingDiagram = false,
}: ThinkingIndicatorProps) {
  if (!isGenerating) return null;

  const active = workflowProgress.filter(item => item.status === 'active' || item.status === 'retry');
  const latestComplete = [...workflowProgress].reverse().find(item => item.status === 'complete' && phaseLabels[item.phase]);
  const activeLabels = [...new Set(active.map(item => phaseLabels[item.phase]?.[0] ?? 'Working…'))];
  const waitingLabel = isFinishingDiagram ? 'Finishing…'
    : latestComplete?.phase === 'explain' || latestComplete?.phase === 'synthesis' ? 'Preparing answer…'
      : 'Working…';

  const thoughts = thinkingProgress.filter(item => item.content.trim());
  const latestExcerpt = thoughts.at(-1)?.content.replace(/\s+/g, ' ').trim().slice(-140) ?? '';

  return (
    <div className="thinking-indicator">
    <div role="status" aria-live="polite" aria-atomic="false"
      className="thinking-activity">
      {latestComplete && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <svg aria-hidden="true" width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="m3 8 3 3 7-7" /></svg>
          <span>{phaseLabels[latestComplete.phase][1]}</span>
        </div>
      )}
      {(activeLabels.length ? activeLabels : [waitingLabel]).map(label => (
        <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span aria-hidden="true" style={{ width: 6, height: 6, margin: 3, borderRadius: '50%', background: '#a78bfa', flexShrink: 0 }} />
          <span>{label}</span>
        </div>
      ))}
    </div>
    {thoughts.length > 0 && <details className="thinking-feed" open>
      <summary aria-label="Thinking"><span>Thinking</span><span className="thinking-excerpt" aria-hidden="true">{latestExcerpt}</span></summary>
      <div className="thinking-transcript" tabIndex={0} role="region" aria-label="Thinking trace">
        {thoughts.map(item => <section key={item.operationId}>
          <h3>{thinkingLabels[item.phase] ?? 'Thinking'}</h3>
          <p>{item.content}</p>
        </section>)}
      </div>
    </details>}
    </div>
  );
}
