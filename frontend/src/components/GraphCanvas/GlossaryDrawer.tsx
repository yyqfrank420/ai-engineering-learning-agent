import { useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties, PointerEvent as ReactPointerEvent } from 'react';
import type { GraphData } from '../../types';
import { extractGlossaryEntries } from '../../utils/glossary';
import './GlossaryDrawer.css';

interface GlossaryDrawerProps {
  graphData: GraphData | null;
  sourceTexts: string[];
  bottomOffset: string;
}

export function GlossaryDrawer({ graphData, sourceTexts, bottomOffset }: GlossaryDrawerProps) {
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const dragStateRef = useRef<{
    active: boolean;
    startX: number;
    startY: number;
    originX: number;
    originY: number;
    bounds?: { left: number; right: number; top: number; bottom: number };
  }>({
    active: false,
    startX: 0,
    startY: 0,
    originX: 0,
    originY: 0,
  });
  const suppressClickRef = useRef(false);
  const rootRef = useRef<HTMLDivElement>(null);

  const entries = useMemo(
    () => extractGlossaryEntries(sourceTexts, graphData),
    [graphData, sourceTexts],
  );

  useEffect(() => {
    const handlePointerMove = (event: PointerEvent) => {
      const drag = dragStateRef.current;
      if (!drag.active) return;
      const dx = event.clientX - drag.startX;
      const dy = event.clientY - drag.startY;
      if (Math.abs(dx) > 4 || Math.abs(dy) > 4) {
        suppressClickRef.current = true;
      }
      const bounds = drag.bounds;
      const desired = { x: drag.originX + dx, y: drag.originY + dy };
      setOffset(bounds ? {
        x: Math.max(bounds.left, Math.min(desired.x, bounds.right)),
        y: Math.max(bounds.top, Math.min(desired.y, bounds.bottom)),
      } : desired);
    };

    const handlePointerUp = () => {
      dragStateRef.current.active = false;
      window.setTimeout(() => {
        suppressClickRef.current = false;
      }, 0);
    };

    window.addEventListener('pointermove', handlePointerMove);
    window.addEventListener('pointerup', handlePointerUp);
    window.addEventListener('pointercancel', handlePointerUp);
    return () => {
      window.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('pointerup', handlePointerUp);
      window.removeEventListener('pointercancel', handlePointerUp);
    };
  }, []);

  useEffect(() => {
    const canvas = rootRef.current?.parentElement?.closest('.graph-canvas__surface');
    if (!canvas) return;
    const resetPosition = () => {
      dragStateRef.current.active = false;
      setOffset(current => current.x === 0 && current.y === 0 ? current : { x: 0, y: 0 });
    };
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', resetPosition);
      return () => window.removeEventListener('resize', resetPosition);
    }
    const observer = new ResizeObserver(resetPosition);
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [entries.length]);

  if (entries.length === 0) return null;

  const startDrag = (event: ReactPointerEvent<HTMLElement>) => {
    const root = rootRef.current;
    const panel = root?.getBoundingClientRect();
    const canvas = root?.parentElement?.closest('.graph-canvas__surface')?.getBoundingClientRect();
    const bottomPadding = root ? Math.max(16, Number.parseFloat(getComputedStyle(root).bottom) || 0) : 16;
    const bounds = panel && canvas && canvas.width > 0 && canvas.height > 0 ? {
      left: canvas.left + 16 - panel.left + offset.x,
      right: canvas.right - 16 - panel.right + offset.x,
      top: canvas.top + 16 - panel.top + offset.y,
      bottom: canvas.bottom - bottomPadding - panel.bottom + offset.y,
    } : undefined;
    dragStateRef.current = {
      active: true,
      startX: event.clientX,
      startY: event.clientY,
      originX: offset.x,
      originY: offset.y,
      bounds,
    };
  };

  const handleTriggerClick = () => {
    if (suppressClickRef.current) return;
    setOpen((value) => !value);
  };

  return (
    <div
      ref={rootRef}
      className="glossary-drawer"
      style={{
        position: 'absolute',
        right: '1rem',
        bottom: `max(${bottomOffset}, env(safe-area-inset-bottom))`,
        zIndex: 25,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'flex-end',
        gap: '0.5rem',
        pointerEvents: 'auto',
        transform: `translate(${offset.x}px, ${offset.y}px)`,
      }}
    >
      {open && (
        <div className="glossary-drawer__panel" style={drawerStyle(expanded)}>
          <div
            className="glossary-drawer__header"
            style={headerStyle}
            onPointerDown={startDrag}
          >
            <div>
              <div style={{ fontSize: '0.72rem', color: '#e6edf3', fontWeight: 600 }}>
                Acronyms & terms
              </div>
              <div className="glossary-drawer__summary" style={{ fontSize: '0.64rem', color: '#6e7681', marginTop: '0.1rem' }}>
                Quick plain-English explanations for technical words in this diagram and response.
              </div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', flexShrink: 0 }}>
              <button
                onClick={() => { setOffset({ x: 0, y: 0 }); setExpanded(value => !value); }}
                aria-label={expanded ? 'Use compact glossary' : 'Open larger glossary'}
                className="glossary-drawer__icon"
                style={windowButtonStyle}
              >
                {expanded ? '▣' : '□'}
              </button>
              <button
                onClick={() => setOpen(false)}
                aria-label="Close glossary"
                className="glossary-drawer__icon"
                style={closeButtonStyle}
              >
                ×
              </button>
            </div>
          </div>

          <div className="glossary-drawer__entries" style={entriesStyle(expanded)}>
            {entries.map((entry) => (
              <div key={entry.term} style={{ borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: '0.45rem' }}>
                <div style={{ fontSize: '0.7rem', color: '#a78bfa', fontWeight: 700, letterSpacing: '0.03em' }}>
                  {entry.term}
                </div>
                <div style={{ fontSize: '0.68rem', color: '#9aa4af', lineHeight: 1.55, marginTop: '0.16rem' }}>
                  {entry.explanation}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <button
        onClick={handleTriggerClick}
        onPointerDown={startDrag}
        className="glossary-drawer__trigger"
        style={triggerStyle(open)}
        aria-expanded={open}
        title="Drag to move"
      >
        Dictionary
      </button>
    </div>
  );
}

const drawerStyle = (expanded: boolean): CSSProperties => ({
  width: expanded ? '28rem' : '20rem',
  background: 'rgba(10,14,26,0.96)',
  border: '1px solid rgba(167,139,250,0.22)',
  borderRadius: '12px',
  padding: '0.8rem 0.9rem',
  backdropFilter: 'blur(18px)',
  WebkitBackdropFilter: 'blur(18px)',
  boxShadow: '0 16px 40px rgba(0,0,0,0.55)',
});

const headerStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'flex-start',
  justifyContent: 'space-between',
  gap: '1rem',
  cursor: 'grab',
  userSelect: 'none',
};

const entriesStyle = (expanded: boolean): CSSProperties => ({
  display: 'flex',
  flexDirection: 'column',
  gap: '0.5rem',
  maxHeight: expanded ? '24rem' : '15rem',
  overflowY: 'auto',
  paddingRight: '0.2rem',
  marginTop: '0.65rem',
});

const closeButtonStyle: CSSProperties = {
  background: 'none',
  border: 'none',
  color: '#6e7681',
  fontSize: '1rem',
  cursor: 'pointer',
  lineHeight: 1,
  padding: '0.2rem',
  flexShrink: 0,
};

const windowButtonStyle: CSSProperties = {
  ...closeButtonStyle,
  fontSize: '0.82rem',
};

const triggerStyle = (open: boolean): CSSProperties => ({
  border: open ? '1px solid rgba(167,139,250,0.4)' : '1px solid rgba(255,255,255,0.1)',
  background: open ? 'rgba(167,139,250,0.16)' : 'rgba(10,13,19,0.82)',
  color: open ? '#d9c9ff' : '#c9d1d9',
  borderRadius: '999px',
  padding: '0.34rem 0.8rem',
  fontSize: '0.7rem',
  cursor: 'grab',
  backdropFilter: 'blur(10px)',
  WebkitBackdropFilter: 'blur(10px)',
});
