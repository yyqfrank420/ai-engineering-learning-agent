import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useBackendReadiness } from '../useBackendReadiness';

vi.mock('../../services/api', () => ({
  captureAnalyticsEvent: vi.fn().mockResolvedValue(undefined),
  prepareBackend: vi.fn(),
}));

vi.mock('../../services/analytics', () => ({ trackEvent: vi.fn() }));

import { prepareBackend } from '../../services/api';
import { trackEvent } from '../../services/analytics';

const TEST_SESSION = {
  access_token: 'token',
  refresh_token: 'refresh',
  user: {
    id: 'user-1',
    email: 'friend@example.com',
  },
};

describe('useBackendReadiness', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    localStorage.clear();
    vi.useRealTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('automatically starts preparing an authenticated session', () => {
    vi.mocked(prepareBackend).mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useBackendReadiness(TEST_SESSION));

    expect(result.current.backendReadiness).toBe('preparing');
    expect(result.current.isBackendReady).toBe(false);
    expect(prepareBackend).toHaveBeenCalledTimes(1);
  });

  it('marks the backend ready only after /api/prepare succeeds', async () => {
    vi.mocked(prepareBackend).mockResolvedValueOnce({
      status: 'ready',
      faiss_loaded: true,
    });

    const { result } = renderHook(() => useBackendReadiness(TEST_SESSION));

    await act(async () => {
      await result.current.prepareBackendNow();
    });

    await waitFor(() => {
      expect(result.current.backendReadiness).toBe('ready');
      expect(result.current.isBackendReady).toBe(true);
      expect(result.current.prepareMessage).toBeNull();
    });
  });

  it('surfaces prepare failures and allows a retry', async () => {
    vi.mocked(prepareBackend)
      .mockRejectedValueOnce(new Error('Backend unavailable'))
      .mockResolvedValueOnce({
        status: 'ready',
        faiss_loaded: true,
      });

    const { result } = renderHook(() => useBackendReadiness(TEST_SESSION));

    await act(async () => {
      await result.current.prepareBackendNow();
    });

    await waitFor(() => {
      expect(result.current.backendReadiness).toBe('error');
      expect(result.current.prepareMessage).toBe('Backend unavailable');
    });
    expect(vi.mocked(trackEvent).mock.calls.some(([name]) => name === 'prepare_clicked')).toBe(false);

    await act(async () => {
      await result.current.prepareBackendNow();
    });

    await waitFor(() => {
      expect(result.current.backendReadiness).toBe('ready');
      expect(result.current.isBackendReady).toBe(true);
      expect(result.current.prepareMessage).toBeNull();
    });
  });

  it('keeps one pending request across same-user token refreshes', async () => {
    let finish!: (value: { status: 'ready' }) => void;
    vi.mocked(prepareBackend).mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    const { result, rerender } = renderHook(({ session }) => useBackendReadiness(session), {
      initialProps: { session: TEST_SESSION },
    });
    const signal = vi.mocked(prepareBackend).mock.calls[0][0]!;
    rerender({ session: { ...TEST_SESSION, access_token: 'refreshed' } });
    expect(prepareBackend).toHaveBeenCalledTimes(1);
    expect(signal.aborted).toBe(false);
    await act(async () => { finish({ status: 'ready' }); });
    expect(result.current.isBackendReady).toBe(true);
    expect(vi.mocked(trackEvent).mock.calls.map(([name]) => name)).toEqual(['prepare_succeeded']);
  });

  it('resets the prepared cache when the authenticated user changes', async () => {
    vi.mocked(prepareBackend).mockResolvedValue({
      status: 'ready',
      faiss_loaded: true,
    });

    const { result, rerender } = renderHook(
      ({ session }) => useBackendReadiness(session),
      { initialProps: { session: TEST_SESSION } },
    );

    await act(async () => {
      await result.current.prepareBackendNow();
    });

    await waitFor(() => {
      expect(result.current.backendReadiness).toBe('ready');
    });

    rerender({
      session: {
        ...TEST_SESSION,
        user: {
          id: 'user-2',
          email: 'second@example.com',
        },
      },
    });

    await waitFor(() => expect(result.current.backendReadiness).toBe('ready'));
    expect(prepareBackend).toHaveBeenCalledTimes(2);
  });

  it('does nothing without an auth session and can clear prepared cache', async () => {
    vi.mocked(prepareBackend).mockResolvedValue({ status: 'ready', faiss_loaded: true });

    const { result, rerender } = renderHook(
      ({ session }) => useBackendReadiness(session),
      { initialProps: { session: null as typeof TEST_SESSION | null } },
    );

    await act(async () => {
      await result.current.prepareBackendNow();
    });

    expect(prepareBackend).not.toHaveBeenCalled();

    rerender({ session: TEST_SESSION });
    await act(async () => {
      await result.current.prepareBackendNow();
    });
    await waitFor(() => expect(result.current.backendReadiness).toBe('ready'));

    act(() => {
      result.current.clearPreparedCache();
    });

    expect(result.current.backendReadiness).toBe('unknown');
  });

  it('renders the real startup milestone reported by the backend', async () => {
    vi.useFakeTimers();
    vi.mocked(prepareBackend).mockResolvedValue({
      status: 'preparing',
      step: 'index',
      detail: 'Loading the retrieval index into memory',
      progress: { completed_units: 2, total_units: 3, percent: 67 },
      faiss_loaded: false,
    });

    const { result } = renderHook(() => useBackendReadiness(TEST_SESSION));

    await act(async () => {
      await result.current.prepareBackendNow();
    });

    expect(result.current.backendReadiness).toBe('preparing');
    expect(result.current.prepareMessage).toBe('Loading the retrieval index into memory');
    expect(result.current.prepareProgress).toEqual({
      completedUnits: 2,
      totalUnits: 3,
      percent: 67,
    });
  });

  it('waits for each readiness poll before scheduling another', async () => {
    vi.useFakeTimers();
    let resolveSlowPoll!: (value: {
      status: 'preparing';
      step: string;
      progress: { completed_units: number; total_units: number; percent: number };
    }) => void;
    const slowPoll = new Promise<{
      status: 'preparing';
      step: string;
      progress: { completed_units: number; total_units: number; percent: number };
    }>((resolve) => {
      resolveSlowPoll = resolve;
    });
    vi.mocked(prepareBackend)
      .mockResolvedValueOnce({
        status: 'preparing',
        step: 'artifacts',
        progress: { completed_units: 1, total_units: 3, percent: 33 },
      })
      .mockReturnValueOnce(slowPoll)
      .mockResolvedValueOnce({ status: 'ready', faiss_loaded: true });

    const { result } = renderHook(() => useBackendReadiness(TEST_SESSION));
    await act(async () => {
      await result.current.prepareBackendNow();
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    expect(prepareBackend).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_500);
    });
    expect(prepareBackend).toHaveBeenCalledTimes(2);

    await act(async () => {
      resolveSlowPoll({
        status: 'preparing',
        step: 'index',
        progress: { completed_units: 2, total_units: 3, percent: 67 },
      });
      await Promise.resolve();
      await vi.advanceTimersByTimeAsync(500);
    });

    expect(prepareBackend).toHaveBeenCalledTimes(3);
    expect(result.current.backendReadiness).toBe('ready');
  });

  it('shows non-index startup steps and fails from interval polling errors', async () => {
    vi.useFakeTimers();
    vi.mocked(prepareBackend)
      .mockResolvedValueOnce({
        status: 'preparing',
        step: 'database',
        progress: { completed_units: 0, total_units: 3, percent: 0 },
      })
      .mockRejectedValueOnce(new Error('Backend gone'));

    const { result } = renderHook(() => useBackendReadiness(TEST_SESSION));

    await act(async () => {
      await result.current.prepareBackendNow();
    });

    expect(result.current.prepareMessage).toBe('Initializing database…');

    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });

    expect(result.current.backendReadiness).toBe('error');
    expect(result.current.prepareMessage).toBe('Backend gone');
  });

  it('does not restart preparation or retry errors for same-user session refreshes', async () => {
    vi.mocked(prepareBackend).mockRejectedValueOnce(new Error('Offline'));
    const { result, rerender } = renderHook(({ session }) => useBackendReadiness(session), {
      initialProps: { session: TEST_SESSION },
    });
    await waitFor(() => expect(result.current.backendReadiness).toBe('error'));
    rerender({ session: { ...TEST_SESSION, access_token: 'refreshed' } });
    expect(prepareBackend).toHaveBeenCalledTimes(1);
    vi.mocked(prepareBackend).mockResolvedValueOnce({ status: 'ready' });
    await act(async () => { await result.current.prepareBackendNow(); });
    rerender({ session: { ...TEST_SESSION, access_token: 'newer' } });
    expect(result.current.backendReadiness).toBe('ready');
    expect(prepareBackend).toHaveBeenCalledTimes(2);
  });

  it.each(['unmount', 'clear', 'user change'] as const)('aborts and ignores stale results on %s', async (action) => {
    vi.useFakeTimers();
    let finish!: (result: { status: 'preparing'; step: string }) => void;
    vi.mocked(prepareBackend).mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    const { result, unmount, rerender } = renderHook(({ session }) => useBackendReadiness(session), {
      initialProps: { session: TEST_SESSION },
    });
    const signal = vi.mocked(prepareBackend).mock.calls[0][0]!;
    if (action === 'unmount') unmount();
    else if (action === 'clear') act(() => result.current.clearPreparedCache());
    else {
      vi.mocked(prepareBackend).mockResolvedValueOnce({ status: 'ready' });
      await act(async () => { rerender({ session: { ...TEST_SESSION, user: { ...TEST_SESSION.user, id: 'user-2' } } }); });
    }
    expect(signal.aborted).toBe(true);
    await act(async () => {
      finish({ status: 'preparing', step: 'index' });
      await vi.advanceTimersByTimeAsync(2_000);
    });
    expect(prepareBackend).toHaveBeenCalledTimes(action === 'user change' ? 2 : 1);
    if (action === 'clear') expect(result.current.backendReadiness).toBe('unknown');
    if (action === 'user change') expect(result.current.backendReadiness).toBe('ready');
    expect(vi.getTimerCount()).toBe(0);
  });

  it('cancels an already scheduled poll when clearing or unmounting', async () => {
    vi.useFakeTimers();
    vi.mocked(prepareBackend).mockResolvedValue({ status: 'preparing' });
    const { result, unmount } = renderHook(() => useBackendReadiness(TEST_SESSION));
    await act(async () => {});
    expect(vi.getTimerCount()).toBe(1);
    act(() => result.current.clearPreparedCache());
    expect(vi.getTimerCount()).toBe(0);
    await act(async () => { await result.current.prepareBackendNow(); });
    expect(vi.getTimerCount()).toBe(1);
    unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(2_000); });
    expect(prepareBackend).toHaveBeenCalledTimes(2);
  });

  it('survives StrictMode effect replay and ignores the aborted first response', async () => {
    let stale!: (value: { status: 'ready' }) => void;
    vi.mocked(prepareBackend)
      .mockReturnValueOnce(new Promise(resolve => { stale = resolve; }))
      .mockRejectedValueOnce(new Error('Current attempt failed'));
    const { result } = renderHook(() => useBackendReadiness(TEST_SESSION), {
      reactStrictMode: true,
    });
    await waitFor(() => expect(result.current.backendReadiness).toBe('error'));
    expect(prepareBackend).toHaveBeenCalledTimes(2);
    expect(vi.mocked(prepareBackend).mock.calls[0][0]?.aborted).toBe(true);
    await act(async () => { stale({ status: 'ready' }); });
    expect(result.current.backendReadiness).toBe('error');
  });

  it('requires a new check when switching back to a previously ready user', async () => {
    vi.mocked(prepareBackend)
      .mockResolvedValueOnce({ status: 'ready' })
      .mockReturnValue(new Promise(() => {}));
    const { result, rerender } = renderHook(({ session }) => useBackendReadiness(session), {
      initialProps: { session: TEST_SESSION },
    });
    await waitFor(() => expect(result.current.isBackendReady).toBe(true));
    rerender({ session: { ...TEST_SESSION, user: { ...TEST_SESSION.user, id: 'user-2' } } });
    expect(result.current.backendReadiness).toBe('preparing');
    rerender({ session: TEST_SESSION });
    expect(result.current.backendReadiness).toBe('preparing');
    expect(result.current.isBackendReady).toBe(false);
    expect(prepareBackend).toHaveBeenCalledTimes(3);
    expect(vi.mocked(prepareBackend).mock.calls[1][0]?.aborted).toBe(true);
  });

});
