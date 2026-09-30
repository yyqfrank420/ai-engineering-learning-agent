// ─────────────────────────────────────────────────────────────────────────────
// File: frontend/src/services/agentTransport.ts
// Purpose: Agent transport client. Chat uses a bidirectional WebSocket so the
//          user can steer or stop active work; node suggestions retain the
//          small HTTP/SSE endpoint while it remains a one-shot request.
//          Authenticated requests include a Supabase bearer token and thread ID.
// Language: TypeScript
// Connects to: hooks/useAgentStream.ts (consumed via agentTransport singleton)
// Inputs:  VITE_API_URL env var (empty string = relative URL, proxied by Vite
//          dev server; set to full backend URL in production)
// Outputs: ServerEvent objects dispatched to registered handlers
// ─────────────────────────────────────────────────────────────────────────────

import type { AuthSession, DiagramLayoutReport, SendOptions, ServerEvent } from '../types';
import { API_BASE } from './config';

const PRE_START_CONNECT_RETRIES = 1;
const PRE_START_RETRY_DELAY_MS = 250;
const CHAT_HANDSHAKE_TIMEOUT_MS = 30_000;
// Older servers use a 940-second workflow deadline. Allow another minute
// for delivery when they do not advertise their configured deadline.
const DEFAULT_CHAT_TURN_TIMEOUT_MS = 1_000_000;

export class ChatTurnTimeoutError extends Error {
  constructor() {
    super('The connection timed out after the turn started.');
    this.name = 'ChatTurnTimeoutError';
  }
}

export interface StreamMeta {
  kind: 'chat' | 'node-selected';
  clientRequestId: string;
}

export type EventHandler = (event: ServerEvent, meta: StreamMeta) => void;

export function createClientRequestId(): string {
  return crypto.randomUUID();
}

function dispatchSSEChunk(chunk: string, handlers: EventHandler[], meta: StreamMeta): boolean {
  const line = chunk.trim();
  if (!line.startsWith('data: ')) return false;

  try {
    const event = JSON.parse(line.slice(6)) as ServerEvent;
    handlers.forEach(handler => handler(event, meta));
    return event.type === 'done';
  } catch {
    console.error('[sse] Failed to parse event:', line);
    return false;
  }
}

/**
 * Read an SSE stream from a fetch Response and dispatch each event to handlers.
 *
 * SSE wire format:
 *   data: <json>\n\n
 *
 * We split on double-newlines rather than using EventSource because EventSource
 * only supports GET requests.
 */
async function consumeSSEStream(response: Response, handlers: EventHandler[], meta: StreamMeta): Promise<boolean> {
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
  }
  if (!response.body) {
    throw new Error('Response has no body');
  }

  const reader  = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer    = '';
  let sawDone   = false;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    // stream: true tells the decoder this chunk may be mid-codepoint
    buffer += decoder.decode(value, { stream: true });

    // SSE events are delimited by a blank line. Accept both LF and CRLF framing.
    const chunks = buffer.split(/\r?\n\r?\n/);
    buffer = chunks.pop()!;  // last element is the incomplete trailing chunk

    for (const chunk of chunks) {
      sawDone = dispatchSSEChunk(chunk, handlers, meta) || sawDone;
    }
  }

  if (buffer.trim()) {
    sawDone = dispatchSSEChunk(buffer, handlers, meta) || sawDone;
  }

  return sawDone;
}

export class AgentTransport {
  private eventHandlers: EventHandler[] = [];
  private _chatSocket: WebSocket | null = null;
  private _chatClientRequestId: string | null = null;
  private _chatCommandsReady = false;
  private _pendingSteers: string[] = [];
  private _cancelChatRequest: (() => void) | null = null;
  private _cancelPendingChatRetry: (() => void) | null = null;
  private _nodeAbortController: AbortController | null = null;
  private _nodeClientRequestId: string | null = null;

