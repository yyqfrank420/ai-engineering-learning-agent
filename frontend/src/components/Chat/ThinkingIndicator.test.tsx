import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ThinkingIndicator } from './ThinkingIndicator';

const idleWorkers = { rag: null, graph: null, critic: null, orchestrator: null, research: null };

describe('ThinkingIndicator', () => {
  it('keeps completed activity collapsed and available', () => {
    render(<ThinkingIndicator workerStatus={idleWorkers}
      workflowProgress={[{ phase: 'explain', status: 'complete', title: 'Walkthrough ready', detail: 'Finished.' }]} />);
    expect(screen.getByText('View activity').closest('details')?.open).toBe(false);
    expect(screen.getByText('Walkthrough ready')).toBeTruthy();
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('shows actual progress and deduplicated worker feedback without hidden details or controls', () => {
    const { container } = render(<ThinkingIndicator
      workerStatus={{ ...idleWorkers, rag: 'Searching book…', research: 'Searching book…', graph: 'Sources collected.' }}
      workflowProgress={[{ phase: 'evidence', status: 'complete', title: 'Evidence ready', detail: 'Sources collected.' }]}
      isGenerating />);
    expect(screen.getByRole('status').textContent).toContain('Working…');
    expect(screen.getByText('Evidence ready')).toBeTruthy();
    expect(screen.getAllByText('Sources collected.')).toHaveLength(1);
    expect(screen.getAllByText('Searching book…')).toHaveLength(1);
    expect(container.querySelector('details')).toBeNull();
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('updates visible activity through repair, failure, and completed history', () => {
    const { rerender, container } = render(<ThinkingIndicator workerStatus={idleWorkers}
      workflowProgress={[{ phase: 'revise', status: 'retry', title: 'Refining the diagram', detail: 'Applying the clarity review once.' }]}
      isGenerating />);
    expect(screen.getByText('Applying the clarity review once.')).toBeTruthy();
    expect(container.querySelector('details')).toBeNull();
    const failedProgress = [{ phase: 'revise' as const, status: 'rejected' as const, title: 'Diagram could not be completed', detail: 'The provider is unavailable. Please try again.' }];
    rerender(<ThinkingIndicator workerStatus={idleWorkers} workflowProgress={failedProgress} isGenerating />);
    expect(screen.queryByText('Applying the clarity review once.')).toBeNull();
    expect(screen.getByRole('status').textContent).toContain('The provider is unavailable. Please try again.');
    expect(container.querySelector('details')).toBeNull();
    rerender(<ThinkingIndicator workerStatus={idleWorkers} workflowProgress={failedProgress} />);
    expect(screen.getByText('View activity').closest('details')?.open).toBe(false);
  });

  it('renders no invented activity before any progress arrives', () => {
    render(<ThinkingIndicator workerStatus={idleWorkers} isGenerating />);
    expect(screen.getByRole('status').textContent).toBe('Working…');
    expect(screen.queryByRole('list')).toBeNull();
  });
});
