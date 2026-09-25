import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { SplitPane } from './SplitPane';

function stubViewport(stacked: boolean) {
  vi.stubGlobal('matchMedia', vi.fn(() => ({
    matches: stacked,
    media: '(max-width: 1023px)',
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })));
}

describe('SplitPane responsive and accessible resizing', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('supports keyboard resizing for the desktop separator', () => {
    stubViewport(false);
    render(<SplitPane left={<div>graph</div>} right={<div>chat</div>} />);

    const separator = screen.getByRole('separator', { name: 'Resize graph and conversation panes' });
    expect(separator.getAttribute('aria-orientation')).toBe('vertical');
    expect(separator.getAttribute('aria-valuenow')).toBe('60');
    fireEvent.keyDown(separator, { key: 'ArrowLeft' });
    expect(separator.getAttribute('aria-valuenow')).toBe('55');
    fireEvent.keyDown(separator, { key: 'Home' });
    expect(separator.getAttribute('aria-valuenow')).toBe('40');
    fireEvent.keyDown(separator, { key: 'End' });
    expect(separator.getAttribute('aria-valuenow')).toBe('80');
  });

  it('stacks graph above chat and uses vertical arrow keys on narrow screens', () => {
    stubViewport(true);
    const { container } = render(<SplitPane left={<div>graph</div>} right={<div>chat</div>} />);

    expect(container.querySelector('.split-pane')?.classList.contains('split-pane--stacked')).toBe(true);
    const separator = screen.getByRole('separator');
    expect(separator.getAttribute('aria-orientation')).toBe('horizontal');
    fireEvent.keyDown(separator, { key: 'ArrowDown' });
    expect(separator.getAttribute('aria-valuenow')).toBe('65');
  });

  it('removes a hidden graph separator from the tab order', () => {
    stubViewport(false);
    render(<SplitPane left={<div>graph</div>} right={<div>chat</div>} graphVisible={false} />);
    expect(screen.getByRole('separator', { hidden: true }).getAttribute('tabindex')).toBe('-1');
  });

  it('keeps a captured drag active outside the divider and restores body styles on release', () => {
    stubViewport(false);
    const { container } = render(<SplitPane left={<div>graph</div>} right={<div>chat</div>} />);
    const separator = screen.getByRole('separator');
    separator.setPointerCapture = vi.fn();
    separator.hasPointerCapture = vi.fn(() => true);
    separator.releasePointerCapture = vi.fn();
    vi.spyOn(container.firstElementChild!, 'getBoundingClientRect').mockReturnValue({
      x: 0, y: 0, top: 0, left: 0, right: 1000, bottom: 700, width: 1000, height: 700, toJSON: () => ({}),
    });
    fireEvent.pointerDown(separator, { pointerId: 1, button: 0 });
    expect(container.firstElementChild?.classList.contains('split-pane--resizing')).toBe(true);
    expect(container.querySelector<HTMLElement>('.split-pane__graph')?.style.transition).toBe('none');
    fireEvent.pointerLeave(separator, { pointerId: 1 });
    fireEvent.pointerMove(separator, { pointerId: 1, clientX: 720 });
    expect(separator.getAttribute('aria-valuenow')).toBe('72');
    expect(document.body.style.userSelect).toBe('none');
    fireEvent.pointerUp(separator, { pointerId: 1 });
    expect(document.body.style.userSelect).toBe('');
    expect(container.firstElementChild?.classList.contains('split-pane--resizing')).toBe(false);
    fireEvent.doubleClick(separator);
    expect(separator.getAttribute('aria-valuenow')).toBe('60');
  });

  it('cleans up an interrupted drag when pointer capture is lost or the pane unmounts', () => {
    stubViewport(false);
    const { unmount } = render(<SplitPane left={<div>graph</div>} right={<div>chat</div>} />);
    const separator = screen.getByRole('separator');
    separator.setPointerCapture = vi.fn();
    separator.hasPointerCapture = vi.fn(() => false);
    fireEvent.pointerDown(separator, { pointerId: 1, button: 0 });
    fireEvent.lostPointerCapture(separator, { pointerId: 1 });
    expect(document.body.style.cursor).toBe('');
    fireEvent.pointerDown(separator, { pointerId: 2, button: 0 });
    expect(document.body.style.cursor).toBe('col-resize');
    unmount();
    expect(document.body.style.cursor).toBe('');
    expect(document.body.style.userSelect).toBe('');
  });
});
