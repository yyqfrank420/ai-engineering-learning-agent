import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { GraphGenerationStatus } from './GraphGenerationStatus';

describe('generation feedback', () => {
  it('shows reported work directly without pause or cancel controls', () => {
    const { container } = render(<GraphGenerationStatus hasGraph={false} isPreview={false}
      progress={[{ phase: 'review', status: 'active', title: 'Checking connections', detail: 'Checking the candidate.' }]} />);
    expect(screen.getByRole('heading').textContent).toBe('Building your diagram…');
    expect(screen.getByText('Checking connections')).toBeTruthy();
    expect(screen.getByText('Checking the candidate.')).toBeTruthy();
    expect(screen.queryByRole('button')).toBeNull();
    expect(container.querySelector('details')).toBeNull();
    expect(screen.queryByRole('progressbar')).toBeNull();
  });

  it('updates the visible status for completion and failure', () => {
    const { rerender } = render(<GraphGenerationStatus hasGraph isPreview={false}
      progress={[{ phase: 'render', status: 'complete', title: 'Diagram laid out', detail: 'Layout is ready.' }]} />);
    expect(screen.getByRole('heading').textContent).toBe('Preparing your answer…');
    expect(screen.getByRole('status').textContent).toContain('Layout is ready.');
    rerender(<GraphGenerationStatus hasGraph isPreview={false}
      progress={[{ phase: 'review', status: 'rejected', title: 'Connection interrupted', detail: 'Please try again when connected.' }]} />);
    expect(screen.getByRole('heading').textContent).toBe('Diagram needs another try');
    expect(screen.getByRole('status').textContent).toContain('Please try again when connected.');
    expect(screen.queryByText('Layout is ready.')).toBeNull();
  });
});
