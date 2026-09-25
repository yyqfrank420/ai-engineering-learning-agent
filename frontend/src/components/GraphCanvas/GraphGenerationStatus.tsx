import { useState } from 'react';
import type { WorkflowProgress } from '../../types';
import './GraphGenerationStatus.css';
import { WorkflowActivity } from '../WorkflowActivity';

interface Props {
  progress: WorkflowProgress[];
  hasGraph: boolean;
  isPreview: boolean;
  onStop?: () => void;
}

export function GraphGenerationStatus({ progress, hasGraph, isPreview, onStop }: Props) {
  const [motionPaused, setMotionPaused] = useState(false);
  const latest = progress.at(-1);
  const rejected = latest?.status === 'rejected';
  const title = rejected ? 'Diagram needs another try' : hasGraph && !isPreview ? 'Preparing your answer…' : 'Building your diagram…';

  return (
    <section className={`graph-generation ${hasGraph ? 'graph-generation--overlay' : ''}`}
      data-motion-paused={motionPaused || rejected} aria-label="Generation progress">
      <div className="graph-generation__visual" aria-hidden="true">
        <svg viewBox="0 0 560 160" fill="none">
          <path className="graph-generation__track" d="M70 80H220M280 80H480M280 80V130H400" />
          <path className="graph-generation__signal" d="M70 80H220M280 80H480M280 80V130H400" />
          {[70, 250, 480].map((x, index) => (
            <g key={x} className="graph-generation__node" style={{ animationDelay: `${index * 0.5}s` }}>
              <rect x={x - 30} y="50" width="60" height="60" rx="14" />
              <path d={`M${x - 12} 73H${x + 12}M${x - 12} 85H${x + 5}`} />
            </g>
          ))}
          <circle cx="400" cy="130" r="7" className="graph-generation__endpoint" />
        </svg>
      </div>
      <div role="status" aria-live="polite" aria-atomic="true">
        <h2>{title}</h2>
        <WorkflowActivity progress={progress} />
      </div>
      <div className="graph-generation__actions">
        <button type="button" onClick={() => setMotionPaused(value => !value)} aria-pressed={motionPaused}
          aria-label={motionPaused ? 'Resume animation' : 'Pause animation'} title={motionPaused ? 'Resume animation' : 'Pause animation'}>
          <svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
            {motionPaused ? <path d="M4 2L14 8L4 14Z" /> : <><rect x="3" y="2" width="3" height="12" rx="1" /><rect x="10" y="2" width="3" height="12" rx="1" /></>}
          </svg>
        </button>
        {onStop && <button type="button" onClick={onStop} aria-label="Stop generation">Cancel</button>}
      </div>
    </section>
  );
}
