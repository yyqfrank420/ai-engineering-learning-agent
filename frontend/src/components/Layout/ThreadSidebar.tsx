import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { BackendReadiness } from '../../hooks/useBackendReadiness';
import type { AuthSession, ThreadSummary } from '../../types';
import { listThreads, deleteThread } from '../../services/api';
import { ChatCircle, Plus, Trash, X } from '@phosphor-icons/react';
import './AppChrome.css';
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
  const newChatRef = useRef<HTMLButtonElement>(null);
  const pendingNewChatFocusRef = useRef(false);
  const confirmationRef = useRef<HTMLDivElement>(null);

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
      pendingNewChatFocusRef.current = true;
      setThreads(prev => prev.filter(t => t.id !== threadId));
      onDeleteThread(threadId);
    } catch {
      // The failed deletion leaves the thread available.
      deleteButtonRef.current?.focus();
    }
  }, [authSession, isLoading, onDeleteThread]);

  const closePopup = useCallback(() => {
    setConfirmingId(null);
    deleteButtonRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!confirmingId) return;
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!confirmationRef.current?.contains(target) && !deleteButtonRef.current?.contains(target)) closePopup();
    };
    const handleResize = () => closePopup();
    document.addEventListener('pointerdown', handlePointerDown);
    window.addEventListener('resize', handleResize);
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown);
      window.removeEventListener('resize', handleResize);
    };
  }, [confirmingId, closePopup]);

  const grouped = groupThreads(threads);
  const newChatDisabled = isLoading || !authSession || !backendReady || threads.length >= MAX_THREADS;

  useLayoutEffect(() => {
    if (!pendingNewChatFocusRef.current) return;
    if (!isOpen || !authSession || !backendReady) {
      pendingNewChatFocusRef.current = false;
      return;
    }
    if (newChatDisabled) return;
    pendingNewChatFocusRef.current = false;
    newChatRef.current?.focus();
  }, [threads, newChatDisabled, isOpen, authSession, backendReady]);

  useEffect(() => {
    const handleFocusIn = (event: FocusEvent) => {
      const target = event.target;
      if (pendingNewChatFocusRef.current && target instanceof HTMLElement && target.isConnected
        && target !== newChatRef.current && target.matches('button, input, textarea, select, a[href], [tabindex]')) {
        pendingNewChatFocusRef.current = false;
      }
    };
    document.addEventListener('focusin', handleFocusIn);
    return () => document.removeEventListener('focusin', handleFocusIn);
  }, []);

  return (
    <dialog ref={dialogRef} id="chat-history" aria-label="Chat history"
      aria-modal={isDrawer ? true : undefined}
      inert={!isOpen} aria-hidden={!isOpen}
      className={`thread-sidebar ${isDrawer ? 'thread-sidebar--drawer' : 'thread-sidebar--inline'} ${isOpen ? 'thread-sidebar--open' : 'thread-sidebar--closed'}`}
      onCancel={event => {
        event.preventDefault();
        if (confirmingId) closePopup();
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
            <X size={20} aria-hidden="true" />
          </button>}
        </div>
        <button type="button" ref={newChatRef} className="thread-sidebar__new-chat" aria-label="New chat" disabled={newChatDisabled} onClick={onNewChat}>
          <Plus size={18} aria-hidden="true" />
          New chat
        </button>
        {threads.length >= MAX_THREADS && <p className="thread-sidebar__limit">Limit reached ({MAX_THREADS} chats)</p>}
        <div className="thread-sidebar__list">
          {fetching && threads.length === 0 && <p role="status" className="thread-sidebar__empty">Loading…</p>}
          {!fetching && threads.length === 0 && <p role="status" className="thread-sidebar__empty">
            {!authSession ? 'Sign in to view your chats' : backendReadiness === 'error' ? 'Could not connect to load chats'
              : backendReady ? 'No chats yet' : 'Connecting to your chats…'}
          </p>}
          {grouped.map(group => <section key={group.label} aria-label={group.label} className="thread-sidebar__group">
            <h3 className="thread-sidebar__group-label">{group.label}</h3>
            {group.items.map(thread => <div key={thread.id}>
              <div className={`thread-sidebar__item ${thread.id === activeThreadId ? 'thread-sidebar__item--active' : ''} ${confirmingId === thread.id ? 'thread-sidebar__item--confirming' : ''}`}>
                <button type="button" className="thread-sidebar__select" disabled={isLoading || !backendReady || thread.id === activeThreadId}
                  aria-current={thread.id === activeThreadId ? 'page' : undefined}
                  aria-label={`Open chat ${thread.title || 'New chat'}`} onClick={() => onSelectThread(thread.id)}><ChatCircle size={16} aria-hidden="true" /><span>{thread.title || 'New chat'}</span></button>
                <button type="button" className="thread-sidebar__delete" disabled={isLoading}
                  aria-label={`Delete chat ${thread.title || 'New chat'}`} aria-haspopup="dialog" aria-expanded={confirmingId === thread.id}
                  onClick={event => { deleteButtonRef.current = event.currentTarget; setConfirmingId(confirmingId === thread.id ? null : thread.id); }}>
                  <Trash size={16} aria-hidden="true" />
                </button>
              </div>
              {/* Native modal history requires its confirmation to stay in the same top layer. */}
              {confirmingId === thread.id && <div ref={confirmationRef} role="dialog" aria-labelledby="delete-chat-question" className="thread-sidebar__confirmation"
                onKeyDown={event => {
                  if (event.key === 'Escape') {
                    event.preventDefault();
                    event.stopPropagation();
                    closePopup();
                  } else if (event.key === 'Tab') {
                    const buttons = event.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)');
                    const first = buttons[0];
                    const last = buttons[buttons.length - 1];
                    if (event.shiftKey && document.activeElement === first) {
                      event.preventDefault();
                      last?.focus();
                    } else if (!event.shiftKey && document.activeElement === last) {
                      event.preventDefault();
                      first?.focus();
                    }
                  }
                }}>
                <p id="delete-chat-question">Permanently delete this chat?</p>
                <div><button type="button" className="chrome-button thread-sidebar__confirm" disabled={isLoading} onClick={() => handleDelete(thread.id)}>Yes</button>
                  <button type="button" className="chrome-button" ref={cancelRef} aria-label="Cancel deletion" onClick={closePopup}><X size={16} aria-hidden="true" />Cancel</button></div>
              </div>}
            </div>)}
          </section>)}
        </div>
      </div>
    </dialog>
  );
}
