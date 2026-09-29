import { useCallback, useEffect, useRef, useState } from 'react';
import type { BackendReadiness } from '../../hooks/useBackendReadiness';
import type { AuthSession, ThreadSummary } from '../../types';
import { listThreads, deleteThread } from '../../services/api';
import './ThreadSidebar.css';

interface ThreadSidebarProps {
  authSession: AuthSession | null;
  activeThreadId: string | null;
  backendReadiness: BackendReadiness;
  onNewChat: () => void;
  onSelectThread: (threadId: string) => void;
  onDeleteThread: (threadId: string) => void;
  onClose?: () => void;
  isLoading: boolean;
  isOpen: boolean;
}

// Matches settings.max_threads_per_user in backend/config.py.
const MAX_THREADS = 5;
export const HISTORY_OVERLAY_QUERY = '(max-width: 1279px)';

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

export function ThreadSidebar({ authSession, activeThreadId, backendReadiness,
  onNewChat, onSelectThread, onDeleteThread, onClose, isLoading, isOpen }: ThreadSidebarProps) {
  const backendReady = backendReadiness === 'ready';
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [fetching, setFetching] = useState(false);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [isDrawer, setIsDrawer] = useState(() => window.matchMedia?.(HISTORY_OVERLAY_QUERY).matches ?? false);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const deleteButtonRef = useRef<HTMLButtonElement | null>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const query = window.matchMedia?.(HISTORY_OVERLAY_QUERY);
    if (!query) return;
    const handleChange = () => setIsDrawer(query.matches);
    query.addEventListener('change', handleChange);
    return () => query.removeEventListener('change', handleChange);
  }, []);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    // A single mounted dialog preserves history state across viewport changes.
    const activeElement = document.activeElement as HTMLElement | null;
    const focused = dialog.contains(activeElement) ? activeElement : null;
    if (dialog.open) dialog.close();
    if (isOpen) {
      if (isDrawer) dialog.showModal();
      // The open attribute keeps the inline rail visible without dialog autofocus.
      else dialog.setAttribute('open', '');
      focused?.focus();
    }
  }, [isOpen, isDrawer]);

  useEffect(() => {
    const dialog = dialogRef.current;
    return () => { if (dialog?.open) dialog.close(); };
  }, []);

  useEffect(() => {
    if (confirmingId) cancelRef.current?.focus();
  }, [confirmingId]);

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
    try {
      await deleteThread(authSession, threadId);
      setThreads(prev => prev.filter(t => t.id !== threadId));
      onDeleteThread(threadId);
    } catch {
      // Non-fatal — thread stays in list
    }
  }, [authSession, isLoading, onDeleteThread]);

  const closePopup = useCallback(() => {
    setConfirmingId(null);
  }, []);

  const grouped = groupThreads(threads);
  const newChatDisabled = isLoading || !authSession || !backendReady || threads.length >= MAX_THREADS;

  return (
    <dialog ref={dialogRef} id="chat-history" aria-label="Chat history"
      aria-modal={isDrawer ? true : undefined}
      className={`thread-sidebar ${isDrawer ? 'thread-sidebar--drawer' : 'thread-sidebar--inline'} ${isOpen ? 'thread-sidebar--open' : 'thread-sidebar--closed'}`}
      onCancel={event => {
        event.preventDefault();
        if (confirmingId) { closePopup(); deleteButtonRef.current?.focus(); }
        else onClose?.();
      }}
      onClick={event => {
        if (!isDrawer || event.target !== event.currentTarget) return;
        const rect = event.currentTarget.getBoundingClientRect();
        if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) onClose?.();
      }}>
      <div className="thread-sidebar__inner">
        <div className="thread-sidebar__heading">
          <h2>Chat history</h2>
          {isDrawer && <button type="button" className="thread-sidebar__close" aria-label="Close chat history" onClick={onClose} autoFocus>
            <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>
          </button>}
        </div>
        <button type="button" className="thread-sidebar__new" aria-label="New chat" disabled={newChatDisabled} onClick={onNewChat}>
          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M12 5v14M5 12h14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>
          New chat
        </button>
        {threads.length >= MAX_THREADS && <p className="thread-sidebar__limit">Limit reached ({MAX_THREADS} chats)</p>}
        <div className="thread-sidebar__list">
          {fetching && threads.length === 0 && <p className="thread-sidebar__empty">Loading…</p>}
          {!fetching && threads.length === 0 && <p role="status" className="thread-sidebar__empty">
            {!authSession ? 'Sign in to view your chats' : backendReadiness === 'error' ? 'Could not connect to load chats'
              : backendReady ? 'No chats yet' : 'Connecting to your chats…'}
          </p>}
          {grouped.map(group => <section key={group.label} aria-label={group.label}>
            <h3 className="thread-sidebar__group">{group.label}</h3>
            {group.items.map(thread => <div key={thread.id}>
              <div className={`thread-sidebar__row ${thread.id === activeThreadId ? 'thread-sidebar__row--active' : ''}`}>
                <button type="button" className="thread-sidebar__select" disabled={isLoading || !backendReady || thread.id === activeThreadId}
                  aria-current={thread.id === activeThreadId ? 'page' : undefined}
                  aria-label={`Open chat ${thread.title || 'New chat'}`} onClick={() => onSelectThread(thread.id)}>{thread.title || 'New chat'}</button>
                <button type="button" className="thread-sidebar__delete" disabled={isLoading}
                  aria-label={`Delete chat ${thread.title || 'New chat'}`} aria-expanded={confirmingId === thread.id}
                  onClick={event => { deleteButtonRef.current = event.currentTarget; setConfirmingId(confirmingId === thread.id ? null : thread.id); }}>
                  <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 10v7M14 10v7" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" /></svg>
                </button>
              </div>
              {confirmingId === thread.id && <div role="group" aria-label={`Confirm deletion of ${thread.title || 'New chat'}`} className="thread-sidebar__confirmation"
                onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); closePopup(); deleteButtonRef.current?.focus(); } }}>
                <p>Permanently delete this chat?</p>
                <div><button type="button" className="thread-sidebar__confirm" disabled={isLoading} onClick={() => handleDelete(thread.id)}>Delete</button>
                  <button type="button" ref={cancelRef} onClick={() => { closePopup(); deleteButtonRef.current?.focus(); }}>Cancel</button></div>
              </div>}
            </div>)}
          </section>)}
        </div>
      </div>
    </dialog>
  );
}
