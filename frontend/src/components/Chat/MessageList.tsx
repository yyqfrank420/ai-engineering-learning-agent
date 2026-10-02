// ─────────────────────────────────────────────────────────────────────────────
// File: frontend/src/components/Chat/MessageList.tsx
// Purpose: Renders the conversation thread with full markdown support.
//          Uses react-markdown + remark-gfm for headings, bold, italic,
//          lists, tables, and code fences.
//          LaTeX ($...$ inline, $$...$$ block) is rendered via KaTeX.
// ─────────────────────────────────────────────────────────────────────────────

import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Root, RootContent } from 'mdast';
import type { VFile } from 'vfile';
import { InlineMath, BlockMath } from 'react-katex';
import 'katex/dist/katex.min.css';
import type { LiveActivity, Message } from '../../types';
import '../GraphHistoryControls.css';
import './MessageList.css';
import { ThinkingIndicator } from './ThinkingIndicator';

interface MessageListProps {
  messages: Message[];
  liveActivity?: LiveActivity | null;
  revisionIds?: string[];
  viewedRevisionId?: string | null;
  onViewDiagram?: (id: string) => void;
  historyDisabled?: boolean;
  onRetryMessage?: (message: Message) => void;
  retryDisabled?: boolean;
  retryingMessageId?: string | null;
}

// ── LaTeX pre-processor ───────────────────────────────────────────────────────
// react-markdown doesn't handle LaTeX natively. Split the text on $...$ / $$...$$
// boundaries before handing the plain-text portions to ReactMarkdown.

type Segment = { type: 'text'; value: string } | { type: 'inline-math' | 'block-math'; value: string };
type MarkdownChildrenProps = { children?: ReactNode };
type MarkdownCodeProps = MarkdownChildrenProps & { className?: string };
type MarkdownAnchorProps = MarkdownChildrenProps & { href?: string };
type MarkdownImageProps = { alt?: string };

function splitLatex(text: string): Segment[] {
  const segments: Segment[] = [];
  const regex = /(\$\$[\s\S]+?\$\$|\$[^$\n]+?\$)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = regex.exec(text)) !== null) {
    if (m.index > last) segments.push({ type: 'text', value: text.slice(last, m.index) });
    const raw = m[0];
    if (raw.startsWith('$$')) segments.push({ type: 'block-math', value: raw.slice(2, -2).trim() });
    else                       segments.push({ type: 'inline-math', value: raw.slice(1, -1).trim() });
    last = regex.lastIndex;
  }
  if (last < text.length) segments.push({ type: 'text', value: text.slice(last) });
  return segments;
}

// ── Shared markdown component overrides ──────────────────────────────────────
// These inline styles keep the markdown visually consistent with the dark theme.

