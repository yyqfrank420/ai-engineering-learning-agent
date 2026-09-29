import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { MessageList } from './MessageList';

describe('MessageList', () => {
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

    expect(screen.getByText(labels.map((label) => `(${label})`).join(' '))).toBeTruthy();
    expect(container.querySelector('a')).toBeNull();
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

  it('renders a stable empty state', () => {
    render(<MessageList messages={[]} />);

    expect(screen.getByText('Ask a question about AI Engineering…')).toBeTruthy();
  });
});
