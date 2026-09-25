import type { WorkflowProgress } from '../types';

const labels: Record<WorkflowProgress['phase'], [string, string]> = {
  evidence: ['Reading relevant sources', 'Sources reviewed'],
  architect: ['Designing the architecture', 'Architecture drafted'],
  challenger: ['Checking the design', 'Design checked'],
  integrate: ['Connecting the components', 'Components connected'],
  render: ['Laying out your diagram', 'Diagram laid out'],
  review: ['Checking diagram readability', 'Diagram checked'],
  revise: ['Refining your diagram', 'Diagram refined'],
  explain: ['Writing your walkthrough', 'Walkthrough ready'],
};

export function WorkflowActivity({ progress, limit = 3 }: { progress: WorkflowProgress[]; limit?: number }) {
  return <ol aria-label="Activity" style={{ listStyle: 'none', padding: 0, margin: '12px 0', lineHeight: 1.8, fontSize: 13, color: '#94a3b8' }}>
    {progress.slice(-limit).map(item => <li key={item.phase}>
      <span aria-hidden="true" style={{ display: 'inline-block', width: 20 }}>{item.status === 'complete' ? '✓' : item.status === 'rejected' ? '!' : '·'}</span>
      {item.status === 'rejected' ? 'The diagram could not be completed' : labels[item.phase][item.status === 'complete' ? 1 : 0]}
    </li>)}
  </ol>;
}