const mdComponents = {
  // Headings
  h1: ({ children }: MarkdownChildrenProps) => (
    <h1 style={{ fontSize: '1.1rem', fontWeight: 700, color: '#e6edf3', margin: '0.75rem 0 0.35rem', borderBottom: '1px solid #21262d', paddingBottom: '0.25rem' }}>{children}</h1>
  ),
  h2: ({ children }: MarkdownChildrenProps) => (
    <h2 style={{ fontSize: '0.95rem', fontWeight: 600, color: '#e6edf3', margin: '0.65rem 0 0.3rem' }}>{children}</h2>
  ),
  h3: ({ children }: MarkdownChildrenProps) => (
    <h3 style={{ fontSize: '0.875rem', fontWeight: 600, color: '#c9d1d9', margin: '0.5rem 0 0.25rem' }}>{children}</h3>
  ),
  // Paragraphs
  p: ({ children }: MarkdownChildrenProps) => (
    <p style={{ margin: '0.35rem 0', lineHeight: 1.65 }}>{children}</p>
  ),
  // Bold / italic
  strong: ({ children }: MarkdownChildrenProps) => (
    <strong style={{ color: '#e6edf3', fontWeight: 600 }}>{children}</strong>
  ),
  em: ({ children }: MarkdownChildrenProps) => (
    <em style={{ color: '#c9d1d9', fontStyle: 'italic' }}>{children}</em>
  ),
  // Unordered + ordered lists
  ul: ({ children }: MarkdownChildrenProps) => (
    <ul style={{ margin: '0.35rem 0', paddingLeft: '1.4rem', lineHeight: 1.65 }}>{children}</ul>
  ),
  ol: ({ children }: MarkdownChildrenProps) => (
    <ol style={{ margin: '0.35rem 0', paddingLeft: '1.4rem', lineHeight: 1.65 }}>{children}</ol>
  ),
  li: ({ children }: MarkdownChildrenProps) => (
    <li style={{ margin: '0.15rem 0' }}>{children}</li>
  ),
  // react-markdown v10 no longer supplies the old `inline` prop. Fenced code
  // retains a trailing newline (or language class); paragraphs do not. The
  // `pre` renderer owns block layout so this component never nests a <pre>
  // inside the paragraph or <pre> that react-markdown already created.
  code: ({ children, className }: MarkdownCodeProps) => {
    const isBlock = Boolean(className) || String(children ?? '').endsWith('\n');
    return (
      <code className={className} style={{
        background: isBlock ? 'transparent' : '#0d1117',
        border: isBlock ? 'none' : '1px solid #21262d',
        borderRadius: isBlock ? 0 : '4px',
        padding: isBlock ? 0 : '1px 5px',
        fontSize: '0.82rem',
        fontFamily: '"SF Mono", "Fira Code", "Cascadia Code", monospace',
        color: isBlock ? '#c9d1d9' : '#a78bfa',
      }}>
        {children}
      </code>
    );
  },
  pre: ({ children }: MarkdownChildrenProps) => (
    <pre className="chat-message__code" style={{
      background: '#0d1117',
      border: '1px solid #21262d',
      borderRadius: '6px',
      padding: '0.75rem 1rem',
      overflowX: 'auto',
      fontSize: '0.82rem',
      lineHeight: 1.6,
      margin: '0.5rem 0',
      fontFamily: '"SF Mono", "Fira Code", "Cascadia Code", monospace',
    }}>
      {children}
    </pre>
  ),
  // Block quotes
  blockquote: ({ children }: MarkdownChildrenProps) => (
    <blockquote style={{
      borderLeft: '3px solid rgba(167,139,250,0.4)',
      paddingLeft: '0.75rem',
      margin: '0.5rem 0',
      color: '#8b949e',
      fontStyle: 'italic',
    }}>
      {children}
    </blockquote>
  ),
  // Tables (GFM)
  table: ({ children }: MarkdownChildrenProps) => (
    <div className="chat-message__table" style={{ overflowX: 'auto', margin: '0.5rem 0' }}>
      <table style={{ borderCollapse: 'collapse', fontSize: '0.82rem', width: '100%' }}>{children}</table>
    </div>
  ),
  th: ({ children }: MarkdownChildrenProps) => (
    <th style={{ border: '1px solid #30363d', padding: '6px 10px', background: '#161b22', color: '#e6edf3', fontWeight: 600, textAlign: 'left' }}>{children}</th>
  ),
  td: ({ children }: MarkdownChildrenProps) => (
    <td style={{ border: '1px solid #21262d', padding: '6px 10px', color: '#8b949e' }}>{children}</td>
  ),
  // Horizontal rule
  hr: () => <hr style={{ border: 'none', borderTop: '1px solid #21262d', margin: '0.75rem 0' }} />,
  // Links
  a: ({ href, children }: MarkdownAnchorProps) => (
    <a href={href} style={{ color: '#60a5fa', textDecoration: 'none' }} target="_blank" rel="noopener noreferrer">{children}</a>
  ),
  // Model-authored remote images can act as tracking pixels. This text-only
  // study UI intentionally does not fetch them.
  img: ({ alt }: MarkdownImageProps) => (
    <span style={{ color: '#6e7681', fontStyle: 'italic' }}>[Image omitted{alt ? `: ${alt}` : ''}]</span>
  ),
};

