// ─────────────────────────────────────────────────────────────────────────────
// File: frontend/src/components/Chat/MessageList.tsx
// Purpose: Renders the conversation thread with full markdown support.
//          Uses react-markdown + remark-gfm for headings, bold, italic,
//          lists, tables, and code fences.
//          LaTeX ($...$ inline, $$...$$ block) is rendered via KaTeX.
// ─────────────────────────────────────────────────────────────────────────────

import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { ArrowClockwise, ArrowDown } from '@phosphor-icons/react';
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

const mdComponents = {
  // react-markdown v10 omits the old inline prop; a language class or trailing
  // newline identifies block code. The pre renderer owns block layout.
  code: ({ children, className }: MarkdownCodeProps) => {
    const isBlock = Boolean(className) || String(children ?? '').endsWith('\n');
    return (
      <code className={[className, isBlock ? 'message-code-block' : 'message-code-inline'].filter(Boolean).join(' ')}>
        {children}
      </code>
    );
  },
  table: ({ children }: MarkdownChildrenProps) => (
    <div className="message-table-scroll"><table>{children}</table></div>
  ),
  a: ({ href, children }: MarkdownAnchorProps) => (
    <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
  ),
  // Model-authored remote images can act as tracking pixels. Keep this study
  // interface text-only so reading an answer never fetches those images.
  img: ({ alt }: MarkdownImageProps) => (
    <span className="message-image-omitted">[Image omitted{alt ? `: ${alt}` : ''}]</span>
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
    <div className="message-markdown">
      {segments.map((seg, i) => {
        if (seg.type === 'block-math') return <BlockMath key={i} math={seg.value} />;
        if (seg.type === 'inline-math') return <InlineMath key={i} math={seg.value} />;
        return (
          <ReactMarkdown key={i} remarkPlugins={isAssistant ? [remarkGfm, remarkBookCitationLabels] : [remarkGfm]} components={mdComponents}>
            {seg.value}
          </ReactMarkdown>
        );
      })}
    </div>
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
    <div ref={listRef} className="message-list" role="region" aria-label="Conversation" tabIndex={0}
      onPointerDown={() => { pointerDown.current = true; }}
      onScroll={() => {
        const list = listRef.current;
        if (!list) return;
        followLatest.current = nearBottom(list) && !hasSelection() && !pointerDown.current;
        if (nearBottom(list)) setHasNewContent(false);
      }}>
      {messages.length === 0 && !liveActivity && (
        <div className="message-empty">
          <h2>What would you like to understand?</h2>
          <p>Ask a question about AI Engineering…</p>
          <p>Inspect the generated architecture to see how its components work together.</p>
        </div>
      )}

      {messages.flatMap(msg => [
        msg.role === 'assistant' && (msg.id === liveOwnerId || msg.activity)
          ? <ThinkingIndicator key={`activity-${msg.clientRequestId ?? msg.id}`}
              activity={msg.id === liveOwnerId ? liveActivity!.activity : msg.activity!}
              liveActivity={msg.id === liveOwnerId ? liveActivity ?? undefined : undefined} /> : null,
        <div
          key={msg.id}
          className={`message-row message-row--${msg.role}`}
          data-testid={`message-${msg.role}`}
        >
          <div className={msg.role === 'user' ? 'message-user' : 'message-assistant'}>
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
                <ArrowClockwise size={17} aria-hidden="true" />
                <span>{retryingMessageId === msg.id ? 'Retrying…' : 'Retry generation'}</span>
              </button>
            )}
            {msg.isStreaming && (
              <span className="message-streaming-cursor" aria-hidden="true" />
            )}
          </div>
        </div>
      ]).concat(liveActivity && !liveOwnerId
        ? [<ThinkingIndicator key={`activity-${liveActivity.clientRequestId}`}
            activity={liveActivity.activity} liveActivity={liveActivity} />] : [])}
    </div>
    {hasNewContent && <button className="message-jump" aria-label="Jump to latest" title="Jump to latest" onClick={jumpToLatest}>
      <ArrowDown size={18} aria-hidden="true" />
    </button>}
    </div>
  );
}