  /**
   * WS /api/chat/ws — runs one bidirectional, steerable agent turn.
   * Authentication is the first frame, keeping bearer credentials out of URLs.
   */
  async sendMessage(
    session: AuthSession,
    threadId: string,
    content: string,
    opts?: SendOptions,
    clientRequestId = createClientRequestId(),
  ): Promise<boolean> {
    if (this._chatSocket) {
      this.stopGeneration(this._chatClientRequestId ?? undefined);
    }
    this._chatClientRequestId = clientRequestId;
    this._chatCommandsReady = false;
    this._pendingSteers = [];

    return await new Promise<boolean>((resolve, reject) => {
      let settled = false;
      let watchdog: number | null = null;
      const clearWatchdog = () => {
        if (watchdog !== null) window.clearTimeout(watchdog);
        watchdog = null;
      };

      const settle = (socket: WebSocket, value: boolean, error?: Error) => {
        if (settled) return;
        settled = true;
        clearWatchdog();
        if (this._chatSocket === socket) {
          this._cancelChatRequest = null;
          this._chatSocket = null;
          this._chatClientRequestId = null;
          this._chatCommandsReady = false;
        }
        if (error) reject(error);
        else resolve(value);
      };

      const connect = (attempt: number) => {
        const socket = new WebSocket(websocketUrl('/api/chat/ws'));
        this._chatSocket = socket;
        this._cancelChatRequest = () => settle(socket, false);
        this._chatCommandsReady = false;
        let sawDone = false;
        let startSent = false;
        let retryScheduled = false;

        const retryBeforeStart = () => {
          if (
            settled
            || retryScheduled
            || startSent
            || attempt >= PRE_START_CONNECT_RETRIES
            || this._chatSocket !== socket
          ) {
            return false;
          }
          retryScheduled = true;
          clearWatchdog();
          socket.onerror = null;
          socket.onclose = null;
          socket.close(1000, 'Retrying pre-start connection');
          const retryTimer = window.setTimeout(() => {
            if (this._cancelPendingChatRetry === cancelRetry) {
              this._cancelPendingChatRetry = null;
            }
            if (!settled && this._chatSocket === socket && this._chatClientRequestId === clientRequestId) {
              connect(attempt + 1);
            } else {
              settle(socket, false);
            }
          }, PRE_START_RETRY_DELAY_MS);
          // The failed socket's close handler is detached, so stopping during
          // the retry delay must settle the request without waiting for close.
          const cancelRetry = () => {
            window.clearTimeout(retryTimer);
            settle(socket, false);
          };
          this._cancelPendingChatRetry = cancelRetry;
          return true;
        };

        const armWatchdog = (delay: number) => {
          clearWatchdog();
          watchdog = window.setTimeout(() => {
            if (settled || retryScheduled || this._chatSocket !== socket) return;
            if (!startSent && retryBeforeStart()) return;
            settle(socket, false, startSent
              ? new ChatTurnTimeoutError()
              : new Error('Connection timed out before the response could start. Please try again.'));
            socket.close(1000, 'Connection timed out');
          }, delay);
        };
        armWatchdog(CHAT_HANDSHAKE_TIMEOUT_MS);

        socket.onopen = () => {
          if (settled || retryScheduled || this._chatSocket !== socket) return;
          socket.send(JSON.stringify({ type: 'auth', access_token: session.access_token }));
        };
        socket.onmessage = (message) => {
          if (settled || retryScheduled || this._chatSocket !== socket) return;
          try {
            const event = JSON.parse(String(message.data)) as ServerEvent | { type: 'ready'; turn_timeout_ms?: unknown };
            if (event.type === 'ready') {
              if (!startSent && this._chatSocket === socket) {
                startSent = true;
                const advertisedTimeout = event.turn_timeout_ms;
                const turnTimeout = typeof advertisedTimeout === 'number'
                  && Number.isSafeInteger(advertisedTimeout)
                  && advertisedTimeout > 0
                  && advertisedTimeout <= 2_147_483_647
                  ? advertisedTimeout
                  : DEFAULT_CHAT_TURN_TIMEOUT_MS;
                armWatchdog(turnTimeout);
                socket.send(JSON.stringify({
                  type: 'start',
                  thread_id: threadId,
                  content,
                  complexity: opts?.complexity ?? 'auto',
                  graph_mode: opts?.graphMode ?? 'on',
                  ...(opts?.diagramRequested ? { diagram_requested: true } : {}),
                  research_enabled: opts?.researchEnabled ?? false,
                  ...(opts?.graphAction ? { graph_action: opts.graphAction } : {}),
                  ...(opts?.expectedGraphVersion !== undefined ? { expected_graph_version: opts.expectedGraphVersion } : {}),
                  ...(opts?.retrySourceRequestId ? { retry_source_request_id: opts.retrySourceRequestId } : {}),
                  ...(opts?.steeringUpdates?.length ? { steering_updates: opts.steeringUpdates } : {}),
                  client_request_id: clientRequestId,
                }));
                this._chatCommandsReady = true;
                for (const steering of this._pendingSteers.splice(0)) {
                  socket.send(JSON.stringify({
                    type: 'steer',
                    content: steering,
                    client_request_id: clientRequestId,
                  }));
                }
              }
              return;
            }
            this.eventHandlers.forEach(handler => handler(event, { kind: 'chat', clientRequestId }));
            if (event.type === 'done') {
              sawDone = true;
              socket.close(1000, 'Complete');
              settle(socket, true);
            }
          } catch {
            console.error('[ws] Failed to parse event:', message.data);
          }
        };
        socket.onerror = () => {
          if (settled || retryScheduled || this._chatSocket !== socket) return;
          if (!retryBeforeStart()) {
            settle(socket, false, new Error('WebSocket connection failed'));
            socket.close(1000, 'Connection failed');
          }
        };
        socket.onclose = () => {
          if (settled || retryScheduled || this._chatSocket !== socket) return;
          if (!retryBeforeStart()) settle(socket, sawDone);
        };
      };

      connect(0);
    });
  }