// Book locations are citation labels, not URL destinations. CommonMark leaves
// these malformed self-links as prose text; preserve code and actual link nodes.
function remarkBookCitationLabels() {
  return (tree: Root, file: VFile) => {
    const source = String(file);
    function visit(node: Root | RootContent) {
      if (node.type === 'text') {
        const start = node.position?.start.offset;
        const end = node.position?.end.offset;
        // Parsed text loses escapes; leave deliberate Markdown literals intact.
        if (start === undefined || end === undefined || source.slice(start, end).includes("\\")) {
          return;
        }
        node.value = node.value.replace(
          /(?<!!)\[(Chapter [1-9][0-9]*(?:, p\.[1-9][0-9]*)?|Book, p\.[1-9][0-9]*|Book excerpt)\]\(\1\)/g,
          '$1',
        );
      } else if ('children' in node && node.type !== 'link' && node.type !== 'linkReference') {
        node.children.forEach(visit);
      }
    }
    visit(tree);
  };
}

// ── Message content renderer ──────────────────────────────────────────────────
// Splits on LaTeX first, then renders each text segment through ReactMarkdown.
function MessageContent({ content, isAssistant }: { content: string; isAssistant: boolean }) {
  const segments = splitLatex(content);
  return (
    <>
      {segments.map((seg, i) => {
        if (seg.type === 'block-math') return <div className="chat-message__math" key={i}><BlockMath math={seg.value} /></div>;
        if (seg.type === 'inline-math') return <InlineMath key={i} math={seg.value} />;
        return (
          <ReactMarkdown key={i} remarkPlugins={isAssistant ? [remarkGfm, remarkBookCitationLabels] : [remarkGfm]} components={mdComponents}>
            {seg.value}
          </ReactMarkdown>
        );
      })}
    </>
  );
}

