import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { ThinkingProgress, WorkflowProgress } from '../../types';
import { ThinkingIndicator } from './ThinkingIndicator';

function progress(phase: string, status: string = 'active'): WorkflowProgress {
  return { phase, status, title: 'Internal phase title', detail: 'Internal workflow details' } as WorkflowProgress;
}

describe('ThinkingIndicator', () => {
  it('shows concurrent real operations without exposing internal prose or percentages', () => {
    const { container } = render(<ThinkingIndicator workflowProgress={[progress('book'), progress('web')]} isGenerating />);
    expect(screen.getByText('Searching the book…')).toBeTruthy();
    expect(screen.getByText('Searching the web…')).toBeTruthy();
    expect(screen.getByRole('status').getAttribute('aria-live')).toBe('polite');
    expect(screen.queryByText(/Internal/)).toBeNull();
    expect(container.querySelector('details, progress, button')).toBeNull();
    expect(container.textContent).not.toContain('%');
  });

  it('keeps the other operation visible while one completes and retains only the latest completed milestone', () => {
    const view = render(<ThinkingIndicator workflowProgress={[progress('book'), progress('web')]} isGenerating />);
    view.rerender(<ThinkingIndicator workflowProgress={[progress('web'), progress('book', 'complete')]} isGenerating />);
    expect(screen.queryByText('Searching the book…')).toBeNull();
    expect(screen.getByText('Book search finished')).toBeTruthy();
    expect(screen.getByText('Searching the web…')).toBeTruthy();
    view.rerender(<ThinkingIndicator workflowProgress={[progress('book', 'complete'), progress('web', 'complete'), progress('components')]} isGenerating />);
    expect(screen.queryByText('Book search finished')).toBeNull();
    expect(screen.getByText('Web search finished')).toBeTruthy();
    expect(screen.getByText('Building components…')).toBeTruthy();
  });

  it('shows retries as ongoing work without treating degraded or rejected stages as active or successful', () => {
    render(<ThinkingIndicator workflowProgress={[progress('book', 'degraded'), progress('review', 'rejected'), progress('revise', 'retry')]} isGenerating />);
    expect(screen.getByRole('status').textContent).toBe('Refining the diagram…');
  });

  it('shows real completion and concurrent answer work during accepted finishing', () => {
    render(<ThinkingIndicator workflowProgress={[progress('review', 'complete'), progress('explain')]} isGenerating isFinishingDiagram />);
    expect(screen.getByText('Diagram checked')).toBeTruthy();
    expect(screen.getByText('Writing the answer…')).toBeTruthy();
  });

  it('uses neutral finishing feedback while awaiting the next event', () => {
    render(<ThinkingIndicator isGenerating isFinishingDiagram />);
    expect(screen.getByRole('status').textContent).toBe('Finishing…');
  });

  it('does not invent an operation before an event arrives', () => {
    render(<ThinkingIndicator isGenerating />);
    expect(screen.getByRole('status').textContent).toBe('Working…');
  });

  it('deduplicates equivalent answer phase labels', () => {
    render(<ThinkingIndicator workflowProgress={[progress('explain'), progress('synthesis')]} isGenerating />);
    expect(screen.getAllByText('Writing the answer…')).toHaveLength(1);
  });

  it('opens provider text by default as plain text with a bounded collapsed excerpt', () => {
    const content = '<img src="https://example.test/pixel"> **not markdown** ' + 'x'.repeat(180);
    const trace: ThinkingProgress = { operationId: 'components-1', phase: 'components', content };
    const { container } = render(<ThinkingIndicator isGenerating thinkingProgress={[trace]} />);
    const details = container.querySelector('details')!;
    expect(details.open).toBe(true);
    expect(container.querySelector('.thinking-excerpt')?.textContent?.length).toBeLessThanOrEqual(140);
    expect(screen.getByText(content)).toBeTruthy();
    expect(container.querySelector('img, a, strong')).toBeNull();
    expect(screen.getByRole('status').textContent).not.toContain(content);
  });

  it('preserves the native disclosure toggle and scroll position across trace updates', () => {
    const trace: ThinkingProgress = { operationId: 'review-1', phase: 'review', content: 'First thought.' };
    const view = render(<ThinkingIndicator isGenerating thinkingProgress={[trace]} />);
    const details = view.container.querySelector('details')!;
    const transcript = screen.getByRole('region', { name: 'Thinking trace' });
    transcript.scrollTop = 35;
    view.rerender(<ThinkingIndicator isGenerating thinkingProgress={[{ ...trace, content: 'First thought. Next thought.' }]} />);
    expect(view.container.querySelector('details')).toBe(details);
    expect(details.open).toBe(true);
    expect(transcript.scrollTop).toBe(35);
    expect(transcript.querySelector('p')?.textContent).toBe('First thought. Next thought.');
    details.open = false;
    for (const content of ['First thought. More text.', 'First thought. More text. Still streaming.']) {
      view.rerender(<ThinkingIndicator isGenerating thinkingProgress={[{ ...trace, content }]} />);
      expect(details.open).toBe(false);
      expect(transcript.querySelector('p')?.textContent).toBe(content);
    }
    view.rerender(<ThinkingIndicator thinkingProgress={[trace]} />);
    expect(view.container.querySelector('details')).toBeNull();
  });

  it('uses the most recently updated operation for the excerpt without exposing operation identifiers', () => {
    const thoughts: ThinkingProgress[] = [
      { operationId: 'internal-plan-uuid', phase: 'components', content: 'Plan thought' },
      { operationId: 'internal-review-uuid', phase: 'review', content: 'Review thought' },
    ];
    const { container } = render(<ThinkingIndicator isGenerating thinkingProgress={thoughts} />);
    expect(container.querySelector('.thinking-excerpt')?.textContent).toBe('Review thought');
    expect(container.textContent).not.toContain('internal-');
  });

  it.each(['complete', 'rejected', 'degraded'])('removes live activity after a %s terminal turn', status => {
    const view = render(<ThinkingIndicator workflowProgress={[progress('review')]} isGenerating />);
    view.rerender(<ThinkingIndicator workflowProgress={[progress('review', status)]} />);
    expect(screen.queryByRole('status')).toBeNull();
  });
});
