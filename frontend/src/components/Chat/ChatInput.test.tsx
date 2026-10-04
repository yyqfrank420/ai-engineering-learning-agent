import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ChatInput } from './ChatInput';

const defaultProps = {
  onSend: vi.fn(),
  onStop: vi.fn(),
  onRetryReadiness: vi.fn(),
  threadId: 'thread-1' as string | null,
  disabled: false,
  sendDisabled: false,
  backendReadiness: 'ready' as const,
  retryDisabled: false,
  readinessMessage: null as string | null,
  isGenerating: false,
  selectionSuggestion: null as string | null,
  selectionReferenceActive: false,
};

function renderInput(threadId: string | null, overrides = {}) {
  return render(
    <ChatInput
      {...defaultProps}
      {...overrides}
      threadId={threadId}
    />,
  );
}

describe('ChatInput', () => {
  it('sends broad requests immediately without options or a diagram-choice dialog', () => {
    const onSend = vi.fn();
    renderInput('thread-1', { onSend });
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'AI trading bot?' } });
    const send = screen.getByRole('button', { name: 'Send message' });
    expect(send.querySelector('svg')).toBeTruthy();
    expect(send.textContent).toBe('');
    fireEvent.click(send);
    expect(onSend).toHaveBeenCalledExactlyOnceWith('AI trading bot?');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Message options' })).toBeNull();
  });

  it.each(['ask', 'send', 'answer'] as const)('automatically submits the server intent %s without a dialog', async action => {
    const onSend = vi.fn();
    renderInput('thread-1', { onSend, checkSubmission: vi.fn().mockResolvedValue(action) });
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'My request' } });
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
    await waitFor(() => expect(onSend).toHaveBeenCalledExactlyOnceWith('My request', action));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it.each(['send', 'answer', 'extend', 'new_chat'] as const)('preserves the classified %s action for an existing diagram', async action => {
    const onSend = vi.fn();
    renderInput('thread-1', { hasGraph: true, onSend, checkSubmission: vi.fn().mockResolvedValue(action) });
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'My request' } });
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
    await waitFor(() => expect(onSend).toHaveBeenCalledExactlyOnceWith('My request', action));
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('');
  });

  it.each(['click', 'Enter'] as const)('sends an ambiguous existing-diagram follow-up when %s is used again', async trigger => {
    const onSend = vi.fn();
    const checkSubmission = vi.fn().mockResolvedValue('ask');
    renderInput('thread-1', { hasGraph: true, onSend, checkSubmission });
    const input = screen.getByRole('textbox') as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: '  How should I read this diagram?  ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
    await screen.findByRole('group', { name: 'Where to continue' });
    expect(onSend).not.toHaveBeenCalled();
    if (trigger === 'click') fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
    else fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => expect(onSend).toHaveBeenCalledExactlyOnceWith('How should I read this diagram?', 'answer'));
    expect(checkSubmission).toHaveBeenCalledExactlyOnceWith('How should I read this diagram?');
    expect(input.value).toBe('');
    expect(screen.queryByRole('group', { name: 'Where to continue' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Extend this diagram' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Start a new chat' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Dismiss' })).toBeNull();
  });

  it('sends after dismissing choices without reopening them or repeating intent classification', async () => {
    const onSend = vi.fn();
    const checkSubmission = vi.fn().mockResolvedValue('ask');
    renderInput('thread-1', { hasGraph: true, onSend, checkSubmission });
    const input = screen.getByRole('textbox') as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: 'Explain this diagram' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Dismiss' }));
    expect(input.value).toBe('Explain this diagram');
    expect(screen.queryByRole('group', { name: 'Where to continue' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
    await waitFor(() => expect(onSend).toHaveBeenCalledExactlyOnceWith('Explain this diagram', 'answer'));
    expect(checkSubmission).toHaveBeenCalledOnce();
    expect(input.value).toBe('');
    expect(screen.queryByRole('group', { name: 'Where to continue' })).toBeNull();
  });

  it.each(['visible', 'dismissed'] as const)('keeps steering unclassified when generation starts with %s choices', async status => {
    const onSend = vi.fn();
    const checkSubmission = vi.fn().mockResolvedValue('ask');
    const view = renderInput('thread-1', { hasGraph: true, onSend, checkSubmission });
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Focus on the arrows' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
    await screen.findByRole('group', { name: 'Where to continue' });
    if (status === 'dismissed') fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
    view.rerender(<ChatInput {...defaultProps} threadId="thread-1" hasGraph isGenerating onSend={onSend} checkSubmission={checkSubmission} />);
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
    expect(onSend).toHaveBeenCalledExactlyOnceWith('Focus on the arrows');
    expect(checkSubmission).toHaveBeenCalledOnce();
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('');
  });

  it.each(['draft', 'thread'] as const)('checks intent again after %s changes following dismissal', async change => {
    const onSend = vi.fn();
    const checkSubmission = vi.fn().mockResolvedValue('ask');
    const view = renderInput('thread-1', { hasGraph: true, onSend, checkSubmission });
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Old question' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Dismiss' }));
    if (change === 'thread') {
      view.rerender(<ChatInput {...defaultProps} threadId="thread-2" hasGraph onSend={onSend} checkSubmission={checkSubmission} />);
    }
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'New question' } });
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
    await screen.findByRole('group', { name: 'Where to continue' });
    expect(checkSubmission).toHaveBeenCalledTimes(2);
    expect(checkSubmission).toHaveBeenLastCalledWith('New question');
    expect(onSend).not.toHaveBeenCalled();
  });

  it.each([
    ['Extend this diagram', 'extend'],
    ['Start a new chat', 'new_chat'],
  ] as const)('retains the explicit %s action', async (label, action) => {
    const onSend = vi.fn();
    const checkSubmission = vi.fn().mockResolvedValue('ask');
    renderInput('thread-1', { hasGraph: true, onSend, checkSubmission });
    const input = screen.getByRole('textbox') as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: 'My request' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
    fireEvent.click(await screen.findByRole('button', { name: label }));
    await waitFor(() => expect(onSend).toHaveBeenCalledExactlyOnceWith('My request', action));
    expect(checkSubmission).toHaveBeenCalledOnce();
    expect(input.value).toBe('');
  });

  it('blocks duplicate unresolved sends and retains an ambiguous follow-up for retry after rejection', async () => {
    let reject!: (error: Error) => void;
    const onSend = vi.fn()
      .mockImplementationOnce(() => new Promise<void>((_, fail) => { reject = fail; }))
      .mockResolvedValueOnce(undefined);
    const checkSubmission = vi.fn().mockResolvedValue('ask');
    renderInput('thread-1', { hasGraph: true, onSend, checkSubmission });
    const input = screen.getByRole('textbox') as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: 'Explain the arrows' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
    await screen.findByRole('group', { name: 'Where to continue' });
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => expect(onSend).toHaveBeenCalledExactlyOnceWith('Explain the arrows', 'answer'));
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(checkSubmission).toHaveBeenCalledOnce();
    expect(onSend).toHaveBeenCalledOnce();
    expect(input.value).toBe('Explain the arrows');
    await act(async () => reject(new Error('Send was not accepted.')));
    expect(screen.getByRole('alert').textContent).toBe('Send was not accepted.');
    expect(input.value).toBe('Explain the arrows');
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(2));
    expect(onSend).toHaveBeenLastCalledWith('Explain the arrows', 'answer');
    expect(checkSubmission).toHaveBeenCalledOnce();
    expect(input.value).toBe('');
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('keeps the draft when classified new-chat creation fails and blocks duplicate submission', async () => {
    let reject!: (error: Error) => void;
    const onSend = vi.fn(() => new Promise<void>((_, fail) => { reject = fail; }));
    const checkSubmission = vi.fn().mockResolvedValue('new_chat');
    renderInput('thread-1', { hasGraph: true, onSend, checkSubmission });
    const input = screen.getByRole('textbox') as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: 'Separate topic' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
    await waitFor(() => expect(onSend).toHaveBeenCalledExactlyOnceWith('Separate topic', 'new_chat'));
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onSend).toHaveBeenCalledOnce();
    expect(checkSubmission).toHaveBeenCalledOnce();
    await act(async () => reject(new Error('Could not create a new chat.')));
    expect(screen.getByRole('alert').textContent).toContain('Could not create');
    expect(input.value).toBe('Separate topic');
  });

  it('retains a new-chat draft through its own thread handoff until send is accepted', async () => {
    let reject!: (error: Error) => void;
    const onSend = vi.fn(() => new Promise<void>((_, fail) => { reject = fail; }));
    const checkSubmission = vi.fn().mockResolvedValue('new_chat');
    const view = renderInput('thread-1', { onSend, checkSubmission });
    fireEvent.change(screen.getByRole('textbox'), {target:{value:'Keep until accepted'}});
    fireEvent.click(screen.getByRole('button', {name:'Send message'}));
    await waitFor(() => expect(onSend).toHaveBeenCalledOnce());
    view.rerender(<ChatInput {...defaultProps} threadId="created-thread" onSend={onSend} checkSubmission={checkSubmission} />);
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('Keep until accepted');
    await act(async () => reject(new Error('Send was not accepted.')));
    expect(screen.getByRole('alert').textContent).toBe('Send was not accepted.');
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('Keep until accepted');
  });

  it('keeps the draft and reports a connection failure when intent checking fails', async () => {
    const onSend = vi.fn();
    renderInput('thread-1', { onSend, checkSubmission: vi.fn().mockRejectedValue(new Error('offline')) });
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Keep my question' } });
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
    expect((await screen.findByRole('alert')).textContent).toContain('offline');
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('Keep my question');
    expect(onSend).not.toHaveBeenCalled();
  });

  it.each(['draft', 'disabled', 'sendDisabled', 'thread', 'unmount'] as const)('ignores an intent response after %s changes', async change => {
    let resolve!: (action: 'ask') => void;
    const onSend = vi.fn();
    const checkSubmission = () => new Promise<'ask'>(done => { resolve = done; });
    const view = renderInput('thread-1', { onSend, checkSubmission });
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Old question' } });
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
    if (change === 'draft') fireEvent.change(screen.getByRole('textbox'), { target: { value: 'New question' } });
    else if (change === 'unmount') view.unmount();
    else view.rerender(<ChatInput {...defaultProps} onSend={onSend} checkSubmission={checkSubmission}
      disabled={change === 'disabled'} sendDisabled={change === 'sendDisabled'} threadId={change === 'thread' ? 'thread-2' : 'thread-1'} />);
    await act(async () => resolve('ask'));
    expect(onSend).not.toHaveBeenCalled();
  });

  it('preserves the draft when bootstrapping from no thread to the first active thread', () => {
    const view = renderInput(null);
    const input = screen.getByPlaceholderText('Ask a question…');

    fireEvent.change(input, { target: { value: 'why is send disabled?' } });

    view.rerender(
      <ChatInput
        {...defaultProps}
        threadId="thread-1"
      />,
    );

    expect((screen.getByPlaceholderText('Ask a question…') as HTMLTextAreaElement).value).toBe('why is send disabled?');
  });

  it('clears the draft when switching between real threads', () => {
    const view = renderInput('thread-1');
    const input = screen.getByPlaceholderText('Ask a question…');

    fireEvent.change(input, { target: { value: 'carry this over' } });

    view.rerender(
      <ChatInput
        {...defaultProps}
        threadId="thread-2"
      />,
    );

    expect((screen.getByPlaceholderText('Ask a question…') as HTMLTextAreaElement).value).toBe('');
  });

  it('sends trimmed content on Enter and clears the draft', () => {
    const onSend = vi.fn();
    renderInput('thread-1', { onSend });
    const input = screen.getByPlaceholderText('Ask a question…');

    fireEvent.change(input, { target: { value: '  explain agents  ' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    expect(onSend).toHaveBeenCalledWith('explain agents');
    expect((input as HTMLTextAreaElement).value).toBe('');
  });

  it('sends via the button and reports draft changes', () => {
    const onSend = vi.fn();
    const onDraftChange = vi.fn();
    renderInput('thread-1', { onSend, onDraftChange });
    const input = screen.getByPlaceholderText('Ask a question…');

    fireEvent.change(input, { target: { value: '  explain evals  ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }));

    expect(onDraftChange).toHaveBeenCalledWith(true);
    expect(onDraftChange).toHaveBeenLastCalledWith(false);
    expect(onSend).toHaveBeenCalledWith('explain evals');
    expect((input as HTMLTextAreaElement).value).toBe('');
  });

  it('does not send empty disabled or backend-blocked drafts', () => {
    const onSend = vi.fn();
    const { rerender } = renderInput('thread-1', { onSend });
    const input = screen.getByPlaceholderText('Ask a question…');

    fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
    expect(onSend).not.toHaveBeenCalled();

    fireEvent.change(input, { target: { value: 'blocked' } });
    rerender(<ChatInput {...defaultProps} threadId="thread-1" disabled onSend={onSend} />);
    fireEvent.keyDown(screen.getByPlaceholderText('Ask a question…'), { key: 'Enter' });
    expect(onSend).not.toHaveBeenCalled();

    rerender(<ChatInput {...defaultProps} threadId="thread-1" sendDisabled onSend={onSend} />);
    fireEvent.change(screen.getByPlaceholderText('Ask a question…'), { target: { value: 'blocked' } });
    fireEvent.keyDown(screen.getByPlaceholderText('Ask a question…'), { key: 'Enter' });
    expect(onSend).not.toHaveBeenCalled();
  });

  it('keeps newline behavior for Shift+Enter', () => {
    const onSend = vi.fn();
    renderInput('thread-1', { onSend });
    const input = screen.getByPlaceholderText('Ask a question…');

    fireEvent.change(input, { target: { value: 'line one' } });
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true });

    expect(onSend).not.toHaveBeenCalled();
  });

  it('shows stop button while generating', () => {
    const onStop = vi.fn();
    renderInput('thread-1', { isGenerating: true, onStop });

    const button = screen.getByRole('button', { name: 'Stop generation' });
    fireEvent.mouseEnter(button);
    expect(button.style.background).toBe('rgba(248, 81, 73, 0.2)');
    fireEvent.mouseLeave(button);
    expect(button.style.background).toBe('rgba(248, 81, 73, 0.1)');
    fireEvent.click(button);

    expect(onStop).toHaveBeenCalled();
  });

  it('keeps the composer active and submits steering while generating', () => {
    const onSend = vi.fn();
    renderInput('thread-1', { isGenerating: true, onSend });
    const input = screen.getByPlaceholderText('Add a follow-up…');

    fireEvent.change(input, { target: { value: 'focus on the approval boundary' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }));

    expect(onSend).toHaveBeenCalledWith('focus on the approval boundary');
    expect((input as HTMLTextAreaElement).value).toBe('');
    expect(screen.getByRole('button', { name: 'Stop generation' })).toBeTruthy();
  });

  it('disables repeated Stop requests while the accepted diagram is finishing', () => {
    const onStop = vi.fn();
    renderInput('thread-1', { isGenerating: true, isFinishingDiagram: true, onStop });
    const button = screen.getByRole('button', { name: 'Finishing diagram' }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.textContent).toBe('Finishing…');
    fireEvent.click(button);
    expect(onStop).not.toHaveBeenCalled();
  });

  it('preserves focus feedback', () => {
    renderInput('thread-1');
    const input = screen.getByRole('textbox');
    fireEvent.focus(input);
    expect(input.style.borderColor).toBe('rgba(167, 139, 250, 0.5)');
    fireEvent.blur(input);
    expect(input.style.borderColor).toBe('rgba(255, 255, 255, 0.08)');
  });

  it('keeps the send arrow disabled and announces automatic startup milestones', () => {
    const onSend = vi.fn();
    renderInput('thread-1', {
      backendReadiness: 'preparing',
      readinessMessage: 'Loading the retrieval index…',
      onSend,
    });
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Keep my draft' } });
    expect(screen.getByRole('status').textContent).toContain('Loading the retrieval index…');
    expect(screen.queryByRole('progressbar')).toBeNull();
    expect(screen.getByRole('status').textContent).not.toContain('%');
    expect(screen.getByRole('status').querySelector('.chat-readiness-spinner')?.getAttribute('aria-hidden')).toBe('true');
    expect((screen.getByRole('button', { name: 'Send message' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByRole('button', { name: /prepare|retry/i })).toBeNull();
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
    expect(onSend).not.toHaveBeenCalled();
  });

  it('shows Retry only for an explicit readiness error and preserves the draft across recovery', () => {
    const onRetryReadiness = vi.fn();
    const view = renderInput('thread-1', { backendReadiness: 'error', readinessMessage: 'Connection failed.', onRetryReadiness });
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Saved draft' } });
    expect(screen.getByRole('alert').textContent).toBe('Connection failed.');
    expect(view.container.querySelector('.chat-readiness-spinner')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Retry connection' }));
    expect(onRetryReadiness).toHaveBeenCalledOnce();
    view.rerender(<ChatInput {...defaultProps} backendReadiness="preparing" />);
    expect(screen.queryByRole('button', { name: 'Retry connection' })).toBeNull();
    expect(screen.getByRole('status').textContent).toBe('Connecting…');
    expect(view.container.querySelector('.chat-readiness-spinner')).not.toBeNull();
    view.rerender(<ChatInput {...defaultProps} />);
    expect(view.container.querySelector('.chat-readiness-spinner')).toBeNull();
    expect(screen.queryByRole('status')).toBeNull();
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('Saved draft');
    expect((screen.getByRole('button', { name: 'Send message' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('honors disabled retry without inferring state from message text', () => {
    const onRetryReadiness = vi.fn();
    const view = renderInput('thread-1', { backendReadiness: 'error', retryDisabled: true, onRetryReadiness });
    fireEvent.click(screen.getByRole('button', { name: 'Retry connection' }));
    expect(onRetryReadiness).not.toHaveBeenCalled();
    view.rerender(<ChatInput {...defaultProps} backendReadiness="preparing" readinessMessage="Temporarily unavailable" />);
    expect(screen.queryByRole('button', { name: 'Retry connection' })).toBeNull();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('keeps an empty composer at one row when highlighted context changes', () => {
    const view = renderInput('thread-1');
    const input = screen.getByRole('textbox') as HTMLTextAreaElement;
    view.rerender(<ChatInput {...defaultProps} selectionSuggestion="Selected paragraph" selectionReferenceActive />);
    expect(input.placeholder).toBe('Ask a question about the highlighted text…');
    expect(input.rows).toBe(1);
    expect(input.style.whiteSpace).toBe('nowrap');
    expect(input.style.textOverflow).toBe('ellipsis');
    expect(input.style.height).toBe('auto');
    Object.defineProperty(input, 'scrollHeight', { configurable: true, get: () => 100 });
    fireEvent.change(input, { target: { value: 'A draft' } });
    expect(input.style.height).toBe('100px');
    fireEvent.change(input, { target: { value: '' } });
    expect(input.style.height).toBe('auto');
    expect(input.style.whiteSpace).toBe('nowrap');
    expect(input.style.overflow).toBe('hidden');
  });

  it('grows for draft content with borders and caps long drafts with scrolling', () => {
    renderInput('thread-1', { selectionSuggestion: 'Selected paragraph', selectionReferenceActive: true });
    const input = screen.getByRole('textbox') as HTMLTextAreaElement;
    Object.defineProperties(input, {
      scrollHeight: { configurable: true, get: () => input.style.whiteSpace === 'nowrap' ? 37 : 58 },
      offsetHeight: { configurable: true, get: () => 39 },
      clientHeight: { configurable: true, get: () => 37 },
    });
    fireEvent.change(input, { target: { value: 'Line one\nLine two' } });
    expect(input.style.height).toBe('60px');
    expect(input.style.whiteSpace).toBe('');
    expect(input.style.overflow).toBe('auto');
    Object.defineProperty(input, 'scrollHeight', { get: () => 180 });
    fireEvent.change(input, { target: { value: 'Line one\nLine two\nLine three' } });
    expect(input.style.height).toBe('120px');
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(input.value).toBe('');
    expect(input.style.height).toBe('auto');
  });

  it('handles highlighted text suggestion lifecycle', () => {
    const onUseSelection = vi.fn();
    const onDismissSelection = vi.fn();
    const onClearSelectionReference = vi.fn();
    renderInput('thread-1', {
      selectionSuggestion: 'Selected paragraph',
      selectionReferenceActive: true,
      onUseSelection,
      onDismissSelection,
      onClearSelectionReference,
    });

    expect(screen.getByPlaceholderText('Ask a question about the highlighted text…')).toBeTruthy();
    fireEvent.click(screen.getByText('Referenced'));
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss highlighted text' }));
    fireEvent.focus(screen.getByPlaceholderText('Ask a question about the highlighted text…'));

    expect(onUseSelection).toHaveBeenCalled();
    expect(onDismissSelection).toHaveBeenCalled();
    expect(onClearSelectionReference).toHaveBeenCalled();
  });

  it('activates highlighted text when typing before reference is active', () => {
    const onUseSelection = vi.fn();
    renderInput('thread-1', {
      selectionSuggestion: 'Selected paragraph',
      selectionReferenceActive: false,
      onUseSelection,
    });

    fireEvent.change(screen.getByPlaceholderText('Ask a question about the highlighted text…'), {
      target: { value: 'compare this' },
    });

    expect(onUseSelection).toHaveBeenCalled();
  });
});
