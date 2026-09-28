import type { WorkflowProgress } from '../../types';
import './GraphGenerationStatus.css';
import { WorkflowActivity } from '../WorkflowActivity';

interface Props {
  progress: WorkflowProgress[];
  hasGraph: boolean;
  isPreview: boolean;
}

export function GraphGenerationStatus({ progress, hasGraph, isPreview }: Props) {
  const latest = progress.at(-1);
  const rejected = latest?.status === 'rejected';
  const title = rejected ? 'Diagram needs another try' : hasGraph && !isPreview ? 'Preparing your answer…' : 'Building your diagram…';

  return (
    <section className={`graph-generation ${hasGraph ? 'graph-generation--overlay' : ''}`}
      aria-label="Generation progress">
      <div className="graph-generation__visual" aria-hidden="true">
        <svg viewBox="0 0 560 160" fill="none">
          <path className="graph-generation__track" d="M70 80H220M280 80H480M280 80V130H400" />
          {[70, 250, 480].map(x => (
            <g key={x} className="graph-generation__node">
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
    </section>
  );
}
