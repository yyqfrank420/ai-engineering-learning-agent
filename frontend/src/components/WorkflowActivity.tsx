import type { WorkerStatus, WorkflowProgress } from '../types';

interface Props {
  progress: WorkflowProgress[];
  limit?: number;
  workerStatus?: WorkerStatus;
}

export function WorkflowActivity({ progress, limit = 3, workerStatus }: Props) {
  const visibleProgress = progress.slice(-limit);
  const progressMessages = new Set(visibleProgress.flatMap(item => [item.title.trim(), item.detail.trim()]));
  const workerMessages = [...new Set(Object.values(workerStatus ?? {})
    .filter((status): status is string => typeof status === 'string' && status.trim().length > 0)
    .map(status => status.trim()))].filter(status => !progressMessages.has(status));

  if (visibleProgress.length === 0 && workerMessages.length === 0) return null;

  return <ol aria-label="Activity" style={{ listStyle: 'none', padding: 0, margin: '12px 0', lineHeight: 1.5, fontSize: 13, color: '#94a3b8', textAlign: 'left', overflowWrap: 'anywhere' }}>
    {visibleProgress.map(item => <li key={item.phase} style={{ display: 'flex', gap: 8, marginTop: 8 }}>
      <svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" style={{ flexShrink: 0, marginTop: 2 }}>
        {item.status === 'complete' ? <path d="m3 8 3 3 7-7" /> : item.status === 'rejected' ? <><path d="M8 3v6" /><circle cx="8" cy="12" r=".75" fill="currentColor" stroke="none" /></> : <circle cx="8" cy="8" r="3" />}
      </svg>
      <div>
        <div style={{ color: '#cbd5e1' }}>{item.title}</div>
        {item.detail && item.detail !== item.title && <div>{item.detail}</div>}
      </div>
    </li>)}
    {workerMessages.map(status => <li key={status} style={{ marginTop: 8, paddingLeft: 24 }}>{status}</li>)}
  </ol>;
}
