import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { MessageList } from './MessageList';
import { formatNodeQuestionRequest, mapThreadMessages } from '../../utils/threadState';

describe('MessageList', () => {
  it('projects saved user node requests after reload while preserving assistant and retry data', () => {
    const request = formatNodeQuestionRequest('Explain this node', { id: 'n1', label: 'Node label' });
    const user = mapThreadMessages([{ id: 'user', role: 'user', content: request, created_at: '' }])[0];
    const assistant = { id: 'assistant', role: 'assistant' as const, content: request, retryRequest: { content: request, complexity: 'auto' as const, graphMode: 'on' as const, diagramRequested: false, researchEnabled: true, graphAction: 'answer' as const, expectedGraphVersion: null } };
    const onRetryMessage = vi.fn();
    const view = render(<MessageList messages={[user, assistant]} onRetryMessage={onRetryMessage} />);
    expect(screen.getByTestId('message-user').textContent).toBe('Explain this node');
    expect(screen.getByTestId('message-assistant').textContent).toContain('Selected component:');
    fireEvent.click(screen.getByRole('button', { name: 'Retry generation' }));
    expect(onRetryMessage).toHaveBeenCalledExactlyOnceWith(assistant);
    expect(user.content).toBe(request);
    expect(assistant.retryRequest.content).toBe(request);
    view.rerender(<MessageList messages={[{ ...user }, assistant]} onRetryMessage={onRetryMessage} />);
    expect(screen.getByTestId('message-user').textContent).toBe('Explain this node');
  });

  it('keeps activity in conversation order and preserves disclosure identity as an answer arrives', () => {
    const activity = { duration_ms: 1200, steps: [{ sequence: 0, kind: 'update' as const,
      phase: 'context' as const, status: 'active' as const, text: 'I am checking your request.', elapsed_ms: 0 }] };
    const liveActivity = { clientRequestId: 'run', startedAt: Date.now(), activity };
    const user = { id: 'user', role: 'user' as const, content: 'Question' };
    const view = render(<MessageList messages={[user]} liveActivity={liveActivity} />);
    const details = view.container.querySelector('details')!;
    expect(details.open).toBe(true);
    const answer = { id: 'answer', role: 'assistant' as const, clientRequestId: 'run', content: 'Answer' };
    view.rerender(<MessageList messages={[user, answer]} liveActivity={liveActivity} />);
    expect(view.container.querySelector('details')).toBe(details);
    expect(details.compareDocumentPosition(screen.getByText('Answer')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    view.rerender(<MessageList messages={[user, { ...answer, activity }]} />);
    expect(view.container.querySelector('details')).toBe(details);
    expect(details.open).toBe(false);
    expect(screen.getByText('Worked for 1s')).toBeTruthy();
    expect(screen.queryByText(/Working for/)).toBeNull();
    expect(view.container.querySelector('[data-testid="message-assistant"]')?.textContent).toBe('Answer');
  });

  it('renders saved activity only for the owning assistant and excludes it from answer content', () => {
    const activity = { duration_ms: 62_000, steps: [{ sequence: 0, kind: 'tool' as const,
      phase: 'book' as const, status: 'complete' as const, text: 'Searched the book', elapsed_ms: 1000 }] };
    const view = render(<MessageList messages={[{ id: 'first', role: 'assistant', content: 'First answer', activity },
      { id: 'second', role: 'assistant', content: 'Second answer' }]} />);
    expect(view.container.querySelectorAll('details')).toHaveLength(1);
    expect(view.container.querySelector('details')?.open).toBe(false);
    expect(screen.getByText('Worked for 1m 2s')).toBeTruthy();
    expect(screen.getAllByTestId('message-assistant').map(message => message.textContent)).toEqual(['First answer', 'Second answer']);
  });

  it('shows retry only on an explicitly failed assistant message and blocks repeat clicks while busy', () => {
    const onRetryMessage = vi.fn();
    const failed = { id: 'failed', role: 'assistant' as const, content: 'Diagram unchanged', retryRequest: {
      content: 'Expand retrieval', complexity: 'auto' as const, graphMode: 'on' as const,
      diagramRequested: true, researchEnabled: true, graphAction: 'extend' as const,
      expectedGraphVersion: 'old',
    } };
    const messages = [
      { id: 'success', role: 'assistant' as const, content: 'Done' },
      { id: 'user', role: 'user' as const, content: 'Expand retrieval' },
      failed,
    ];
    const view = render(<MessageList messages={messages} onRetryMessage={onRetryMessage} />);
    const retry = screen.getByRole('button', { name: 'Retry generation' });
    expect(retry.closest('[data-testid="message-assistant"]')?.textContent).toContain('Diagram unchanged');
    fireEvent.click(retry);
    expect(onRetryMessage).toHaveBeenCalledExactlyOnceWith(failed);
    view.rerender(<MessageList messages={messages} onRetryMessage={onRetryMessage} retryDisabled retryingMessageId="failed" />);
    const busy = screen.getByRole('button', { name: 'Retrying…' }) as HTMLButtonElement;
    expect(busy.disabled).toBe(true);
    fireEvent.click(busy);
    expect(onRetryMessage).toHaveBeenCalledTimes(1);
  });
  it('follows near-bottom content, preserves a reader above it, and lets them jump back', () => {
    const view = render(<MessageList messages={[]} />);
    const list = screen.getByRole('region', { name: 'Conversation' });
    let height = 1000;
    let top = 0;
    Object.defineProperties(list, {
      scrollHeight: { configurable: true, get: () => height },
      clientHeight: { configurable: true, get: () => 300 },
      scrollTop: { configurable: true, get: () => top, set: value => { top = Math.max(0, Math.min(value, height - 300)); } },
    });
    const messages = [{ id: 'q1', role: 'user' as const, content: 'Question' }, { id: 'a1', role: 'assistant' as const, content: 'First answer' }];
    view.rerender(<MessageList messages={messages} />);
    expect(top).toBe(700);
    height = 1100;
    view.rerender(<MessageList messages={[messages[0], { ...messages[1], content: 'First answer continues' }]} />);
    expect(top).toBe(800);
    list.scrollTop = 200;
    fireEvent.scroll(list);
    view.rerender(<MessageList messages={[messages[0], { ...messages[1], content: 'First answer continues', graphRevisionId: 'saved' }]} />);
    expect(screen.queryByRole('button', { name: 'Jump to latest' })).toBeNull();
    height = 1200;
    view.rerender(<MessageList messages={[messages[0], { ...messages[1], content: 'More answer arrives' }]} />);
    expect(top).toBe(200);
    const jump = screen.getByRole('button', { name: 'Jump to latest' });
    jump.focus();
    fireEvent.click(jump);
    expect(top).toBe(900);
    expect(document.activeElement).toBe(list);
    expect(screen.queryByRole('button', { name: 'Jump to latest' })).toBeNull();
  });

  it('does not move selected text during updates, but a new request and conversation reach the latest', () => {
    const first = { id: 'a1', role: 'assistant' as const, content: 'Selectable answer' };
    const view = render(<MessageList messages={[first]} />);
    const list = screen.getByRole('region', { name: 'Conversation' });
    let height = 1200;
    let top = 0;
    Object.defineProperties(list, {
      scrollHeight: { configurable: true, get: () => height },
      clientHeight: { configurable: true, value: 300 },
      scrollTop: { configurable: true, get: () => top, set: value => { top = Math.max(0, Math.min(value, height - 300)); } },
    });
    list.scrollTop = 900;
    fireEvent.scroll(list);
    const range = document.createRange();
    range.selectNodeContents(screen.getByText('Selectable answer'));
    window.getSelection()!.removeAllRanges();
    window.getSelection()!.addRange(range);
    expect(window.getSelection()!.isCollapsed).toBe(false);
    fireEvent(document, new Event('selectionchange'));
    height = 1400;
    view.rerender(<MessageList messages={[{ ...first, content: 'Selectable answer continues' }]} />);
    expect(list.scrollTop).toBe(900);
    window.getSelection()!.removeAllRanges();
    list.scrollTop = 100;
    fireEvent.scroll(list);
    view.rerender(<MessageList messages={[first, { id: 'q2', role: 'user', content: 'New request' }]} />);
    expect(list.scrollTop).toBe(1100);
    list.scrollTop = 100;
    fireEvent.scroll(list);
    view.rerender(<MessageList messages={[{ id: 'other-thread', role: 'assistant', content: 'Loaded conversation' }]} />);
    expect(list.scrollTop).toBe(1100);
  });

  it('shows assistant prose without bubble chrome or raw node identifiers', () => {
    const { container } = render(<MessageList messages={[{ id: 'a', role: 'assistant', kind: 'explanation', title: 'A useful heading', content: 'Explanation', relatedNodeIds: ['n1', 'n2'] }]} />);
    expect(screen.getByRole('heading', { name: 'A useful heading' })).toBeTruthy();
    expect(container.querySelector('.message-assistant')).toBeTruthy();
    expect(container.querySelector('.message-user')).toBeNull();
    expect(screen.queryByText('n1')).toBeNull();
  });

  it('links only assistant diagrams with a real saved revision and respects busy state', () => {
    const onViewDiagram = vi.fn();
    const messages = [
      { id: 'known', role: 'assistant' as const, content: 'Saved answer', graphRevisionId: 'r1' },
      { id: 'unknown', role: 'assistant' as const, content: 'Unknown version', graphRevisionId: 'missing' },
      { id: 'user', role: 'user' as const, content: 'User text', graphRevisionId: 'r1' },
    ];
    const view = render(<MessageList messages={messages} revisionIds={['r1']} viewedRevisionId="r1" onViewDiagram={onViewDiagram} />);
    expect(screen.getAllByRole('button', { name: 'View diagram' })).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'View diagram' }).getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(screen.getByRole('button', { name: 'View diagram' }));
    expect(onViewDiagram).toHaveBeenCalledWith('r1');
    view.rerender(<MessageList messages={messages} revisionIds={['r1']} onViewDiagram={onViewDiagram} historyDisabled />);
    expect((screen.getByRole('button', { name: 'View diagram' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByRole('button', { name: 'View diagram' }).getAttribute('aria-pressed')).toBe('false');
  });

  it('keeps inline code inline and renders fenced code in one valid pre block', () => {
    const { container } = render(
      <MessageList
        messages={[
          {
            id: 'assistant-code',
            role: 'assistant',
            content: 'Route through `response_generator`.\n\n```ts\nconst safe = true;\n```',
          },
        ]}
      />,
    );

    const inlineCode = screen.getByText('response_generator');
    expect(inlineCode.tagName).toBe('CODE');
    expect(inlineCode.closest('p')).not.toBeNull();
    expect(inlineCode.closest('pre')).toBeNull();
    expect(container.querySelectorAll('pre')).toHaveLength(1);
    expect(container.querySelector('pre pre')).toBeNull();
    expect(container.querySelector('pre code.language-ts')).not.toBeNull();
  });

  it('does not load model-authored remote images', () => {
    const { container } = render(
      <MessageList
        messages={[
          {
            id: 'assistant-1',
            role: 'assistant',
            content: '![tracking pixel](https://tracker.example/pixel.gif)',
          },
        ]}
      />,
    );

    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByText('[Image omitted: tracking pixel]')).toBeTruthy();
  });

  it('renders the supported study markdown, math, and explanation metadata', () => {
    const { container } = render(
      <MessageList
        messages={[
          {
            id: 'user-rich',
            role: 'user',
            content: [
              '# Architecture',
              '## Retrieval',
              '### Ranking',
              '**Strong** and *grounded* with $x + y$.',
              '- semantic search',
              '1. retrieve',
              '> Preserve evidence.',
              '| Layer | Tool |\n| --- | --- |\n| API | FastAPI |',
              '---',
              '[Book](https://example.com/book)',
              '$$z = x + y$$',
            ].join('\n\n'),
          },
          {
            id: 'assistant-explanation',
            role: 'assistant',
            kind: 'explanation',
            title: 'Why retrieval matters',
            content: 'Evidence reaches the answer.',
            relatedNodeIds: ['retrieval_api', 'vector_store', 'ranker', 'answer', 'ignored'],
            isStreaming: true,
          },
        ]}
      />,
    );

    expect(screen.getByRole('heading', { level: 1, name: 'Architecture' })).toBeTruthy();
    expect(screen.getByRole('heading', { level: 2, name: 'Retrieval' })).toBeTruthy();
    expect(screen.getByRole('heading', { level: 3, name: 'Ranking' })).toBeTruthy();
    expect(screen.getByText('Strong').tagName).toBe('STRONG');
    expect(screen.getByText('grounded').tagName).toBe('EM');
    expect(container.querySelector('blockquote')).not.toBeNull();
    expect(container.querySelector('table')).not.toBeNull();
    expect(container.querySelector('hr')).not.toBeNull();
    expect(screen.getByRole('link', { name: 'Book' })).toHaveProperty('target', '_blank');
    expect(container.querySelectorAll('.katex')).not.toHaveLength(0);
    expect(screen.getByText('Why retrieval matters')).toBeTruthy();
    expect(screen.queryByText('retrieval api')).toBeNull();
    expect(screen.queryByText('answer')).toBeNull();
    expect(screen.queryByText('ignored')).toBeNull();
    expect(screen.getAllByTestId(/message-/)).toHaveLength(2);
  });

  it.each([false, true])('renders duplicated book citation labels during streaming=%s', (isStreaming) => {
    const labels = ['Chapter 10, p.473', 'Book, p.12', 'Chapter 3', 'Book excerpt'];
    const { container } = render(<MessageList messages={[{
      id: 'citations', role: 'assistant', isStreaming,
      content: labels.map((label) => `([${label}](${label}))`).join(' '),
    }]} />);

    expect(container.querySelector('.message-markdown > p')?.textContent).toBe('([1]) ([2]) ([3]) ([4])');
    expect(container.querySelector('details')?.open).toBe(false);
    expect([...container.querySelectorAll('.message-sources li')].map(node => node.textContent)).toEqual(labels);
    expect(container.querySelector('.message-sources a')).toBeNull();
  });

  it('preserves code, real links, mismatched citations and unsupported book labels', () => {
    const citation = '[Chapter 10, p.473](Chapter 10, p.473)';
    const untouched = [
      '[Chapter 10, p.473](Chapter 10, p.474)',
      '[Chapter 0](Chapter 0)',
      '[Chapter 01](Chapter 01)',
      '[Book, p.0](Book, p.0)',
      '[Chapter 2, pp.3-4](Chapter 2, pp.3-4)',
      '[Chapter two](Chapter two)',
      '![Chapter 3](Chapter 3)',
    ];
    const { container } = render(<MessageList messages={[{
      id: 'citation-boundaries', role: 'assistant',
      content: [
        `\`${citation}\``,
        `\`\`\`text\n${citation}\n\`\`\``,
        '[Chapter 10, p.473](https://example.com/book)',
        '[Book excerpt](http://example.com/excerpt)',
        ...untouched,
      ].join('\n\n'),
    }]} />);

    expect(container.querySelectorAll('code')).toHaveLength(2);
    for (const code of container.querySelectorAll('code')) {
      expect(code.textContent?.trim()).toBe(citation);
    }
    expect(screen.getByRole('link', { name: 'Chapter 10, p.473' }).getAttribute('href')).toBe('https://example.com/book');
    expect(screen.getByRole('link', { name: 'Book excerpt' }).getAttribute('href')).toBe('http://example.com/excerpt');
    for (const value of untouched) expect(screen.getByText(value)).toBeTruthy();
  });

  it('preserves intentionally escaped assistant citation literals', () => {
    render(<MessageList messages={[{
      id: 'escaped-citation', role: 'assistant',
      content: String.raw`\[Chapter 3\]\(Chapter 3\)`,
    }]} />);
    expect(screen.getByText('[Chapter 3](Chapter 3)')).toBeTruthy();
  });

  it('preserves user-authored book citation syntax', () => {
    const content = '([Chapter 10, p.473](Chapter 10, p.473))';
    render(<MessageList messages={[{ id: 'user-citation', role: 'user', content }]} />);
    expect(screen.getByText(content)).toBeTruthy();
  });

  it('collects assistant links and book locations into one collapsed deduplicated disclosure', () => {
    const content = 'Read [the guide](https://example.com/guide), https://example.com/guide and <https://example.com/other>. ' +
      'Details (Chapter 6, p.299), repeated (Chapter 6, p.299).\n\n[Reference][guide]\n\n[guide]: https://example.com/guide';
    const { container } = render(<MessageList messages={[{ id: 'sources', role: 'assistant', content }]} />);
    const details = container.querySelector('details')!;
    expect(details.open).toBe(false);
    expect(screen.getByText('Sources (3)')).toBeTruthy();
    expect(details.querySelectorAll('li')).toHaveLength(3);
    const prose = container.querySelector('.message-markdown > p')!;
    expect(prose.textContent).toContain('Read the guide [1], [1] and [2].');
    expect(prose.textContent).not.toContain('https://');
    expect(prose.textContent).not.toContain('Chapter 6');
    expect(content).toContain('(Chapter 6, p.299)');
    const reference = screen.getAllByRole('link', { name: 'Source 3: Chapter 6, p.299' })[0];
    reference.focus();
    fireEvent.click(reference);
    expect(details.open).toBe(true);
    expect(document.activeElement).toBe(details.querySelectorAll('li')[2]);
    expect(details.querySelector('a')?.getAttribute('rel')).toBe('noopener noreferrer');
  });

  it('preserves source disclosure identity and open state during streaming with math', () => {
    const answer = { id: 'stream', role: 'assistant' as const, isStreaming: true, content: 'https://example.com/one $x$' };
    const view = render(<MessageList messages={[answer]} />);
    const details = view.container.querySelector('details')!;
    details.open = true;
    view.rerender(<MessageList messages={[{ ...answer, content: answer.content + ' https://example.com/two $$y = 2$$' }]} />);
    expect(view.container.querySelectorAll('details')).toHaveLength(1);
    expect(view.container.querySelector('details')).toBe(details);
    expect(details.open).toBe(true);
    expect(details.querySelectorAll('li')).toHaveLength(2);
    expect(view.container.querySelectorAll('.katex')).toHaveLength(2);
    expect(view.container.querySelector('p .katex-display')).toBeNull();
  });

  it('preserves code, escaped citations and user links while keeping unsafe links inert', () => {
    const content = String.raw`\[Chapter 3\]\(Chapter 3\) and \*literal\*.

${"`"}https://example.com/code $code$ (Chapter 6, p.299)${"`"}

[unsafe](javascript:alert) ![pixel](https://example.com/pixel)

$\frac{x}{y}$`;
    const { container } = render(<MessageList messages={[
      { id: 'safe', role: 'assistant', content },
      { id: 'user-links', role: 'user', content: 'https://example.com/user (Chapter 6, p.299)' },
    ]} />);
    expect(container.querySelector('details')).toBeNull();
    expect(container.querySelector('code')?.textContent).toContain('$code$');
    expect(container.querySelector('.message-user a')?.getAttribute('href')).toBe('https://example.com/user');
    expect(screen.getByText('unsafe').getAttribute('href')).toBe('');
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelectorAll('.katex')).toHaveLength(1);
  });

  it('parses math before Markdown formatting and preserves escaped dollars and code', () => {
    const { container } = render(<MessageList messages={[{ id: 'math', role: 'assistant', content: String.raw`$a *b* + \{c\}$

$$\begin{matrix}a & b \\ c & d\end{matrix}$$

Escaped \$5 and identifier ${"`"}USER$${"`"}.

https://example.com/math` }]} />);
    expect(container.querySelectorAll('.katex')).toHaveLength(2);
    expect(container.querySelector('em')).toBeNull();
    expect([...container.querySelectorAll('annotation')].map(node => node.textContent)).toEqual([
      String.raw`a *b* + \{c\}`, String.raw`\begin{matrix}a & b \\ c & d\end{matrix}`,
    ]);
    expect(container.querySelector('code')?.textContent).toBe('USER$');
    expect(container.querySelector('.message-markdown')?.textContent).toContain('Escaped $5');
    expect(container.querySelectorAll('details')).toHaveLength(1);
  });

  it.each(['assistant', 'user'] as const)('renders math inside %s link labels without extracting nested book citations', (role) => {
    const content = '[loss $L$ (Chapter 6, p.299)](https://example.com/loss) and [**risk** $R$ (Book excerpt)][risk].\n\n[risk]: https://example.com/risk';
    const { container } = render(<MessageList messages={[{ id: 'math-links', role, content }]} />);
    const markdown = container.querySelector('.message-markdown')!;
    expect(markdown.querySelectorAll('.katex')).toHaveLength(2);
    expect([...markdown.querySelectorAll('annotation')].map(node => node.textContent)).toEqual(['L', 'R']);
    expect(markdown.querySelector('code')).toBeNull();
    expect(markdown.querySelector('strong')?.textContent).toBe('risk');
    if (role === 'assistant') {
      expect(markdown.querySelector('summary')?.textContent).toBe('Sources (2)');
      expect(markdown.querySelectorAll('.message-source-reference')).toHaveLength(2);
      expect(markdown.querySelector('p')?.textContent).toContain('(Chapter 6, p.299)');
      expect(markdown.querySelector('p')?.textContent).toContain('(Book excerpt)');
    } else {
      expect(markdown.querySelector('details')).toBeNull();
      expect(markdown.querySelectorAll('a .katex')).toHaveLength(2);
      expect([...markdown.querySelectorAll('a')].map(node => node.getAttribute('href'))).toEqual([
        'https://example.com/loss', 'https://example.com/risk',
      ]);
    }
  });

  it('renders a stable empty state', () => {
    render(<MessageList messages={[]} />);

    expect(screen.getByText('Ask a question about AI Engineering…')).toBeTruthy();
  });
});
