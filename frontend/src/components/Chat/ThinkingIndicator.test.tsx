import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { WorkflowProgress } from '../../types';
import { ThinkingIndicator } from './ThinkingIndicator';

function progress(phase: WorkflowProgress['phase'], status: WorkflowProgress['status'] = 'active'): WorkflowProgress {
  return { phase, status, title: 'Internal phase title', detail: 'Internal workflow details' };
}

describe('ThinkingIndicator', () => {
  it.each([
    ['evidence', 'Reading sources…'],
    ['architect', 'Building diagram…'],
    ['challenger', 'Checking diagram…'],
    ['integrate', 'Building diagram…'],
    ['render', 'Building diagram…'],
    ['review', 'Checking diagram…'],
    ['revise', 'Refining diagram…'],
    ['explain', 'Writing answer…'],
  ] as const)('shows a short label for %s', (phase, label) => {
    const { container } = render(<ThinkingIndicator workflowProgress={[progress(phase)]} isGenerating />);
    const status = screen.getByRole('status');
    expect(status.textContent).toBe(label);
    expect(status.getAttribute('aria-live')).toBe('polite');
    expect(status.getAttribute('aria-atomic')).toBe('true');
    expect(container.querySelector('details, ol, ul, svg, button')).toBeNull();
    expect(screen.queryByText(/Internal/)).toBeNull();
  });

  it('follows the latest reported phase, including a repair', () => {
    const { rerender } = render(<ThinkingIndicator workflowProgress={[progress('explain'), progress('evidence')]} isGenerating />);
    expect(screen.getByRole('status').textContent).toBe('Reading sources…');
    rerender(<ThinkingIndicator workflowProgress={[progress('evidence'), progress('revise', 'retry')]} isGenerating />);
    expect(screen.getByRole('status').textContent).toBe('Refining diagram…');
  });

  it.each([undefined, progress('evidence', 'complete'), progress('review', 'rejected')])(
    'uses neutral feedback while waiting without an active phase', latest => {
      render(<ThinkingIndicator workflowProgress={latest ? [latest] : []} isGenerating />);
      expect(screen.getByRole('status').textContent).toBe('Working…');
    },
  );

  it('shows preparation while a completed answer waits for display', () => {
    render(<ThinkingIndicator workflowProgress={[progress('explain', 'complete')]} isGenerating />);
    expect(screen.getByRole('status').textContent).toBe('Preparing answer…');
  });

  it.each(['complete', 'rejected'] as const)('removes feedback and history after a %s turn', status => {
    const { rerender, container } = render(<ThinkingIndicator workflowProgress={[progress('review')]} isGenerating />);
    rerender(<ThinkingIndicator workflowProgress={[progress('review', status)]} />);
    expect(container.textContent).toBe('');
    expect(container.querySelector('details')).toBeNull();
    expect(screen.queryByRole('status')).toBeNull();
  });
});
