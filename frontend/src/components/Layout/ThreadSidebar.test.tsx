import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { AuthSession } from '../../types';

const mocks = vi.hoisted(() => ({
  listThreads: vi.fn(),
  deleteThread: vi.fn(),
}));

vi.mock('../../services/api', () => ({
  listThreads: mocks.listThreads,
  deleteThread: mocks.deleteThread,
}));

import { ThreadSidebar } from './ThreadSidebar';

const session: AuthSession = {
  access_token: 'token',
  refresh_token: 'refresh',
  user: { id: 'user-1', email: 'user@example.com' },
};

const thread = {
  id: 'thread-2',
  title: 'Support architecture',
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  last_seen_at: new Date().toISOString(),
};

function renderSidebar(isLoading: boolean, onSelectThread = vi.fn()) {
  return render(
    <ThreadSidebar
      authSession={session}
      activeThreadId="thread-1"
      backendReadiness="ready"
      onNewChat={vi.fn()}
      onSelectThread={onSelectThread}
      onDeleteThread={vi.fn()}
      isLoading={isLoading}
      isOpen
    />,
  );
}

describe('ThreadSidebar active-work protection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(HTMLDialogElement.prototype, 'show');
    vi.spyOn(HTMLDialogElement.prototype, 'showModal');
    mocks.listThreads.mockResolvedValue([thread]);
    mocks.deleteThread.mockResolvedValue(undefined);
  });

  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it.each([
    ['unknown', 'Connecting to your chats…'],
    ['preparing', 'Connecting to your chats…'],
    ['error', 'Could not connect to load chats'],
  ] as const)('shows %s readiness without a manual startup instruction', (backendReadiness, message) => {
    render(<ThreadSidebar authSession={session} activeThreadId={null} backendReadiness={backendReadiness}
      onNewChat={vi.fn()} onSelectThread={vi.fn()} onDeleteThread={vi.fn()} isLoading={false} isOpen />);
    expect(screen.getByRole('status').textContent).toBe(message);
    expect(screen.queryByText(/Prepare backend/)).toBeNull();
    expect((screen.getByRole('button', { name: 'New chat' }) as HTMLButtonElement).disabled).toBe(true);
    expect(mocks.listThreads).not.toHaveBeenCalled();
  });

  it('asks a signed-out user to sign in without starting a history request', () => {
    render(<ThreadSidebar authSession={null} activeThreadId={null} backendReadiness="unknown"
      onNewChat={vi.fn()} onSelectThread={vi.fn()} onDeleteThread={vi.fn()} isLoading={false} isOpen />);
    expect(screen.getByRole('status').textContent).toBe('Sign in to view your chats');
    expect(mocks.listThreads).not.toHaveBeenCalled();
  });

  it('blocks selecting or deleting another thread while work is active', async () => {
    const onSelectThread = vi.fn();
    const view = renderSidebar(false, onSelectThread);
    const select = await screen.findByRole('button', { name: 'Open chat Support architecture' });
    view.rerender(<ThreadSidebar authSession={session} activeThreadId="thread-1" backendReadiness="ready"
      onNewChat={vi.fn()} onSelectThread={onSelectThread} onDeleteThread={vi.fn()} isLoading isOpen />);
    const remove = screen.getByRole('button', { name: 'Delete chat Support architecture' });
    expect((select as HTMLButtonElement).disabled).toBe(true);
    expect((remove as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(select);
    fireEvent.click(remove);
    expect(onSelectThread).not.toHaveBeenCalled();
    expect(mocks.deleteThread).not.toHaveBeenCalled();
  });

  it('allows selecting another thread after work becomes idle', async () => {
    const onSelectThread = vi.fn();
    const view = renderSidebar(true, onSelectThread);

    view.rerender(
      <ThreadSidebar
        authSession={session}
        activeThreadId="thread-1"
        backendReadiness="ready"
        onNewChat={vi.fn()}
        onSelectThread={onSelectThread}
        onDeleteThread={vi.fn()}
        isLoading={false}
        isOpen
      />,
    );
    const select = await screen.findByRole('button', { name: 'Open chat Support architecture' });
    await waitFor(() => expect((select as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(select);
    expect(onSelectThread).toHaveBeenCalledWith('thread-2');
  });

  it('keeps empty drafts out of history and refreshes after their first completed turn', async () => {
    mocks.listThreads.mockResolvedValue([]);
    const props = { authSession: session, activeThreadId: 'draft', backendReadiness: 'ready' as const,
      onNewChat: vi.fn(), onSelectThread: vi.fn(), onDeleteThread: vi.fn(), isLoading: false, isOpen: true };
    const view = render(<ThreadSidebar {...props} />);
    await screen.findByText('No chats yet');
    expect(screen.queryByRole('button', { name: 'Open chat New chat' })).toBeNull();
    expect((screen.getByRole('button', { name: 'New chat' }) as HTMLButtonElement).disabled).toBe(false);

    view.rerender(<ThreadSidebar {...props} isLoading />);
    mocks.listThreads.mockResolvedValue([{ ...thread, id: 'draft' }]);
    view.rerender(<ThreadSidebar {...props} />);
    await screen.findByRole('button', { name: 'Open chat Support architecture' });
    expect(screen.queryByText('No chats yet')).toBeNull();
  });

  it('ignores an older empty-history response after a completed chat has appeared', async () => {
    let finishOldRequest!: (value: typeof thread[]) => void;
    mocks.listThreads.mockReturnValueOnce(new Promise(resolve => { finishOldRequest = resolve; }));
    const props = { authSession: session, activeThreadId: 'draft', backendReadiness: 'ready' as const,
      onNewChat: vi.fn(), onSelectThread: vi.fn(), onDeleteThread: vi.fn(), isLoading: false, isOpen: true };
    const view = render(<ThreadSidebar {...props} />);
    view.rerender(<ThreadSidebar {...props} isLoading />);
    view.rerender(<ThreadSidebar {...props} />);
    await screen.findByRole('button', { name: 'Open chat Support architecture' });
    await act(async () => finishOldRequest([]));
    expect(screen.getByRole('button', { name: 'Open chat Support architecture' })).toBeTruthy();
  });
  it('opens compact history as a modal and requests close on Escape and backdrop', async () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    const onClose = vi.fn();
    const props = { authSession: session, activeThreadId: 'thread-1', backendReadiness: 'ready' as const,
      onNewChat: vi.fn(), onSelectThread: vi.fn(), onDeleteThread: vi.fn(), onClose, isLoading: false, isOpen: true };
    const view = render(<ThreadSidebar {...props} />);
    const dialog = screen.getByRole('dialog', { name: 'Chat history' });
    expect(HTMLDialogElement.prototype.showModal).toHaveBeenCalled();
    fireEvent(dialog, new Event('cancel', { cancelable: true }));
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.click(dialog, { clientX: 500 });
    expect(onClose).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole('button', { name: 'Close chat history' }));
    expect(onClose).toHaveBeenCalledTimes(3);
    await screen.findByRole('button', { name: 'Open chat Support architecture' });
    view.rerender(<ThreadSidebar {...props} isOpen={false} />);
    expect(screen.queryByRole('dialog', { name: 'Chat history' })).toBeNull();
    view.rerender(<ThreadSidebar {...props} />);
    expect(screen.getByRole('button', { name: 'Open chat Support architecture' })).toBeTruthy();
    expect(mocks.listThreads).toHaveBeenCalledTimes(1);
  });

  it('returns confirmation focus to the delete control and only deletes after confirmation', async () => {
    const onDeleteThread = vi.fn();
    render(<ThreadSidebar authSession={session} activeThreadId="thread-1" backendReadiness="ready"
      onNewChat={vi.fn()} onSelectThread={vi.fn()} onDeleteThread={onDeleteThread} isLoading={false} isOpen />);
    const remove = await screen.findByRole('button', { name: 'Delete chat Support architecture' });
    fireEvent.click(remove);
    const cancel = screen.getByRole('button', { name: 'Cancel deletion' });
    expect(document.activeElement).toBe(cancel);
    fireEvent.keyDown(cancel, { key: 'Escape' });
    expect(document.activeElement).toBe(remove);
    expect(screen.queryByRole('dialog', { name: 'Permanently delete this chat?' })).toBeNull();
    expect(mocks.deleteThread).not.toHaveBeenCalled();
    fireEvent.click(remove);
    fireEvent.click(screen.getByRole('button', { name: 'Yes' }));
    await waitFor(() => expect(onDeleteThread).toHaveBeenCalledWith(thread.id));
    expect(mocks.deleteThread).toHaveBeenCalledWith(session, thread.id);
    expect(screen.queryByRole('button', { name: 'Open chat Support architecture' })).toBeNull();
  });

  it('keeps desktop opening from taking focus away from the conversation', async () => {
    const outside = document.createElement('button');
    document.body.append(outside);
    outside.focus();
    renderSidebar(false);
    await screen.findByRole('button', { name: 'Open chat Support architecture' });
    expect(document.activeElement).toBe(outside);
    expect(HTMLDialogElement.prototype.showModal).not.toHaveBeenCalled();
    outside.remove();
  });

  it('keeps new-chat and thread selection callbacks available in compact history', async () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    const onNewChat = vi.fn();
    const onSelectThread = vi.fn();
    render(<ThreadSidebar authSession={session} activeThreadId="thread-1" backendReadiness="ready"
      onNewChat={onNewChat} onSelectThread={onSelectThread} onDeleteThread={vi.fn()} onClose={vi.fn()} isLoading={false} isOpen />);
    const select = await screen.findByRole('button', { name: 'Open chat Support architecture' });
    fireEvent.click(select);
    fireEvent.click(screen.getByRole('button', { name: 'New chat' }));
    expect(onSelectThread).toHaveBeenCalledWith(thread.id);
    expect(onNewChat).toHaveBeenCalledTimes(1);
  });

  it.each([false, true])('focuses cancellation and returns focus to the delete trigger on Escape (drawer=%s)', async isDrawer => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: isDrawer, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    renderSidebar(false);
    const trigger = await screen.findByRole('button', { name: 'Delete chat Support architecture' });
    trigger.focus();
    fireEvent.click(trigger, { detail: 0 });
    const popup = screen.getByRole('dialog', { name: 'Permanently delete this chat?' });
    const cancel = screen.getByRole('button', { name: 'Cancel deletion' });
    expect(document.activeElement).toBe(cancel);
    expect(trigger.getAttribute('aria-expanded')).toBe('true');

    fireEvent.keyDown(cancel, { key: 'Tab' });
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Yes' }));
    fireEvent.keyDown(document.activeElement!, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(cancel);
    fireEvent.keyDown(popup, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: 'Permanently delete this chat?' })).toBeNull();
    expect(document.activeElement).toBe(trigger);
    expect(trigger.getAttribute('aria-expanded')).toBe('false');
    expect(mocks.deleteThread).not.toHaveBeenCalled();
  });

  it.each([false, true])('returns focus to the trigger when cancellation is selected (drawer=%s)', async isDrawer => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: isDrawer, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    renderSidebar(false);
    const trigger = await screen.findByRole('button', { name: 'Delete chat Support architecture' });
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole('button', { name: 'Cancel deletion' }));
    expect(screen.queryByRole('dialog', { name: 'Permanently delete this chat?' })).toBeNull();
    expect(document.activeElement).toBe(trigger);
    expect(mocks.deleteThread).not.toHaveBeenCalled();
  });

  it('makes closed history inert and marks the selected chat', async () => {
    const props = { authSession: session, activeThreadId: thread.id, backendReadiness: 'ready' as const,
      onNewChat: vi.fn(), onSelectThread: vi.fn(), onDeleteThread: vi.fn(), isLoading: false, isOpen: true };
    const view = render(<ThreadSidebar {...props} />);
    const selected = await screen.findByRole('button', { name: 'Open chat Support architecture' });
    expect(selected.getAttribute('aria-current')).toBe('page');
    view.rerender(<ThreadSidebar {...props} isOpen={false} />);
    const history = view.container.querySelector('#chat-history');
    expect(history?.getAttribute('aria-hidden')).toBe('true');
    expect(history?.hasAttribute('inert')).toBe(true);
    expect(screen.queryByRole('button', { name: 'New chat' })).toBeNull();
  });

  it.each([false, true])('focuses New chat after successful deletion (drawer=%s)', async isDrawer => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: isDrawer, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    renderSidebar(false);
    fireEvent.click(await screen.findByRole('button', { name: 'Delete chat Support architecture' }));
    fireEvent.click(screen.getByRole('button', { name: 'Yes' }));
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('button', { name: 'New chat' })));
    expect(screen.queryByRole('button', { name: 'Open chat Support architecture' })).toBeNull();
  });

  it.each([false, true])('returns focus to the trigger after failed deletion (drawer=%s)', async isDrawer => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: isDrawer, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    mocks.deleteThread.mockRejectedValueOnce(new Error('Deletion failed'));
    renderSidebar(false);
    const trigger = await screen.findByRole('button', { name: 'Delete chat Support architecture' });
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole('button', { name: 'Yes' }));
    await waitFor(() => expect(document.activeElement).toBe(trigger));
    expect(screen.getByRole('button', { name: 'Open chat Support architecture' })).toBeTruthy();
  });

  it.each([false, true])('dismisses confirmation on an outside pointer and restores focus (drawer=%s)', async isDrawer => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: isDrawer, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    renderSidebar(false);
    const trigger = await screen.findByRole('button', { name: 'Delete chat Support architecture' });
    fireEvent.click(trigger);
    const confirmation = screen.getByRole('dialog', { name: 'Permanently delete this chat?' });
    fireEvent.pointerDown(confirmation);
    fireEvent.pointerDown(trigger);
    expect(screen.getByRole('dialog', { name: 'Permanently delete this chat?' })).toBe(confirmation);
    fireEvent.pointerDown(screen.getByRole('button', { name: 'New chat' }));
    expect(screen.queryByRole('dialog', { name: 'Permanently delete this chat?' })).toBeNull();
    expect(document.activeElement).toBe(trigger);
    expect(mocks.deleteThread).not.toHaveBeenCalled();
  });

  it.each([false, true])('dismisses confirmation on resize and restores focus (drawer=%s)', async isDrawer => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: isDrawer, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    renderSidebar(false);
    const trigger = await screen.findByRole('button', { name: 'Delete chat Support architecture' });
    fireEvent.click(trigger);
    fireEvent(window, new Event('resize'));
    expect(screen.queryByRole('dialog', { name: 'Permanently delete this chat?' })).toBeNull();
    expect(document.activeElement).toBe(trigger);
    expect(mocks.deleteThread).not.toHaveBeenCalled();
  });

  it('exposes loading history as a status', () => {
    mocks.listThreads.mockReturnValueOnce(new Promise(() => {}));
    renderSidebar(false);
    expect(screen.getByRole('status').textContent).toBe('Loading…');
  });

  it.each([false, true])('focuses New chat after deleting from five histories (drawer=%s)', async isDrawer => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: isDrawer, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    mocks.listThreads.mockResolvedValue([
      thread,
      ...Array.from({ length: 4 }, (_, index) => ({ ...thread, id: `saved-${index}`, title: `Saved chat ${index}` })),
    ]);
    renderSidebar(false);
    const trigger = await screen.findByRole('button', { name: 'Delete chat Support architecture' });
    const newChat = screen.getByRole('button', { name: 'New chat' }) as HTMLButtonElement;
    expect(newChat.disabled).toBe(true);
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole('button', { name: 'Yes' }));
    await waitFor(() => {
      expect(newChat.disabled).toBe(false);
      expect(document.activeElement).toBe(newChat);
    });
    expect(screen.queryByRole('button', { name: 'Open chat Support architecture' })).toBeNull();
  });

  it.each([false, true])('retains deletion focus while the active-thread change loads (drawer=%s)', async isDrawer => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: isDrawer, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    const onDeleteThread = vi.fn();
    const props = { authSession: session, activeThreadId: thread.id, backendReadiness: 'ready' as const,
      onNewChat: vi.fn(), onSelectThread: vi.fn(), onDeleteThread };
    const view = render(<ThreadSidebar {...props} isLoading={false} isOpen />);
    onDeleteThread.mockImplementation(() => {
      mocks.listThreads.mockResolvedValue([]);
      view.rerender(<ThreadSidebar {...props} isLoading isOpen />);
    });
    fireEvent.click(await screen.findByRole('button', { name: 'Delete chat Support architecture' }));
    fireEvent.click(screen.getByRole('button', { name: 'Yes' }));
    await waitFor(() => expect(props.onDeleteThread).toHaveBeenCalledWith(thread.id));
    const newChat = screen.getByRole('button', { name: 'New chat' }) as HTMLButtonElement;
    expect(newChat.disabled).toBe(true);
    expect(document.activeElement).not.toBe(newChat);
    view.rerender(<ThreadSidebar {...props} isLoading={false} isOpen />);
    await waitFor(() => expect(document.activeElement).toBe(newChat));
  });

  it.each([false, true])('cancels pending deletion focus when history closes before ready (drawer=%s)', async isDrawer => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: isDrawer, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    const onDeleteThread = vi.fn();
    const props = { authSession: session, activeThreadId: thread.id, backendReadiness: 'ready' as const,
      onNewChat: vi.fn(), onSelectThread: vi.fn(), onDeleteThread };
    const view = render(<ThreadSidebar {...props} isLoading={false} isOpen />);
    onDeleteThread.mockImplementation(() => {
      mocks.listThreads.mockResolvedValue([]);
      view.rerender(<ThreadSidebar {...props} isLoading isOpen />);
    });
    fireEvent.click(await screen.findByRole('button', { name: 'Delete chat Support architecture' }));
    fireEvent.click(screen.getByRole('button', { name: 'Yes' }));
    await waitFor(() => expect(props.onDeleteThread).toHaveBeenCalledWith(thread.id));
    view.rerender(<ThreadSidebar {...props} isLoading isOpen={false} />);
    view.rerender(<ThreadSidebar {...props} isLoading={false} isOpen />);
    expect(document.activeElement).not.toBe(screen.getByRole('button', { name: 'New chat' }));
  });

  it.each([false, true])('preserves a chosen control focus while deletion finishes (drawer=%s)', async isDrawer => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: isDrawer, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    const onDeleteThread = vi.fn();
    const props = { authSession: session, activeThreadId: thread.id, backendReadiness: 'ready' as const,
      onNewChat: vi.fn(), onSelectThread: vi.fn(), onDeleteThread };
    const view = render(<ThreadSidebar {...props} isLoading={false} isOpen />);
    onDeleteThread.mockImplementation(() => {
      mocks.listThreads.mockResolvedValue([]);
      view.rerender(<ThreadSidebar {...props} isLoading isOpen />);
    });
    fireEvent.click(await screen.findByRole('button', { name: 'Delete chat Support architecture' }));
    fireEvent.click(screen.getByRole('button', { name: 'Yes' }));
    await waitFor(() => expect(props.onDeleteThread).toHaveBeenCalledWith(thread.id));
    const chosen = isDrawer ? screen.getByRole('button', { name: 'Close chat history' }) : document.createElement('button');
    if (!isDrawer) document.body.append(chosen);
    chosen.focus();
    view.rerender(<ThreadSidebar {...props} isLoading={false} isOpen />);
    expect(document.activeElement).toBe(chosen);
    if (!isDrawer) chosen.remove();
  });

});
