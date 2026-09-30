import { useEffect, useState } from 'react';
import type { LiveActivity, MessageActivity } from '../../types';
import './ThinkingIndicator.css';

interface ThinkingIndicatorProps {
  activity: MessageActivity;
  liveActivity?: LiveActivity;
}

function formatDuration(milliseconds: number): string {
  const seconds = Math.floor(Math.max(0, milliseconds) / 1000);
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

export function ThinkingIndicator({ activity, liveActivity }: ThinkingIndicatorProps) {
  const [now, setNow] = useState(() => Date.now());
  const liveRequestId = liveActivity?.clientRequestId;
  useEffect(() => {
    if (!liveRequestId) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [liveRequestId]);
  const duration = liveActivity
    ? Math.max(activity.duration_ms, now - liveActivity.startedAt) : activity.duration_ms;
  const visibleSteps = activity.steps.filter((step, index, steps) => {
    const next = steps[index + 1];
    return !(step.kind === 'tool' && step.status === 'active'
      && next?.kind === 'tool' && next.status === 'complete' && next.phase === step.phase);
  });
  const latest = visibleSteps.at(-1);
  return (
    <>
    <details className="thinking-indicator" open={Boolean(liveActivity)}>
      <summary className="thinking-summary">
        <span>{liveActivity ? 'Working for' : 'Worked for'} {formatDuration(duration)}</span>
        <svg aria-hidden="true" viewBox="0 0 16 16" fill="none"><path d="m5 6 3 3 3-3" /></svg>
      </summary>
      <div className="thinking-steps" role="region" aria-label="Work activity">
        {visibleSteps.map(step => step.kind === 'update'
          ? <p key={step.sequence} className="thinking-update">{step.text}</p>
          : <div key={step.sequence} className="thinking-tool" data-status={step.status}>
              <svg aria-hidden="true" viewBox="0 0 16 16" fill="none">
                {step.status === 'complete'
                  ? <path d="m3 8 3 3 7-7" />
                  : <><circle cx="7" cy="7" r="4" /><path d="m10 10 3 3" /></>}
              </svg>
              <span>{step.text}</span>
            </div>)}
      </div>
    </details>
      {liveActivity && <span className="thinking-announcement" role="status" aria-live="polite" aria-atomic="true">
        {latest?.text ?? 'Working on your request.'}
      </span>}
    </>
  );
}
