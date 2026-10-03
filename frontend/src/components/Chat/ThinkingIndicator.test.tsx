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

  it('shows visible startup text until the first public step arrives', () => {
    const empty = { duration_ms: 0, steps: [] };
    const view = render(<ThinkingIndicator activity={empty} liveActivity={{ ...live, activity: empty }} />);
    const details = view.container.querySelector('details')!;
    expect(details.open).toBe(true);
    expect(screen.getByRole('region', { name: 'Work activity' }).textContent).toBe('Working on your request.');
    view.rerender(<ThinkingIndicator activity={activity} liveActivity={live} />);
    expect(view.container.querySelector('details')).toBe(details);
    expect(screen.getByRole('region', { name: 'Work activity' }).textContent).not.toContain('Working on your request.');
    expect(details.open).toBe(true);
    view.rerender(<ThinkingIndicator activity={activity} />);
    expect(details.open).toBe(false);
  });

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

  it('coalesces adjacent tool start and completion without changing saved activity', () => {
    const steps: MessageActivity['steps'] = Object.freeze([
      { sequence: 0, kind: 'update', phase: 'components', status: 'complete', text: 'The draft has three components.\nI can now connect them.', elapsed_ms: 0 },
      { sequence: 1, kind: 'tool', phase: 'render', status: 'active', text: 'Checking layout', elapsed_ms: 1000 },
      { sequence: 2, kind: 'tool', phase: 'render', status: 'complete', text: 'Layout checked', elapsed_ms: 2000 },
    ]);
    const saved = Object.freeze({ duration_ms: 2500, steps });
    const running = { clientRequestId: 'layout', startedAt: Date.now(), activity: saved };
    const initial = { ...saved, duration_ms: 1000, steps: steps.slice(0, 2) };
    const view = render(<ThinkingIndicator activity={initial} liveActivity={{ ...running, activity: initial }} />);
    const details = view.container.querySelector('details')!;
    expect(screen.getByRole('status').textContent).toBe('Checking layout');
    view.rerender(<ThinkingIndicator activity={saved} liveActivity={running} />);
    expect(view.container.querySelector('details')).toBe(details);
    expect(screen.queryByText('Checking layout')).toBeNull();
    expect([...view.container.querySelectorAll('.thinking-steps > *')].map(row => row.textContent))
      .toEqual([steps[0].text, 'Layout checked']);
    expect(view.container.querySelector('.thinking-update')?.textContent).toBe(steps[0].text);
    expect(screen.getByRole('status').textContent).toBe('Layout checked');
    expect(saved.steps).toHaveLength(3);
    view.rerender(<ThinkingIndicator activity={saved} />);
    expect(view.container.querySelector('details')).toBe(details);
    expect(details.open).toBe(false);
    expect(screen.queryByRole('status')).toBeNull();
    expect(screen.getByText('Worked for 2s')).toBeTruthy();
    view.unmount();
    const reloaded = render(<ThinkingIndicator activity={JSON.parse(JSON.stringify(saved))} />);
    expect(reloaded.container.querySelector('details')?.open).toBe(false);
    expect(reloaded.container.querySelectorAll('.thinking-tool')).toHaveLength(1);
    expect(reloaded.container.querySelector('.thinking-update')?.textContent).toBe(steps[0].text);
  });

  it('retains interleaved work, unsuccessful steps, and later tool attempts in order', () => {
    const rows: Array<Pick<MessageActivity['steps'][number], 'kind' | 'phase' | 'status' | 'text'>> = [
      { kind: 'tool', phase: 'book', status: 'active', text: 'Searching book' },
      { kind: 'update', phase: 'evidence', status: 'complete', text: 'I found a useful example.' },
      { kind: 'tool', phase: 'book', status: 'complete', text: 'Book search finished' },
      { kind: 'tool', phase: 'review', status: 'active', text: 'Checking draft' },
      { kind: 'tool', phase: 'render', status: 'complete', text: 'Layout checked' },
      { kind: 'tool', phase: 'review', status: 'retry', text: 'Trying the check again' },
      { kind: 'tool', phase: 'review', status: 'rejected', text: 'Check did not complete' },
      { kind: 'tool', phase: 'review', status: 'degraded', text: 'Check returned limited results' },
      { kind: 'tool', phase: 'review', status: 'active', text: 'Checking revised draft' },
      { kind: 'tool', phase: 'review', status: 'complete', text: 'Revised draft checked' },
      { kind: 'tool', phase: 'review', status: 'active', text: 'Checking next draft' },
    ];
    const saved = { duration_ms: 2000, steps: rows.map((step, sequence) => ({ ...step, sequence, elapsed_ms: sequence * 100 })) };
    const view = render(<ThinkingIndicator activity={saved} />);
    expect([...view.container.querySelectorAll('.thinking-steps > *')].map(row => row.textContent))
      .toEqual(rows.filter((_, index) => index !== 8).map(row => row.text));
    expect([...view.container.querySelectorAll('.thinking-tool[data-status]')].map(row => row.getAttribute('data-status')))
      .toContain('retry');
    expect(view.container.querySelector('.thinking-tool[data-status="rejected"]')?.textContent).toBe('Check did not complete');
    expect(view.container.querySelector('.thinking-tool[data-status="degraded"]')?.textContent).toBe('Check returned limited results');
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
