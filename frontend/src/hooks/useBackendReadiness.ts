import { useCallback, useEffect, useRef, useState } from 'react';
import type { AuthSession } from '../types';
import { trackEvent } from '../services/analytics';
import { prepareBackend } from '../services/api';

export type BackendReadiness = 'unknown' | 'preparing' | 'ready' | 'error';

const IS_TEST_ENV =
  import.meta.env.MODE === 'test' ||
  import.meta.env.VITEST === 'true' ||
  (typeof navigator !== 'undefined' && navigator.userAgent.includes('jsdom'));

const PREPARE_BYPASS =
  !IS_TEST_ENV &&
  (
    import.meta.env.VITE_DEV_BYPASS_AUTH === 'true' ||
    import.meta.env.DEV
  );
const DEFAULT_READINESS: BackendReadiness = PREPARE_BYPASS ? 'ready' : 'unknown';

const STEP_MESSAGES: Record<string, string> = {
  database: 'Initializing database…',
  artifacts: 'Checking knowledge-base files…',
  index: 'Loading the retrieval index…',
};

export function useBackendReadiness(authSession: AuthSession | null) {
  const [readinessState, setReadinessState] = useState<{
    userId: string | null;
    readiness: BackendReadiness;
    message: string | null;
  }>({
    userId: null,
    readiness: DEFAULT_READINESS,
    message: null,
  });
  const userId = authSession?.user.id ?? null;
  const sessionRef = useRef(authSession);
  useEffect(() => { sessionRef.current = authSession; }, [authSession]);
  const preparationRef = useRef<{
    controller: AbortController;
    timer: ReturnType<typeof window.setTimeout> | null;
  } | null>(null);

  const stateBelongsToUser = userId !== null && readinessState.userId === userId;
  const backendReadiness = stateBelongsToUser ? readinessState.readiness : DEFAULT_READINESS;
  const prepareMessage = stateBelongsToUser ? readinessState.message : null;

  const cancelPreparation = useCallback(() => {
    const preparation = preparationRef.current;
    preparationRef.current = null;
    if (!preparation) return;
    preparation.controller.abort();
    if (preparation.timer !== null) window.clearTimeout(preparation.timer);
  }, []);

  const startPreparation = useCallback(async () => {
    const session = sessionRef.current;
    if (!userId || !session || session.user.id !== userId || PREPARE_BYPASS || preparationRef.current) return;
    const preparation = { controller: new AbortController(), timer: null as ReturnType<typeof window.setTimeout> | null };
    preparationRef.current = preparation;
    setReadinessState({
      userId,
      readiness: 'preparing',
      message: 'Starting the service… usually takes 30-60 seconds',
    });
    const isCurrent = () => preparationRef.current === preparation && !preparation.controller.signal.aborted;

    // The server owns progress. Schedule only after each request settles.
    const pollPrepare = async () => {
      try {
        const result = await prepareBackend(preparation.controller.signal);
        if (!isCurrent()) return;
        if (result.status === 'ready') {
          preparationRef.current = null;
          setReadinessState({ userId, readiness: 'ready', message: null });
          void trackEvent('prepare_succeeded', { backend_readiness_state: 'ready' }, session);
          return;
        }
        const message = result.detail?.trim() || STEP_MESSAGES[result.step ?? ''] || 'Warming up backend…';
        setReadinessState({ userId, readiness: 'preparing', message });
        preparation.timer = window.setTimeout(() => {
          preparation.timer = null;
          void pollPrepare();
        }, 500);
      } catch (err) {
        if (!isCurrent()) return;
        preparationRef.current = null;
        setReadinessState({
          userId,
          readiness: 'error',
          message: err instanceof Error ? err.message : 'Backend unavailable. Please retry.',
        });
        void trackEvent('prepare_failed', {
          backend_readiness_state: 'error',
          error_code: err instanceof Error ? err.message : 'prepare_failed',
        }, session);
      }
    };
    await pollPrepare();
  }, [userId]);

  useEffect(() => {
    // Synchronize startup UI with this user's newly started network preparation.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void startPreparation();
    return cancelPreparation;
  }, [startPreparation, cancelPreparation]);

  const prepareBackendNow = useCallback(async () => {
    if (!userId || PREPARE_BYPASS || preparationRef.current) return;
    const session = sessionRef.current;
    if (session) void trackEvent('prepare_clicked', { backend_readiness_state: backendReadiness }, session);
    await startPreparation();
  }, [startPreparation, userId, backendReadiness]);

  const clearPreparedCache = useCallback(() => {
    cancelPreparation();
    setReadinessState({ userId, readiness: DEFAULT_READINESS, message: null });
  }, [userId, cancelPreparation]);

  return {
    backendReadiness,
    prepareMessage,
    isBackendReady: backendReadiness === 'ready',
    prepareBackendNow,
    clearPreparedCache,
  };
}
