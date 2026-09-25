import type {
  AnalyticsEventName,
  AnalyticsEventProperties,
  AuthSession,
  DashboardFailuresResponse,
  DashboardFunnelResponse,
  DashboardLLMPerformanceResponse,
  DashboardOverviewResponse,
  DashboardTrendsResponse,
  GraphData,
  GraphContentEdit,
  ThreadDetail,
  ThreadSummary,
} from '../types';
import { API_BASE } from './config';

async function authedFetch(path: string, session: AuthSession, init?: RequestInit): Promise<Response> {
  return fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${session.access_token}`,
      ...(init?.headers ?? {}),
    },
  });
}

export async function fetchLatestThread(session: AuthSession): Promise<ThreadDetail> {
  const response = await authedFetch('/api/threads/latest', session);
  if (!response.ok) throw new Error('Failed to load latest thread');
  return response.json();
}

export async function fetchThread(session: AuthSession, threadId: string): Promise<ThreadDetail> {
  const response = await authedFetch(`/api/threads/${threadId}`, session);
  if (!response.ok) throw new Error('Failed to load thread');
  return response.json();
}

export async function checkDiagramIntent(session: AuthSession, threadId: string, message: string): Promise<'send' | 'answer' | 'ask'> {
  const response = await authedFetch(`/api/threads/${threadId}/diagram-intent`, session, {
    method: 'POST', body: JSON.stringify({ message }), signal: AbortSignal.timeout(5000),
  });
  if (!response.ok) throw new Error('Could not check diagram intent');
  const data = await response.json();
  if (!['send', 'answer', 'ask'].includes(data.action)) throw new Error('Invalid diagram intent');
  return data.action;
}

export async function createThread(session: AuthSession, title = 'New chat'): Promise<ThreadDetail> {
  const response = await authedFetch('/api/threads', session, {
    method: 'POST',
    body: JSON.stringify({ title }),
  });
  if (!response.ok) throw new Error('Failed to create thread');
  return response.json();
}

export async function listThreads(session: AuthSession): Promise<ThreadSummary[]> {
  const response = await authedFetch('/api/threads', session);
  if (!response.ok) throw new Error('Failed to list threads');
  const data = await response.json() as { threads: ThreadSummary[] };
  return data.threads;
}

export async function deleteThread(session: AuthSession, threadId: string): Promise<void> {
  const response = await authedFetch(`/api/threads/${threadId}`, session, { method: 'DELETE' });
  if (!response.ok) throw new Error('Failed to delete thread');
}

export async function updateThreadGraph(session: AuthSession, threadId: string, graphData: GraphData): Promise<void> {
  let response: Response;
  try {
    response = await authedFetch(`/api/threads/${threadId}/graph`, session, {
      method: 'PUT',
      body: JSON.stringify({ graph_data: graphData }),
      signal: AbortSignal.timeout(15_000),
    });
  } catch (error) {
    if (error instanceof DOMException && (error.name === 'TimeoutError' || error.name === 'AbortError')) {
      throw new Error('Saving the diagram layout timed out. Check the saved diagram before retrying.');
    }
    throw error;
  }
  if (!response.ok) throw new Error('Failed to update thread graph');
}

export class GraphEditApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'GraphEditApiError';
    this.status = status;
  }
}

export async function saveGraphContentEdit(
  session: AuthSession,
  threadId: string,
  expectedVersion: string | null,
  edit: GraphContentEdit,
): Promise<GraphData> {
  let response: Response;
  try {
    response = await authedFetch(`/api/threads/${threadId}/graph`, session, {
      method: 'PATCH',
      body: JSON.stringify({ ...edit, expected_version: expectedVersion }),
      signal: AbortSignal.timeout(15_000),
    });
  } catch (error) {
    if (error instanceof DOMException && (error.name === 'TimeoutError' || error.name === 'AbortError')) {
      throw new Error('Saving the diagram timed out. Your edit is still open; check the saved diagram before retrying.');
    }
    throw error;
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: unknown } | null;
    const detail = typeof body?.detail === 'string' ? body.detail : null;
    const fallback: Record<number, string> = {
      404: 'This conversation no longer exists.',
      409: 'The diagram changed. Reload it before saving your edit.',
      413: 'The edited diagram is too large to save.',
      422: 'The diagram edit contains invalid values.',
    };
    throw new GraphEditApiError(detail ?? fallback[response.status] ?? 'Could not save diagram edit.', response.status);
  }
  const body = await response.json() as { graph_data?: GraphData };
  if (!body.graph_data || !Array.isArray(body.graph_data.nodes) || !Array.isArray(body.graph_data.edges)) {
    throw new Error('The diagram save returned an invalid graph.');
  }
  return body.graph_data;
}

export interface PrepareResponse {
  status: 'preparing' | 'ready';
  step?: string;
  detail?: string;
  progress?: {
    completed_units: number;
    total_units: number;
    percent: number;
  };
  faiss_loaded?: boolean;
}

export async function prepareBackend(): Promise<PrepareResponse> {
  const response = await fetch(`${API_BASE}/api/prepare`);
  const data = await response.json() as Record<string, unknown>;
  if (!response.ok) {
    const status = typeof data.status === 'string' ? data.status : 'preparing';
    if (response.status === 503 && status === 'preparing') {
      return data as unknown as PrepareResponse;
    }
    const detail = data.detail;
    const detailObject = detail !== null && typeof detail === 'object'
      ? detail as Record<string, unknown>
      : null;
    const step =
      typeof data.step === 'string'
        ? data.step
        : typeof detailObject?.step === 'string'
          ? detailObject.step
          : 'unknown';
    const message =
      typeof detail === 'string'
        ? detail
        : typeof detailObject?.status === 'string'
          ? detailObject.status
          : 'Backend is still warming up';
    const error = new Error(message || status) as Error & { step?: string };
    if (step) {
      error.step = step;
    }
    throw error;
  }
  return data as unknown as PrepareResponse;
}

export async function captureAnalyticsEvent(
  eventType: AnalyticsEventName,
  anonymousId: string,
  properties: AnalyticsEventProperties,
  session?: AuthSession | null,
): Promise<void> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (session) {
    headers.Authorization = `Bearer ${session.access_token}`;
  }
  const response = await fetch(`${API_BASE}/api/analytics/capture`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      anonymous_id: anonymousId,
      event_type: eventType,
      properties,
    }),
  });
  if (!response.ok) {
    throw new Error('Failed to capture analytics event');
  }
}

async function fetchInternal<T>(path: string, session: AuthSession): Promise<T> {
  const response = await authedFetch(path, session);
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail ?? 'Internal dashboard request failed');
  }
  return response.json() as Promise<T>;
}

export function fetchDashboardOverview(session: AuthSession): Promise<DashboardOverviewResponse> {
  return fetchInternal('/api/internal/dashboard/overview', session);
}

export function fetchDashboardTrends(
  session: AuthSession,
  bucket: 'day' | 'hour',
): Promise<DashboardTrendsResponse> {
  return fetchInternal(`/api/internal/dashboard/trends?bucket=${bucket}`, session);
}

export function fetchDashboardFunnel(session: AuthSession): Promise<DashboardFunnelResponse> {
  return fetchInternal('/api/internal/dashboard/funnel', session);
}

export function fetchDashboardFailures(session: AuthSession): Promise<DashboardFailuresResponse> {
  return fetchInternal('/api/internal/dashboard/failures', session);
}

export function fetchDashboardLLMPerformance(session: AuthSession): Promise<DashboardLLMPerformanceResponse> {
  return fetchInternal('/api/internal/dashboard/llm-performance', session);
}
