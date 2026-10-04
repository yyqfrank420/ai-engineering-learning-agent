import { createPortal } from 'react-dom';
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { ChatCircle, Plus, Trash, X } from '@phosphor-icons/react';
import './AppChrome.css';
import type { BackendReadiness } from '../../hooks/useBackendReadiness';
import type { AuthSession, ThreadSummary } from '../../types';
import { listThreads, deleteThread } from '../../services/api';

interface ThreadSidebarProps {
  authSession:     AuthSession | null;
  activeThreadId:  string | null;
  backendReadiness: BackendReadiness;
  onNewChat:       () => void;
  onSelectThread:  (threadId: string) => void;
  onDeleteThread:  (threadId: string) => void;
  isLoading:       boolean;
  isOpen:          boolean;
}

// Must match settings.max_threads_per_user in backend/config.py
const MAX_THREADS = 5;

// ── Date grouping helpers ─────────────────────────────────────────────────────

type Group = 'Today' | 'Yesterday' | 'This week' | 'Older';

function getGroup(dateStr: string): Group {
  const now  = new Date();
  const date = new Date(dateStr);

  const diffMs   = now.getTime() - date.getTime();
  const diffDays = diffMs / (1000 * 60 * 60 * 24);

  const todayStart     = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterdayStart = new Date(todayStart.getTime() - 86400 * 1000);

  if (date >= todayStart)     return 'Today';
  if (date >= yesterdayStart) return 'Yesterday';
  if (diffDays < 7)           return 'This week';
  return 'Older';
}

function groupThreads(threads: ThreadSummary[]): { label: Group; items: ThreadSummary[] }[] {
  const groups: Record<Group, ThreadSummary[]> = {
    Today:      [],
    Yesterday:  [],
    'This week': [],
    Older:      [],
  };
  for (const t of threads) {
    groups[getGroup(t.last_seen_at)].push(t);
  }
  const order: Group[] = ['Today', 'Yesterday', 'This week', 'Older'];
  return order
    .filter(g => groups[g].length > 0)
    .map(g => ({ label: g, items: groups[g] }));
}

// ── DeletePopup ───────────────────────────────────────────────────────────────
// Rendered via React portal at document.body so it escapes sidebar's
// overflow:hidden and can appear to the right of the sidebar at any viewport pos.

interface DeletePopupProps {
  onConfirm: () => void;
  onClose:   () => void;
  // Viewport-space anchor: right edge x, vertical center y of the trash button
  anchor:    { x: number; y: number };
}

