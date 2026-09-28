import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ChatInput } from './ChatInput';

const defaultProps = {
  onSend: vi.fn(),
  onStop: vi.fn(),
  onPrepare: vi.fn(),
  threadId: 'thread-1' as string | null,
  disabled: false,
  sendDisabled: false,
  showPrepare: false,
  prepareDisabled: false,
  prepareMessage: null as string | null,
  prepareProgress: null,
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
    await waitFor(() => expect(onSend).toHaveBeenCalledExactlyOnceWith('My request', action === 'ask'));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('keeps the draft and reports a connection failure when intent checking fails', async () => {
    const onSend = vi.fn();
    renderInput('thread-1', { onSend, checkSubmission: vi.fn().mockRejectedValue(new Error('offline')) });
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Keep my question' } });
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
    expect((await screen.findByRole('alert')).textContent).toContain('Could not connect');
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

  it('preserves focus feedback', () => {
    renderInput('thread-1');
    const input = screen.getByRole('textbox');
    fireEvent.focus(input);
    expect(input.style.borderColor).toBe('rgba(167, 139, 250, 0.5)');
    fireEvent.blur(input);
    expect(input.style.borderColor).toBe('rgba(255, 255, 255, 0.08)');
  });

  it('shows prepare button and notice while backend is warming', () => {
    const onPrepare = vi.fn();
    renderInput('thread-1', {
      showPrepare: true,
      prepareMessage: 'Backend is warming up',
      prepareProgress: { completedUnits: 2, totalUnits: 3, percent: 67 },
      onPrepare,
    });

    expect(screen.getByText('Backend is warming up')).toBeTruthy();
    expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('67');
    fireEvent.click(screen.getByRole('button', { name: 'Prepare backend' }));

    expect(onPrepare).toHaveBeenCalled();
  });

  it('shows unavailable prepare label and honors disabled prepare state', () => {
    const onPrepare = vi.fn();
    renderInput('thread-1', {
      showPrepare: true,
      prepareDisabled: true,
      prepareMessage: 'Backend unavailable',
      onPrepare,
    });

    const button = screen.getByRole('button', { name: 'Prepare backend' });
    expect(button.textContent).toBe('Prepare');
    fireEvent.click(button);
    expect(onPrepare).not.toHaveBeenCalled();
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
