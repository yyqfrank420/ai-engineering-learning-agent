import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

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
    mocks.listThreads.mockResolvedValue([thread]);
    mocks.deleteThread.mockResolvedValue(undefined);
  });

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
});