  isChatActive(): boolean {
    return !!this._chatSocket && (
      this._chatSocket.readyState === WebSocket.CONNECTING ||
      this._chatSocket.readyState === WebSocket.OPEN
    );
  }

  steerGeneration(content: string): boolean {
    if (!this.isChatActive() || !this._chatSocket) return false;
    if (this._chatSocket.readyState === WebSocket.CONNECTING || !this._chatCommandsReady) {
      this._pendingSteers.push(content);
      return true;
    }
    this._chatSocket.send(JSON.stringify({
      type: 'steer',
      content,
      client_request_id: this._chatClientRequestId,
    }));
    return true;
  }

  acceptPreview(clientRequestId: string, graphVersion: string): boolean {
    const socket = this._chatSocket;
    if (!socket || socket.readyState !== WebSocket.OPEN || !this._chatCommandsReady
      || this._chatClientRequestId !== clientRequestId) return false;
    socket.send(JSON.stringify({
      type: 'accept_preview', client_request_id: clientRequestId, graph_version: graphVersion,
    }));
    return true;
  }

  /** Cancel server-side work over the active command channel. */
  stopGeneration(clientRequestId?: string): boolean {
    const socket = this._chatSocket;
    if (!socket) return false;
    if (clientRequestId && this._chatClientRequestId !== clientRequestId) return false;
    const activeRequestId = this._chatClientRequestId;
    const cancelRequest = this._cancelChatRequest;
    this._cancelChatRequest = null;
    const commandsReady = this._chatCommandsReady;
    const cancelPendingRetry = this._cancelPendingChatRetry;
    this._cancelPendingChatRetry = null;
    this._chatSocket = null;
    this._chatClientRequestId = null;
    this._chatCommandsReady = false;
    this._pendingSteers = [];
    cancelPendingRetry?.();
    cancelRequest?.();
    if (socket.readyState === WebSocket.OPEN && commandsReady) {
      socket.send(JSON.stringify({ type: 'stop', client_request_id: activeRequestId }));
      window.setTimeout(() => socket.close(1000, 'Stopped by user'), 750);
    } else {
      socket.close(1000, 'Stopped by user');
    }
    return true;
  }

