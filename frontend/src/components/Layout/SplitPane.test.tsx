import { fireEvent, render, screen, act } from '@testing-library/react';
import { useEffect } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { SplitPane } from './SplitPane';

function stubViewport(compact: boolean) {
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: compact })));
  vi.stubGlobal('innerWidth', 1200);
}

function stubContainerResize() {
  let callback: ResizeObserverCallback;
  const disconnect = vi.fn();
  vi.stubGlobal('ResizeObserver', class {
    constructor(next: ResizeObserverCallback) { callback = next; }
    observe = vi.fn();
    disconnect = disconnect;
  });
  return {
    resize(width: number) {
      act(() => callback([{ contentRect: { width } } as ResizeObserverEntry], {} as ResizeObserver));
    },
    disconnect,
  };
}

function enablePointerCapture(separator: HTMLElement) {
  separator.setPointerCapture = vi.fn();
  separator.hasPointerCapture = vi.fn(() => true);
  separator.releasePointerCapture = vi.fn();
}

function mockContainerWidth(container: HTMLElement, width: number) {
  vi.spyOn(container.querySelector('.split-pane')!, 'getBoundingClientRect').mockReturnValue({
    x: 0, y: 0, top: 0, left: 0, right: width, bottom: 700, width, height: 700, toJSON: () => ({}),
  });
}

