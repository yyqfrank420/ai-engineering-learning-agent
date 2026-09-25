import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { GraphGenerationStatus } from './GraphGenerationStatus';

describe('generation feedback', () => {
  it('shows reported work and lets the learner pause motion or stop generation', () => {
    const stop = vi.fn();
    render(<GraphGenerationStatus hasGraph={false} isPreview={false} onStop={stop}
      progress={[{ phase: 'review', status: 'active', title: 'Checking connections', detail: 'Checking the candidate.' }]} />);
    expect(screen.getByRole('heading').textContent).toBe('Building your diagram…');
    expect(screen.queryByText('Checking the candidate.')).toBeNull();
    expect(screen.queryByText('Your workspace is taking shape')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Pause animation' }));
    expect(screen.getByRole('region').getAttribute('data-motion-paused')).toBe('true');
    fireEvent.click(screen.getByRole('button', { name: 'Stop generation' }));
    expect(stop).toHaveBeenCalledOnce();
    expect(screen.queryByRole('progressbar')).toBeNull();
  });
});