function DeletePopup({ onConfirm, onClose, anchor }: DeletePopupProps) {
  const popupRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);

  useLayoutEffect(() => {
    const popup = popupRef.current;
    if (!popup) return;
    const { width, height } = popup.getBoundingClientRect();
    const left = Math.max(8, Math.min(anchor.x + 8, window.innerWidth - width - 8));
    const top = Math.max(8, Math.min(anchor.y - height / 2, window.innerHeight - height - 8));
    popup.style.left = `${left}px`;
    popup.style.top = `${top}px`;
    cancelRef.current?.focus();
  }, [anchor]);

  useEffect(() => {
    function handlePointerDown(event: PointerEvent) {
      if (popupRef.current && !popupRef.current.contains(event.target as Node)) onClose();
    }
    function handleViewportChange() { onClose(); }
    document.addEventListener('pointerdown', handlePointerDown);
    window.addEventListener('resize', handleViewportChange);
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown);
      window.removeEventListener('resize', handleViewportChange);
    };
  }, [onClose]);

  return createPortal(
    <div ref={popupRef} className="thread-delete-popup" role="dialog" aria-labelledby="delete-chat-question"
      onKeyDown={event => {
        if (event.key === 'Escape') {
          event.preventDefault();
          event.stopPropagation();
          onClose();
        }
        if (event.key === 'Tab') {
          const buttons = popupRef.current?.querySelectorAll('button');
          if (!buttons?.length) return;
          const next = event.shiftKey ? buttons[0] : buttons[buttons.length - 1];
          if (document.activeElement === next) {
            event.preventDefault();
            (event.shiftKey ? buttons[buttons.length - 1] : buttons[0]).focus();
          }
        }
      }}>
      <span id="delete-chat-question" className="thread-delete-popup__text">Permanently delete this chat?</span>
      <div className="thread-delete-popup__actions">
        <button type="button" onClick={onConfirm} className="chrome-button thread-delete-popup__confirm">Yes</button>
        <button type="button" ref={cancelRef} onClick={onClose} className="chrome-button" aria-label="Cancel deletion">
          <X size={16} aria-hidden="true" />
        </button>
      </div>
    </div>,
    document.body,
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

export function ThreadSidebar({
  authSession,
  activeThreadId,
  backendReadiness,
  onNewChat,
  onSelectThread,
  onDeleteThread,
  isLoading,
  isOpen,
}: ThreadSidebarProps) {
  const backendReady = backendReadiness === 'ready';
  const [threads, setThreads]           = useState<ThreadSummary[]>([]);
  const [fetching, setFetching]         = useState(false);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const deleteTriggerRef = useRef<HTMLButtonElement | null>(null);
  const newChatRef = useRef<HTMLButtonElement>(null);
  // Viewport coords of the trash button that opened the popup
  const [popupAnchor, setPopupAnchor]   = useState<{ x: number; y: number } | null>(null);

  // Stable refs — prevent fetchThreads from changing identity on every token refresh,
  // which would cause the effect below to fire repeatedly even with no real state change.
  const authSessionRef = useRef(authSession);
  const backendReadyRef = useRef(backendReady);
  const historyRequestRef = useRef(0);
  useEffect(() => {
    authSessionRef.current = authSession;
    backendReadyRef.current = backendReady;
  }, [authSession, backendReady]);

  const fetchThreads = useCallback(async () => {
    if (!authSessionRef.current || !backendReadyRef.current) return;
    const request = ++historyRequestRef.current;
    setFetching(true);
    try {
      const list = await listThreads(authSessionRef.current);
      if (request === historyRequestRef.current) setThreads(list);
    } catch {
      // Non-fatal — sidebar just stays empty
    } finally {
      if (request === historyRequestRef.current) setFetching(false);
    }
  }, []); // stable reference — never recreated

  // A draft first enters history when its completed turn is persisted.
  useEffect(() => {
    if (!isLoading) fetchThreads();
  }, [fetchThreads, activeThreadId, isLoading, backendReady, authSession?.user.id]);

  const handleDelete = useCallback(async (threadId: string) => {
    if (!authSession || isLoading) return;
    setConfirmingId(null);
    setPopupAnchor(null);
    try {
      await deleteThread(authSession, threadId);
      setThreads(prev => prev.filter(t => t.id !== threadId));
      onDeleteThread(threadId);
      newChatRef.current?.focus();
    } catch {
      // Non-fatal: the thread remains available.
      deleteTriggerRef.current?.focus();
    }
  }, [authSession, isLoading, onDeleteThread]);

  const closePopup = useCallback(() => {
    setConfirmingId(null);
    setPopupAnchor(null);
    deleteTriggerRef.current?.focus();
  }, []);

  const grouped = groupThreads(threads);

  return (
    <aside
      id="chat-history"
      className={`thread-sidebar ${isOpen ? 'thread-sidebar--open' : 'thread-sidebar--closed'}`}
      aria-label="Chat history"
      aria-hidden={!isOpen}
      inert={!isOpen}
    >
      <div className="thread-sidebar__inner">
        <button
          ref={newChatRef}
          type="button"
          className="thread-sidebar__new-chat"
          aria-label="New chat"
          onClick={onNewChat}
          disabled={isLoading || !authSession || !backendReady || threads.length >= MAX_THREADS}
        >
          <Plus size={18} aria-hidden="true" />
          New chat
        </button>
        {threads.length >= MAX_THREADS && (
          <div className="thread-sidebar__limit">Limit reached ({MAX_THREADS} chats)</div>
        )}
        <div className="thread-sidebar__history">
          {fetching && threads.length === 0 && <div className="thread-sidebar__empty" role="status">Loading…</div>}
          {!fetching && threads.length === 0 && (
            <div role="status" className="thread-sidebar__empty">
              <ChatCircle size={24} aria-hidden="true" />
              <span>{!authSession ? 'Sign in to view your chats'
                : backendReadiness === 'error' ? 'Could not connect to load chats'
                  : backendReady ? 'No chats yet' : 'Connecting to your chats…'}</span>
            </div>
          )}
          {grouped.map(group => (
            <section key={group.label} className="thread-sidebar__group" aria-label={group.label}>
              <h2 className="thread-sidebar__group-label">{group.label}</h2>
              {group.items.map(thread => {
                const isActive = thread.id === activeThreadId;
                const isConfirming = thread.id === confirmingId;
                return (
                  <div key={thread.id} className={`thread-sidebar__item${isActive ? ' thread-sidebar__item--active' : ''}${isConfirming ? ' thread-sidebar__item--confirming' : ''}`}>
                    <button
                      type="button"
                      className="thread-sidebar__select"
                      disabled={isLoading || !backendReady || isActive}
                      aria-current={isActive ? 'page' : undefined}
                      onClick={() => onSelectThread(thread.id)}
                      aria-label={`Open chat ${thread.title || 'New chat'}`}
                      title={thread.title || 'New chat'}
                    >
                      <ChatCircle size={16} aria-hidden="true" />
                      <span>{thread.title || 'New chat'}</span>
                    </button>
                    <button
                      type="button"
                      className="thread-sidebar__delete"
                      disabled={isLoading}
                      onClick={event => {
                        if (isConfirming) {
                          closePopup();
                        } else {
                          deleteTriggerRef.current = event.currentTarget;
                          const rect = event.currentTarget.getBoundingClientRect();
                          setPopupAnchor({ x: rect.right, y: rect.top + rect.height / 2 });
                          setConfirmingId(thread.id);
                        }
                      }}
                      aria-haspopup="dialog"
                      aria-expanded={isConfirming}
                      title="Delete chat"
                      aria-label={`Delete chat ${thread.title || 'New chat'}`}
                    >
                      <Trash size={16} aria-hidden="true" />
                    </button>
                  </div>
                );
              })}
            </section>
          ))}
        </div>
      </div>
      {isOpen && confirmingId && popupAnchor && (
        <DeletePopup onConfirm={() => handleDelete(confirmingId)} onClose={closePopup} anchor={popupAnchor} />
      )}
    </aside>
  );
}
