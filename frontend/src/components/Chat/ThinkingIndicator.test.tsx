import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ThinkingIndicator } from './ThinkingIndicator';


describe('ThinkingIndicator', () => {
  it('keeps completed activity collapsed and available', () => {
    render(<ThinkingIndicator
      workerStatus={{ rag: null, graph: null, critic: null, orchestrator: null, research: null }}
      workflowProgress={[{ phase: 'explain', status: 'complete', title: 'Done', detail: 'Finished.' }]}
    />);
    expect(screen.getByText('View activity').closest('details')?.open).toBe(false);
    expect(screen.getByText('Walkthrough ready')).toBeTruthy();
  });

  it('does not promise a diagram while gathering evidence', () => {
    render(<ThinkingIndicator
      workerStatus={{ rag: null, graph: null, critic: null, orchestrator: null, research: null }}
      workflowProgress={[{ phase: 'evidence', status: 'complete', title: 'Evidence ready', detail: 'Sources collected.' }]}
      isGenerating
    />);
    expect(screen.getByRole('status').textContent).toBe('Working…');
    expect(screen.getByText('Details').closest('details')?.open).toBe(false);
    expect(screen.queryByText('Designing your system')).toBeNull();
  });

  it('shows a bounded diagram repair clearly', () => {
    render(
      <ThinkingIndicator
        workerStatus={{ rag: null, graph: null, critic: null, orchestrator: null, research: null }}
        workflowProgress={[{
          phase: 'revise',
          status: 'retry',
          title: 'Refining the diagram',
          detail: 'Applying the clarity review once.',
        }]}
        isGenerating
      />,
    );

    expect(screen.getByRole('status').textContent).toBe('Working…');
    expect(screen.getByText(/Applying the clarity review/).closest('details')?.open).toBe(false);
  });

  it('keeps resume available after generation finishes with queued blocks', () => {
    const onTogglePause = vi.fn();

    render(
      <ThinkingIndicator
        workerStatus={{ rag: null, graph: null, critic: null, orchestrator: null, research: null }}
        workflowProgress={[{
          phase: 'explain',
          status: 'complete',
          title: 'Walkthrough complete',
          detail: 'Explanation blocks are ready.',
        }]}
        isGenerating={false}
        explanationPaused
        onTogglePause={onTogglePause}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Resume reveal' }));

    expect(onTogglePause).toHaveBeenCalledOnce();
  });
});
