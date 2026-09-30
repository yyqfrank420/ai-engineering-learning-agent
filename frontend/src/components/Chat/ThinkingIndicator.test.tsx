import { act, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { LiveActivity, MessageActivity } from '../../types';
import { ThinkingIndicator } from './ThinkingIndicator';

const activity: MessageActivity = { duration_ms: 65_000, steps: [
  { sequence: 0, kind: 'update', phase: 'context', status: 'complete', text: "I'll check how this fits your diagram.", elapsed_ms: 0 },
  { sequence: 1, kind: 'tool', phase: 'book', status: 'complete', text: 'Searched the book', elapsed_ms: 1000 },
] };
const live: LiveActivity = { clientRequestId: 'request', startedAt: 0, activity };

describe('ThinkingIndicator public work activity', () => {
  afterEach(() => vi.useRealTimers());

  it('opens live updates with quieter tool rows and a timer outside announcements', () => {
    vi.useFakeTimers();
    vi.setSystemTime(65_000);
    const view = render(<ThinkingIndicator activity={activity} liveActivity={live} />);
    expect(view.container.querySelector('details')?.open).toBe(true);
    expect(screen.getByText('Working for 1m 5s')).toBeTruthy();
    expect(view.container.querySelector('.thinking-update')?.textContent).toBe(activity.steps[0].text);
    expect(view.container.querySelector('.thinking-tool')?.textContent).toBe('Searched the book');
    const announcement = screen.getByRole('status');
    expect(announcement.textContent).toBe('Searched the book');
    act(() => vi.advanceTimersByTime(2000));
    expect(screen.getByText('Working for 1m 7s')).toBeTruthy();
    expect(announcement.textContent).toBe('Searched the book');
    expect(view.container.textContent).not.toContain('%');
  });

  it('uses the saved duration and a native collapsed disclosure after completion', () => {
    const view = render(<ThinkingIndicator activity={activity} />);
    const details = view.container.querySelector('details')!;
    expect(details.open).toBe(false);
    expect(screen.getByText('Worked for 1m 5s')).toBeTruthy();
    expect(screen.queryByRole('status')).toBeNull();
    details.open = true;
    const region = screen.getByRole('region', { name: 'Work activity' });
    region.scrollTop = 35;
    view.rerender(<ThinkingIndicator activity={{ ...activity, duration_ms: 65_999 }} />);
    expect(view.container.querySelector('details')).toBe(details);
    expect(details.open).toBe(true);
    expect(region.scrollTop).toBe(35);
  });

  it('preserves a user toggle across live events and collapses once when completed', () => {
    const view = render(<ThinkingIndicator activity={activity} liveActivity={live} />);
    const details = view.container.querySelector('details')!;
    details.open = false;
    const updated = { ...activity, steps: [...activity.steps, { ...activity.steps[0], sequence: 2, text: 'I have a draft ready to check.' }] };
    view.rerender(<ThinkingIndicator activity={updated} liveActivity={{ ...live, activity: updated }} />);
    expect(details.open).toBe(false);
    view.rerender(<ThinkingIndicator activity={updated} />);
    expect(view.container.querySelector('details')).toBe(details);
    expect(details.open).toBe(false);
  });

  it('renders public updates as text, without fetching markup or exposing phase identifiers', () => {
    const text = '<img src="https://example.test/pixel"> **plain text**';
    const view = render(<ThinkingIndicator activity={{ duration_ms: 1200,
      steps: [{ ...activity.steps[0], text, phase: 'challenger' }] }} />);
    expect(view.container.querySelector('.thinking-update')?.textContent).toBe(text);
    expect(view.container.querySelector('img, a, strong')).toBeNull();
    expect(view.container.textContent).not.toContain('challenger');
    expect(screen.getByText('Worked for 1s')).toBeTruthy();
  });
});