  /** Return a browser-rendered candidate to the waiting LangGraph quality gate. */
  submitDiagramEvaluation(
    evaluationId: string,
    graphVersion: string | null | undefined,
    report: DiagramLayoutReport,
    screenshotDataUrl: string,
  ): boolean {
    const socket = this._chatSocket;
    if (!socket || socket.readyState !== WebSocket.OPEN) return false;
    const match = screenshotDataUrl.match(/^data:(image\/(?:jpeg|png));base64,(.+)$/);
    if (!match) return false;
    const [, mediaType, encoded] = match;
    const chunkSize = 8_000;
    const chunks: string[] = [];
    for (let offset = 0; offset < encoded.length; offset += chunkSize) {
      chunks.push(encoded.slice(offset, offset + chunkSize));
    }
    socket.send(JSON.stringify({
      type: 'diagram_evaluation_start',
      evaluation_id: evaluationId,
      graph_version: graphVersion ?? null,
      media_type: mediaType,
      total_chunks: chunks.length,
      report,
    }));
    chunks.forEach((data, index) => {
      socket.send(JSON.stringify({
        type: 'diagram_evaluation_chunk',
        evaluation_id: evaluationId,
        index,
        data,
      }));
    });
    socket.send(JSON.stringify({
      type: 'diagram_evaluation_complete',
      evaluation_id: evaluationId,
    }));
    return true;
  }

  /**
   * POST /api/node-selected — generates suggested questions for a graph node.
   * Streams a suggested_questions event then a done event.
   */
  async sendNodeSelected(
    session: AuthSession,
    threadId: string,
    nodeId: string,
    title: string,
    description: string,
    clientRequestId = createClientRequestId(),
  ): Promise<boolean> {
    this.cancelNodeSelection();
    const controller = new AbortController();
    this._nodeAbortController = controller;
    this._nodeClientRequestId = clientRequestId;
    try {
      const response = await fetch(`${API_BASE}/api/node-selected`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${session.access_token}`,
        },
        body: JSON.stringify({
          thread_id: threadId,
          node_id: nodeId,
          title,
          description,
          client_request_id: clientRequestId,
        }),
        signal: controller.signal,
      });
      return await consumeSSEStream(response, this.eventHandlers, {
        kind: 'node-selected',
        clientRequestId,
      });
    } finally {
      if (this._nodeAbortController === controller) {
        this._nodeAbortController = null;
        this._nodeClientRequestId = null;
      }
    }
  }

  cancelNodeSelection(clientRequestId?: string): boolean {
    if (!this._nodeAbortController) return false;
    if (clientRequestId && this._nodeClientRequestId !== clientRequestId) return false;
    const controller = this._nodeAbortController;
    this._nodeAbortController = null;
    this._nodeClientRequestId = null;
    controller.abort();
    return true;
  }

  async useSearchTool(session: AuthSession, threadId: string, requestId: string): Promise<{ ok: boolean; status: string }> {
    const response = await fetch(`${API_BASE}/api/chat/use-search-tool`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${session.access_token}`,
      },
      body: JSON.stringify({
        thread_id: threadId,
        request_id: requestId,
      }),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    return response.json();
  }

  /** Register a handler that fires for every SSE event, across all requests. */
  onEvent(handler: EventHandler): () => void {
    this.eventHandlers.push(handler);
    return () => {
      this.eventHandlers = this.eventHandlers.filter(h => h !== handler);
    };
  }
}

// Module-level singleton — one transport coordinator for the app lifetime.
export const agentTransport = new AgentTransport();

function websocketUrl(path: string): string {
  const httpUrl = new URL(`${API_BASE}${path}`, window.location.origin);
  httpUrl.protocol = httpUrl.protocol === 'https:' ? 'wss:' : 'ws:';
  return httpUrl.toString();
}