describe('SplitPane responsive workspace', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  });

  it('defaults compact screens to Chat and preserves the mounted draft and diagram across tabs', () => {
    stubViewport(true);
    const graphMount = vi.fn();
    function Graph() {
      useEffect(graphMount, []);
      return <div>graph</div>;
    }
    const { container } = render(<SplitPane left={<Graph />} right={<textarea aria-label="Draft" />} />);
    const chat = screen.getByRole('tab', { name: 'Chat' });
    const diagram = screen.getByRole('tab', { name: 'Diagram' });
    const graphPanel = container.querySelector<HTMLElement>('.split-pane__graph')!;
    expect(chat.getAttribute('aria-selected')).toBe('true');
    expect(screen.queryByRole('separator')).toBeNull();
    expect(graphPanel.hasAttribute('inert')).toBe(true);
    expect(graphPanel.getAttribute('aria-hidden')).toBe('true');
    // The hidden canvas keeps full pane geometry so its renderer can acknowledge readiness.
    expect(graphPanel.style.width).toBe('100%');
    expect(graphPanel.classList.contains('split-pane__panel--inactive')).toBe(true);
    expect(graphMount).toHaveBeenCalledTimes(1);
    const draft = screen.getByRole('textbox', { name: 'Draft' });
    fireEvent.change(draft, { target: { value: 'My unfinished prompt' } });
    fireEvent.click(diagram);
    expect(diagram.getAttribute('aria-selected')).toBe('true');
    expect(graphPanel.hasAttribute('inert')).toBe(false);
    expect(container.querySelector('.split-pane__conversation')?.hasAttribute('inert')).toBe(true);
    fireEvent.click(chat);
    expect(screen.getByRole('textbox', { name: 'Draft' })).toBe(draft);
    expect((draft as HTMLTextAreaElement).value).toBe('My unfinished prompt');
    expect(graphMount).toHaveBeenCalledTimes(1);
  });

  it('uses automatic keyboard tab activation with roving focus and labelled panels', () => {
    stubViewport(true);
    render(<SplitPane left={<div>graph</div>} right={<div>chat</div>} />);
    const chat = screen.getByRole('tab', { name: 'Chat' });
    const diagram = screen.getByRole('tab', { name: 'Diagram' });
    chat.focus();
    fireEvent.keyDown(chat, { key: 'ArrowRight' });
    expect(document.activeElement).toBe(diagram);
    expect(diagram.getAttribute('tabindex')).toBe('0');
    expect(chat.getAttribute('tabindex')).toBe('-1');
    expect(screen.getByRole('tabpanel', { name: 'Diagram' }).id).toBe(diagram.getAttribute('aria-controls'));
    fireEvent.keyDown(diagram, { key: 'ArrowRight' });
    expect(document.activeElement).toBe(chat);
    fireEvent.keyDown(chat, { key: 'End' });
    expect(document.activeElement).toBe(diagram);
    fireEvent.keyDown(diagram, { key: 'Home' });
    expect(document.activeElement).toBe(chat);
  });

  it('reconciles a removed diagram and does not automatically reopen it when graph returns', () => {
    stubViewport(true);
    const { rerender, container } = render(<SplitPane left={<div>graph</div>} right={<textarea aria-label="Draft" />} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Diagram' }));
    rerender(<SplitPane left={<div>graph</div>} right={<textarea aria-label="Draft" />} graphVisible={false} />);
    expect(screen.queryByRole('tablist')).toBeNull();
    expect(screen.getByRole('textbox', { name: 'Draft' })).toBeTruthy();
    expect(container.querySelector('.split-pane__graph')?.hasAttribute('inert')).toBe(true);
    rerender(<SplitPane left={<div>new graph</div>} right={<textarea aria-label="Draft" />} />);
    expect(screen.getByRole('tab', { name: 'Chat' }).getAttribute('aria-selected')).toBe('true');
  });

  it('uses container width, retains tab selection after rotation, and disconnects its observer', () => {
    stubViewport(false);
    const observer = stubContainerResize();
    const { unmount } = render(<SplitPane left={<div>graph</div>} right={<div>chat</div>} />);
    expect(screen.getByRole('separator')).toBeTruthy();
    observer.resize(820);
    fireEvent.click(screen.getByRole('tab', { name: 'Diagram' }));
    observer.resize(1100);
    expect(screen.queryByRole('tablist')).toBeNull();
    expect(screen.getByRole('separator')).toBeTruthy();
    observer.resize(959);
    expect(screen.getByRole('tab', { name: 'Diagram' }).getAttribute('aria-selected')).toBe('true');
    unmount();
    expect(observer.disconnect).toHaveBeenCalledOnce();
  });

  it.each(['chat', 'diagram'] as const)('keeps the focused %s pane visible when desktop becomes compact', pane => {
    stubViewport(true);
    const observer = stubContainerResize();
    const { container } = render(<SplitPane left={<input aria-label="Diagram editor" />} right={<textarea aria-label="Draft" />} />);
    if (pane === 'chat') fireEvent.click(screen.getByRole('tab', { name: 'Diagram' }));
    observer.resize(1100);
    const input = screen.getByRole('textbox', { name: pane === 'chat' ? 'Draft' : 'Diagram editor' });
    input.focus();
    fireEvent.change(input, { target: { value: 'unfinished edit' } });
    observer.resize(800);
    expect(screen.getByRole('tab', { name: pane === 'chat' ? 'Chat' : 'Diagram' }).getAttribute('aria-selected')).toBe('true');
    expect(document.activeElement).toBe(input);
    expect((input as HTMLInputElement).value).toBe('unfinished edit');
    expect(container.querySelector(pane === 'chat' ? '.split-pane__conversation' : '.split-pane__graph')?.hasAttribute('inert')).toBe(false);
  });

  it('moves focus into chat when the focused diagram becomes unavailable', () => {
    stubViewport(true);
    const { rerender } = render(<SplitPane left={<input aria-label="Diagram editor" />} right={<textarea aria-label="Draft" />} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Diagram' }));
    screen.getByRole('textbox', { name: 'Diagram editor' }).focus();
    rerender(<SplitPane left={<input aria-label="Diagram editor" />} right={<textarea aria-label="Draft" />} graphVisible={false} />);
    expect(document.activeElement).toBe(screen.getByRole('textbox', { name: 'Draft' }));
  });

  it('does not steal draft focus or switch tabs when graph content updates', () => {
    stubViewport(true);
    const { rerender } = render(<SplitPane left={<div>empty graph</div>} right={<textarea aria-label="Draft" />} />);
    const draft = screen.getByRole('textbox', { name: 'Draft' });
    draft.focus();
    rerender(<SplitPane left={<div>generated graph</div>} right={<textarea aria-label="Draft" />} />);
    expect(document.activeElement).toBe(draft);
    expect(screen.getByRole('tab', { name: 'Chat' }).getAttribute('aria-selected')).toBe('true');
  });

  it('supports desktop keyboard bounds and preserves 320px for chat at the breakpoint', () => {
    stubViewport(false);
    const observer = stubContainerResize();
    render(<SplitPane left={<div>graph</div>} right={<div>chat</div>} />);
    const separator = screen.getByRole('separator');
    expect(separator.getAttribute('aria-orientation')).toBe('vertical');
    fireEvent.keyDown(separator, { key: 'ArrowLeft' });
    expect(separator.getAttribute('aria-valuenow')).toBe('55');
    fireEvent.keyDown(separator, { key: 'Home' });
    expect(separator.getAttribute('aria-valuenow')).toBe('40');
    observer.resize(960);
    fireEvent.keyDown(separator, { key: 'End' });
    expect(separator.getAttribute('aria-valuenow')).toBe('66');
    expect(separator.getAttribute('aria-valuemax')).toBe('66');
    fireEvent.keyDown(separator, { key: 'ArrowRight' });
    expect(separator.getAttribute('aria-valuenow')).toBe('66');
  });

  it('clamps captured pointer resizing and restores existing body styles on cancellation', () => {
    stubViewport(false);
    document.body.style.cursor = 'wait';
    document.body.style.userSelect = 'text';
    const { container } = render(<SplitPane left={<div>graph</div>} right={<div>chat</div>} />);
    const separator = screen.getByRole('separator');
    enablePointerCapture(separator);
    mockContainerWidth(container, 1000);
    fireEvent.pointerDown(separator, { pointerId: 1, button: 0 });
    fireEvent.pointerMove(separator, { pointerId: 1, clientX: 900 });
    expect(separator.getAttribute('aria-valuenow')).toBe('67');
    fireEvent.pointerLeave(separator, { pointerId: 1 });
    fireEvent.pointerMove(separator, { pointerId: 1, clientX: 550 });
    expect(separator.getAttribute('aria-valuenow')).toBe('55');
    fireEvent.pointerCancel(separator, { pointerId: 1 });
    expect(document.body.style.cursor).toBe('wait');
    expect(document.body.style.userSelect).toBe('text');
    expect(container.querySelector('.split-pane')?.classList.contains('split-pane--resizing')).toBe(false);
    fireEvent.doubleClick(separator);
    expect(separator.getAttribute('aria-valuenow')).toBe('60');
  });

  it('restores body styles when the graph disappears during dragging', () => {
    stubViewport(false);
    const { rerender } = render(<SplitPane left={<div>graph</div>} right={<div>chat</div>} />);
    const separator = screen.getByRole('separator');
    enablePointerCapture(separator);
    fireEvent.pointerDown(separator, { pointerId: 1, button: 0 });
    expect(document.body.style.cursor).toBe('col-resize');
    rerender(<SplitPane left={<div>graph</div>} right={<div>chat</div>} graphVisible={false} />);
    expect(document.body.style.cursor).toBe('');
    expect(document.body.style.userSelect).toBe('');
    expect(screen.queryByRole('separator')).toBeNull();
  });

  it('cleans up interrupted dragging on compact resize, capture loss, and unmount', () => {
    stubViewport(false);
    const observer = stubContainerResize();
    const { unmount } = render(<SplitPane left={<div>graph</div>} right={<div>chat</div>} />);
    let separator = screen.getByRole('separator');
    enablePointerCapture(separator);
    fireEvent.pointerDown(separator, { pointerId: 1, button: 0 });
    fireEvent.lostPointerCapture(separator, { pointerId: 1 });
    expect(document.body.style.cursor).toBe('');
    fireEvent.pointerDown(separator, { pointerId: 2, button: 0 });
    observer.resize(800);
    expect(document.body.style.cursor).toBe('');
    observer.resize(1100);
    separator = screen.getByRole('separator');
    enablePointerCapture(separator);
    fireEvent.pointerDown(separator, { pointerId: 3, button: 0 });
    unmount();
    expect(document.body.style.cursor).toBe('');
    expect(document.body.style.userSelect).toBe('');
  });
});
