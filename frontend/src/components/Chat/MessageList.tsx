// ─────────────────────────────────────────────────────────────────────────────
// File: frontend/src/components/Chat/MessageList.tsx
// Purpose: Renders the conversation thread with full markdown support.
//          Uses react-markdown + remark-gfm for headings, bold, italic,
//          lists, tables, and code fences.
//          LaTeX ($...$ inline, $$...$$ block) is rendered via KaTeX.
// ─────────────────────────────────────────────────────────────────────────────

import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { ArrowClockwise, ArrowDown } from '@phosphor-icons/react';
import type { ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import type { Root, RootContent, PhrasingContent } from 'mdast';
import type { Components } from 'react-markdown';
import type { VFile } from 'vfile';
import { InlineMath, BlockMath } from 'react-katex';
import 'katex/dist/katex.min.css';
import type { LiveActivity, Message } from '../../types';
import { displayUserMessageContent } from '../../utils/threadState';
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

type MarkdownChildrenProps = { children?: ReactNode };
type MarkdownCodeProps = MarkdownChildrenProps & { className?: string };
type MarkdownAnchorProps = MarkdownChildrenProps & { href?: string; className?: string; 'aria-label'?: string };
type MarkdownImageProps = { alt?: string };

const mdComponents: Components = {
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
  a: ({ href, children, className, 'aria-label': label }: MarkdownAnchorProps) => (
    <a href={href} className={className} aria-label={label}
      target={className === 'message-source-reference' ? undefined : '_blank'} rel="noopener noreferrer"
      onClick={className === 'message-source-reference' ? (event) => {
        event.preventDefault();
        const target = document.getElementById(href?.slice(1) ?? '');
        const details = target?.closest('details');
        if (details) details.open = true;
        target?.focus();
      } : undefined}>{children}</a>
  ),
  span: ({ node, children }) => {
    const math = node?.properties['dataMath'];
    if (typeof math !== 'string') return <span>{children}</span>;
    return node?.properties['dataMathBlock']
      ? <BlockMath math={math} /> : <InlineMath math={math} />;
  },
  // Model-authored remote images can act as tracking pixels. Keep this study
  // interface text-only so reading an answer never fetches those images.
  img: ({ alt }: MarkdownImageProps) => (
    <span className="message-image-omitted">[Image omitted{alt ? `: ${alt}` : ''}]</span>
  ),
};

interface AnswerSource { key: string; label: string; url?: string }

// Work on parsed Markdown so code, escaped literals, and link destinations remain intact.
function remarkMessagePresentation({ isAssistant, sourceId }: { isAssistant: boolean; sourceId: string }) {
  return (tree: Root, file: VFile) => {
    const original = String(file);
    const sources: AnswerSource[] = [];
    const definitions = new Map(tree.children.filter(node => node.type === 'definition').map(node => [node.identifier.toUpperCase(), node.url]));
    const reference = (source: AnswerSource): PhrasingContent => {
      let index = sources.findIndex(item => item.key === source.key);
      if (index === -1) { index = sources.length; sources.push(source); }
      return { type: 'link', url: `#${sourceId}-${index + 1}`, children: [{ type: 'text', value: `[${index + 1}]` }],
        data: { hProperties: { className: 'message-source-reference', ariaLabel: `Source ${index + 1}: ${source.label}` } } };
    };
    function textParts(node: Extract<RootContent, { type: 'text' }>): PhrasingContent[] {
      const start = node.position?.start.offset;
      const end = node.position?.end.offset;
      const escaped = start === undefined || end === undefined || /\\[[\]()$]/.test(original.slice(start, end));
      const parts: PhrasingContent[] = [];
      // The self-link branch consumes unsupported labels too, preserving them verbatim.
      const tokens = /!?\[([^\]\n]+)\]\(([^)\n]+)\)|\((Chapter [1-9][0-9]*(?:, p\.\s?[1-9][0-9]*)?|Book, p\.\s?[1-9][0-9]*|Book excerpt)\)/g;
      let last = 0;
      for (const match of node.value.matchAll(tokens)) {
        const offset = match.index;
        if (offset > last) parts.push({ type: 'text', value: node.value.slice(last, offset) });
        const [raw, label, destination, book] = match;
        const selfCitation = !raw.startsWith('!') && label === destination && /^(Chapter [1-9][0-9]*(?:, p\.\s?[1-9][0-9]*)?|Book, p\.\s?[1-9][0-9]*|Book excerpt)$/.test(label ?? '');
        if (isAssistant && !escaped && (book || selfCitation)) {
          const citation = (book || label).replace(/p\.\s*/g, 'p.');
          parts.push(reference({ key: citation, label: citation }));
        } else parts.push({ type: 'text', value: raw });
        last = offset + raw.length;
      }
      if (last < node.value.length) parts.push({ type: 'text', value: node.value.slice(last) });
      return parts;
    }
    function visit(node: Root | RootContent, collectSources = true) {
      if (!('children' in node)) return;
      const allowSources = collectSources && node.type !== 'link' && node.type !== 'linkReference';
      node.children = node.children.flatMap((child): typeof child[] => {
        if (child.type === 'math' || child.type === 'inlineMath') {
          const offset = child.position?.start.offset;
          const block = child.type === 'math' || (offset !== undefined && original.slice(offset, offset + 2) === '$$');
          return [{ type: 'text', value: '', data: { hName: 'span', hProperties: { dataMath: child.value, dataMathBlock: block } } }];
        }
        if (child.type === 'text') return allowSources ? textParts(child) : [child];
        const label = child.type === 'link' || child.type === 'linkReference'
          ? child.children.map(part => 'value' in part ? part.value : '').join('') : '';
        // Link labels retain math formatting while citations inside them remain part of the label.
        visit(child, allowSources);
        if (isAssistant && allowSources && (child.type === 'link' || child.type === 'linkReference')) {
          const destination = child.type === 'link' ? child.url : definitions.get(child.identifier.toUpperCase());
          if (!destination) return [child];
          let url: URL;
          try { url = new URL(destination); } catch { return [child]; }
          if (url.protocol !== 'https:' && url.protocol !== 'http:') return [child];
          const rawUrl = /^(?:https?:\/\/|www\.)\S+$/.test(label);
          const source = { key: url.href, url: url.href, label: rawUrl ? url.hostname : label || url.hostname };
          const citation = reference(source);
          // Named links carry meaning in a sentence; raw URLs only need the reference.
          return rawUrl ? [citation] : [...child.children, { type: 'text', value: ' ' }, citation];
        }
        return [child];
      }) as typeof node.children;
      if (node.type === 'paragraph' && node.children.some(child => child.data?.hProperties?.dataMathBlock)) {
        node.data = { ...node.data, hName: 'div' };
      }
    }
    visit(tree);
    if (sources.length) tree.children.push({ type: 'blockquote', data: { hName: 'details', hProperties: { className: 'message-sources' } }, children: [
      { type: 'paragraph', data: { hName: 'summary' }, children: [{ type: 'text', value: `Sources (${sources.length})` }] },
      { type: 'list', ordered: true, children: sources.map((source, index) => ({ type: 'listItem', spread: false,
        data: { hProperties: { id: `${sourceId}-${index + 1}`, tabIndex: -1 } }, children: [{ type: 'paragraph', children: source.url
          ? [{ type: 'link', url: source.url, children: [{ type: 'text', value: source.label }] },
            ...(source.label !== source.url ? [{ type: 'text' as const, value: ` (${source.url})` }] : [])]
          : [{ type: 'text', value: source.label }] }] })) },
    ] });
  };
}

function MessageContent({ content, isAssistant }: { content: string; isAssistant: boolean }) {
  const sourceId = useId();
  return <div className="message-markdown">
    <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath, [remarkMessagePresentation, { isAssistant, sourceId }]]} components={mdComponents}>
      {content}
    </ReactMarkdown>
  </div>;
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
            {/* Stored requests retain model node context; only user presentation returns to the question. */}
            <MessageContent content={msg.role === 'user' ? displayUserMessageContent(msg.content) : msg.content} isAssistant={msg.role === 'assistant'} />
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