export function MessageList({ messages, liveActivity = null, revisionIds = [], viewedRevisionId = null, onViewDiagram, historyDisabled = false, onRetryMessage, retryDisabled = false, retryingMessageId = null }: MessageListProps) {
  const listRef = useRef<HTMLDivElement>(null);
  const followLatest = useRef(true);
  const pointerDown = useRef(false);
  const previous = useRef({ firstId: '', userId: '', messages: [] as Message[], activitySequence: -1 });
  const liveOwnerId = liveActivity ? messages.find(message => message.role === 'assistant'
    && message.clientRequestId === liveActivity.clientRequestId)?.id : undefined;
  const [hasNewContent, setHasNewContent] = useState(false);

  const hasSelection = () => {
    const selection = window.getSelection();
    return !!selection && !selection.isCollapsed && !!listRef.current
      && (listRef.current.contains(selection.anchorNode) || listRef.current.contains(selection.focusNode));
  };
  const nearBottom = (list: HTMLDivElement) => list.scrollHeight - list.scrollTop - list.clientHeight <= 48;

  useEffect(() => {
    const releasePointer = () => {
      if (!pointerDown.current) return;
      pointerDown.current = false;
      if (listRef.current) followLatest.current = !hasSelection() && nearBottom(listRef.current);
    };
    const preserveSelection = () => {
      if (hasSelection()) followLatest.current = false;
    };
    document.addEventListener('selectionchange', preserveSelection);
    document.addEventListener('pointerup', releasePointer);
    document.addEventListener('pointercancel', releasePointer);
    return () => {
      document.removeEventListener('selectionchange', preserveSelection);
      document.removeEventListener('pointerup', releasePointer);
      document.removeEventListener('pointercancel', releasePointer);
    };
  }, []);

  useLayoutEffect(() => {
    const list = listRef.current;
    if (!list) return;
    const firstId = messages[0]?.id ?? '';
    const userId = [...messages].reverse().find(message => message.role === 'user')?.id ?? '';
    const newConversation = firstId !== previous.current.firstId;
    const newRequest = userId !== previous.current.userId;
    const activitySequence = liveActivity?.activity.steps.at(-1)?.sequence ?? -1;
    const contentChanged = activitySequence !== previous.current.activitySequence || messages.length !== previous.current.messages.length || messages.some((message, index) => {
      const old = previous.current.messages[index];
      return message.id !== old?.id || message.content !== old.content || message.title !== old.title || message.activity !== old.activity;
    });
    previous.current = { firstId, userId, messages, activitySequence };
    if (!contentChanged) return;
    if (newConversation || newRequest || (followLatest.current && !pointerDown.current && !hasSelection())) {
      list.scrollTop = list.scrollHeight;
      followLatest.current = true;
      // Visibility depends on the committed scroll geometry, before paint.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setHasNewContent(false);
    } else {
      followLatest.current = false;
      setHasNewContent(!nearBottom(list));
    }
  }, [messages, liveActivity]);

  const jumpToLatest = () => {
    const list = listRef.current;
    if (!list) return;
    list.scrollTop = list.scrollHeight;
    followLatest.current = true;
    setHasNewContent(false);
    list.focus({ preventScroll: true });
  };

  return (
    <div className="message-list-shell">
    <div ref={listRef} className="message-list chat-messages" role="region" aria-label="Conversation" tabIndex={0}
      onPointerDown={() => { pointerDown.current = true; }}
      onScroll={() => {
        const list = listRef.current;
        if (!list) return;
        followLatest.current = nearBottom(list) && !hasSelection() && !pointerDown.current;
        if (nearBottom(list)) setHasNewContent(false);
      }}>
      {messages.length === 0 && !liveActivity && (
        <div style={{
          color: '#6e7681',
          fontSize: '0.875rem',
          textAlign: 'center',
          marginTop: '2rem',
        }}>
          Ask a question about AI Engineering…
        </div>
      )}

      {messages.flatMap(msg => [
        msg.role === 'assistant' && (msg.id === liveOwnerId || msg.activity)
          ? <ThinkingIndicator key={`activity-${msg.clientRequestId ?? msg.id}`}
              activity={msg.id === liveOwnerId ? liveActivity!.activity : msg.activity!}
              liveActivity={msg.id === liveOwnerId ? liveActivity ?? undefined : undefined} /> : null,
        <div
          key={msg.id}
          className="message-row"
          data-testid={`message-${msg.role}`}
          style={{
            display: 'flex',
            justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
          }}
        >
          <div className={`chat-message__body ${msg.role === 'user' ? 'message-user' : 'message-assistant'}`}>
            {msg.kind === 'explanation' && msg.title && (
              <h2 className="message-heading">{msg.title}</h2>
            )}
            <MessageContent content={msg.content} isAssistant={msg.role === 'assistant'} />
            {msg.role === 'assistant' && msg.graphRevisionId && revisionIds.includes(msg.graphRevisionId) && onViewDiagram && (
              <button className="message-diagram-link" aria-pressed={msg.graphRevisionId === viewedRevisionId} disabled={historyDisabled} onClick={() => onViewDiagram(msg.graphRevisionId!)}>View diagram</button>
            )}
            {msg.role === 'assistant' && msg.retryRequest && onRetryMessage && (
              <button className="message-retry" type="button" disabled={retryDisabled || retryingMessageId === msg.id}
                onClick={() => onRetryMessage(msg)}>
                <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M20 11a8 8 0 1 1-2.3-5.7M20 4v6h-6" /></svg>
                <span>{retryingMessageId === msg.id ? 'Retrying…' : 'Retry generation'}</span>
              </button>
            )}
            {msg.isStreaming && (
              <span style={{
                display: 'inline-block',
                width: '8px',
                height: '12px',
                background: '#a78bfa',
                borderRadius: '1px',
                marginLeft: '2px',
                verticalAlign: 'text-bottom',
                animation: 'blink 1s step-end infinite',
              }} />
            )}
          </div>
        </div>
      ]).concat(liveActivity && !liveOwnerId
        ? [<ThinkingIndicator key={`activity-${liveActivity.clientRequestId}`}
            activity={liveActivity.activity} liveActivity={liveActivity} />] : [])}
    </div>
    {hasNewContent && <button className="message-jump" aria-label="Jump to latest" title="Jump to latest" onClick={jumpToLatest}>
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v16m-6-6 6 6 6-6" /></svg>
    </button>}
    </div>
  );
}
