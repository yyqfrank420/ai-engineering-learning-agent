import type { GraphData, Message, ThreadDetail } from '../types';
import { parseMessageActivity } from './messageActivity';
import { normalizeGraphData } from './graphData';

export function storageKeyForThread(userId: string) {
  return `active-thread:${userId}`;
}

export type ThreadSnapshot = {
  threadId?: string | null;
  title: string;
  messages: Message[];
  graphData: GraphData | null;
};

export function storageKeyForThreadSnapshot(userId: string, threadId: string) {
  return `thread-snapshot:${userId}:${threadId}`;
}

export function readThreadSnapshot(userId: string, threadId: string): ThreadSnapshot | null {
  try {
    const raw = localStorage.getItem(storageKeyForThreadSnapshot(userId, threadId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as ThreadSnapshot;
    if (!Array.isArray(parsed.messages)) return null;
    return {
      threadId: parsed.threadId ?? threadId,
      title: parsed.title || 'New chat',
      messages: parsed.messages.map(message => ({
        ...message,
        isStreaming: false,
        activity: message.role === 'assistant' ? parseMessageActivity(message.activity) : undefined,
      })),
      graphData: normalizeGraphData(parsed.graphData ?? null),
    };
  } catch {
    return null;
  }
}

export function writeThreadSnapshot(userId: string, threadId: string, snapshot: ThreadSnapshot): void {
  localStorage.setItem(
    storageKeyForThreadSnapshot(userId, threadId),
    JSON.stringify({
      ...snapshot,
      graphData: normalizeGraphData(snapshot.graphData),
    }),
  );
}

export function shouldPersistThreadSnapshot(
  liveSnapshot: ThreadSnapshot,
  baselineSnapshot: ThreadSnapshot,
): boolean {
  const liveHasGraph = liveSnapshot.graphData !== null;
  const baselineHasGraph = baselineSnapshot.graphData !== null;

  // During app bootstrap or post-deploy prepare, the live stream state can be
  // momentarily empty before hydrateThread() replays the cached thread. Never
  // overwrite a richer cached snapshot with that transient empty state.
  if (liveSnapshot.messages.length < baselineSnapshot.messages.length) {
    return false;
  }
  if (!liveHasGraph && baselineHasGraph) {
    return false;
  }
  return true;
}

export function clearThreadSnapshot(userId: string, threadId: string): void {
  localStorage.removeItem(storageKeyForThreadSnapshot(userId, threadId));
}

export function mapThreadMessages(messages: ThreadDetail['messages']): Message[] {
  return messages.map(message => ({
    id: message.id,
    role: message.role,
    content: message.content,
    graphRevisionId: message.graph_revision_id ?? null,
    activity: message.role === 'assistant' ? parseMessageActivity(message.activity) : undefined,
    clientRequestId: message.client_request_id ?? null,
    retryRequest: message.retry_request ? {
      content: message.retry_request.content,
      complexity: message.retry_request.complexity,
      graphMode: message.retry_request.graph_mode,
      diagramRequested: message.retry_request.diagram_requested,
      researchEnabled: message.retry_request.research_enabled,
      graphAction: message.retry_request.graph_action,
      expectedGraphVersion: message.retry_request.expected_graph_version,
    } : undefined,
    isStreaming: false,
  }));
}
