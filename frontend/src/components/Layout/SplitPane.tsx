import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';

import './SplitPane.css';

interface SplitPaneProps {
  left: React.ReactNode;
  right: React.ReactNode;
  graphVisible?: boolean;
}

type Pane = 'chat' | 'diagram';
const COMPACT_WIDTH = 960;
const MIN_LEFT_PCT = 40;
const MAX_LEFT_PCT = 80;
const DEFAULT_LEFT_PCT = 60;
const SEPARATOR_WIDTH = 10;
const MIN_CHAT_WIDTH = 320;

function initialWidth(): number {
  if (typeof window === 'undefined') return COMPACT_WIDTH;
  if (typeof window.matchMedia === 'function' && window.matchMedia('(max-width: 959px)').matches) {
    return COMPACT_WIDTH - 1;
  }
  return Math.max(window.innerWidth, COMPACT_WIDTH);
}

export function SplitPane({ left, right, graphVisible = true }: SplitPaneProps) {
  const [leftPct, setLeftPct] = useState(DEFAULT_LEFT_PCT);
  const [width, setWidth] = useState(initialWidth);
  const [selectedPane, setSelectedPane] = useState<Pane>('chat');
  const [resizing, setResizing] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const graphPanelRef = useRef<HTMLDivElement>(null);
  const chatPanelRef = useRef<HTMLDivElement>(null);
  const measuredWidth = useRef(width);
  const graphHadFocus = useRef(false);
  const chatTabRef = useRef<HTMLButtonElement>(null);
  const diagramTabRef = useRef<HTMLButtonElement>(null);
  const dragging = useRef(false);
  const previousBodyStyle = useRef({ cursor: '', userSelect: '' });
  const id = useId();
  const compact = width < COMPACT_WIDTH;
  const maxLeftPct = Math.min(MAX_LEFT_PCT, ((width - SEPARATOR_WIDTH - MIN_CHAT_WIDTH) / width) * 100);
  const visibleLeftPct = Math.min(leftPct, maxLeftPct);
  const graphActive = graphVisible && (!compact || selectedPane === 'diagram');
  const chatActive = !compact || !graphVisible || selectedPane === 'chat';

  // A removed diagram should not reopen when a later conversation gains a graph.
  if (!graphVisible && selectedPane === 'diagram') setSelectedPane('chat');

  const stopDragging = useCallback(() => {
    if (!dragging.current) return;
    dragging.current = false;
    setResizing(false);
    Object.assign(document.body.style, previousBodyStyle.current);
  }, []);

  const updateWidth = useCallback((nextWidth: number) => {
    if (nextWidth <= 0) return;
    if (measuredWidth.current >= COMPACT_WIDTH && nextWidth < COMPACT_WIDTH) {
      const focused = document.activeElement;
      if (graphPanelRef.current?.contains(focused)) setSelectedPane('diagram');
      else if (chatPanelRef.current?.contains(focused)) setSelectedPane('chat');
      stopDragging();
    }
    measuredWidth.current = nextWidth;
    setWidth(nextWidth);
  }, [stopDragging]);

  useLayoutEffect(() => {
    const graph = graphPanelRef.current;
    if (!graphVisible && graphHadFocus.current) {
      const chat = chatPanelRef.current;
      const target = chat?.querySelector<HTMLElement>('textarea:not([disabled])')
        ?? chat?.querySelector<HTMLElement>('button:not([disabled]), input:not([disabled]), a[href], [tabindex="0"]')
        ?? chat;
      target?.focus();
    }
    graphHadFocus.current = false;
    // Capture focus before visibility changes make the graph inert.
    return () => {
      graphHadFocus.current = graph?.contains(document.activeElement) ?? false;
    };
  }, [graphVisible]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const measure = () => {
      const nextWidth = container.getBoundingClientRect().width;
      updateWidth(nextWidth);
    };
    const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(entries => {
      const nextWidth = entries[0]?.contentRect.width;
      updateWidth(nextWidth);
    }) : null;
    observer?.observe(container);
    window.addEventListener('resize', measure);
    // Measure after mounting without synchronously cascading an effect render.
    const frame = window.requestAnimationFrame(measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', measure);
      window.cancelAnimationFrame(frame);
    };
  }, [updateWidth]);

  useEffect(() => () => stopDragging(), [compact, graphVisible, stopDragging]);

  const onPointerDown = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (!graphVisible || compact || event.button !== 0 || dragging.current) return;
    event.preventDefault();
    event.currentTarget.focus();
    previousBodyStyle.current = { cursor: document.body.style.cursor, userSelect: document.body.style.userSelect };
    event.currentTarget.setPointerCapture(event.pointerId);
    dragging.current = true;
    setResizing(true);
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  }, [graphVisible, compact]);

  const onPointerMove = useCallback((event: React.PointerEvent) => {
    if (!dragging.current || !containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    if (rect.width <= 0) return;
    const maxPct = Math.min(MAX_LEFT_PCT, ((rect.width - SEPARATOR_WIDTH - MIN_CHAT_WIDTH) / rect.width) * 100);
    const pct = ((event.clientX - rect.left) / rect.width) * 100;
    setLeftPct(Math.min(maxPct, Math.max(MIN_LEFT_PCT, pct)));
  }, []);

  const onPointerUp = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    stopDragging();
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }, [stopDragging]);

  const onSeparatorKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const values: Record<string, number> = {
      Home: MIN_LEFT_PCT,
      End: maxLeftPct,
      ArrowLeft: visibleLeftPct - 5,
      ArrowRight: visibleLeftPct + 5,
    };
    const next = values[event.key];
    if (next === undefined) return;
    event.preventDefault();
    setLeftPct(Math.min(maxLeftPct, Math.max(MIN_LEFT_PCT, next)));
  };

  const onTabKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 'chat' : event.key === 'End' ? 'diagram'
      : selectedPane === 'chat' ? 'diagram' : 'chat';
    setSelectedPane(next);
    (next === 'chat' ? chatTabRef : diagramTabRef).current?.focus();
  };

  return (
    <div
      ref={containerRef}
      className={`split-pane ${compact ? 'split-pane--compact' : 'split-pane--side-by-side'}${resizing ? ' split-pane--resizing' : ''}`}
    >
      {compact && graphVisible && (
        <div className="split-pane__tabs" role="tablist" aria-label="Workspace view">
          <button ref={chatTabRef} id={`${id}-chat-tab`} role="tab" aria-controls={`${id}-chat-panel`}
            aria-selected={selectedPane === 'chat'} tabIndex={selectedPane === 'chat' ? 0 : -1}
            onClick={() => setSelectedPane('chat')} onKeyDown={onTabKeyDown}>Chat</button>
          <button ref={diagramTabRef} id={`${id}-diagram-tab`} role="tab" aria-controls={`${id}-diagram-panel`}
            aria-selected={selectedPane === 'diagram'} tabIndex={selectedPane === 'diagram' ? 0 : -1}
            onClick={() => setSelectedPane('diagram')} onKeyDown={onTabKeyDown}>Diagram</button>
        </div>
      )}
      <div className="split-pane__panels">
        {/* Hidden panels retain geometry because diagram readiness depends on layout. */}
        <div ref={graphPanelRef} className={`split-pane__graph split-pane__panel${graphActive ? '' : ' split-pane__panel--inactive'}`}
          id={`${id}-diagram-panel`} role={compact && graphVisible ? 'tabpanel' : undefined}
          aria-labelledby={compact && graphVisible ? `${id}-diagram-tab` : undefined}
          aria-hidden={!graphActive} inert={!graphActive}
          style={{ width: compact || !graphVisible ? '100%' : `${visibleLeftPct}%` }}>
          {left}
        </div>
        {!compact && graphVisible && (
          <div className="split-pane__separator" role="separator" aria-label="Resize graph and conversation panes"
            aria-orientation="vertical" aria-valuemin={MIN_LEFT_PCT} aria-valuemax={Math.round(maxLeftPct)}
            aria-valuenow={Math.round(visibleLeftPct)}
            aria-valuetext={`Diagram ${Math.round(visibleLeftPct)}%, conversation ${100 - Math.round(visibleLeftPct)}%`}
            title="Drag to resize. Double-click to reset." tabIndex={0}
            onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp} onLostPointerCapture={onPointerUp}
            onDoubleClick={() => setLeftPct(DEFAULT_LEFT_PCT)} onKeyDown={onSeparatorKeyDown} />
        )}
        <div ref={chatPanelRef} tabIndex={-1} className={`split-pane__conversation split-pane__panel${chatActive ? '' : ' split-pane__panel--inactive'}`}
          id={`${id}-chat-panel`} role={compact && graphVisible ? 'tabpanel' : undefined}
          aria-labelledby={compact && graphVisible ? `${id}-chat-tab` : undefined}
          aria-hidden={!chatActive} inert={!chatActive}>
          {right}
        </div>
      </div>
    </div>
  );
}
