import '@testing-library/jest-dom/vitest';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { GraphEdge, GraphNode } from '../../types';
import { GlossaryDrawer } from './GlossaryDrawer';
import { NodeDetailPopup } from './NodeDetailPopup';
import { SequenceBar } from './SequenceBar';


const serviceNode: GraphNode = {
  id: 'service',
  label: 'Retrieval API',
  type: 'service',
  technology: 'FastAPI',
  description: 'Retrieves grounded evidence.',
  detail: 'The book recommends measuring retrieval quality.',
  book_refs: ['Chapter 6', 'Chapter 8'],
  tier: 'public',
};

const nodes: GraphNode[] = [
  serviceNode,
  { ...serviceNode, id: 'store', label: 'Vector index', type: 'datastore' },
  { ...serviceNode, id: 'client', label: 'Question input', type: 'client' },
];

const edges: GraphEdge[] = [
  {
    source: 'service',
    target: 'store',
    label: 'queries vector index',
    technology: 'HTTPS',
    sync: 'async',
    description: 'Carries a search request.',
  },
  {
    source: 'client',
    target: 'service',
    label: 'submits question',
    technology: 'JSON',
    sync: 'sync',
    description: 'Carries user input.',
  },
];


describe('graph detail controls', () => {
  it('shows pause while the graph hook owns automatic playback', () => {
    const onStepChange = vi.fn();
    render(<SequenceBar currentStep={1} totalSteps={3} stepDescription="Second step"
      autoPlaying onStepChange={onStepChange} onDismiss={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Pause' }));
    expect(onStepChange).toHaveBeenCalledWith(1);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('shows compact named connections and reveals their metadata on demand', () => {
    const onClose = vi.fn();
    const onTellMeMore = vi.fn();
    const onExpandGraph = vi.fn();
    render(
      <NodeDetailPopup
        nodes={nodes}
        node={serviceNode}
        edges={edges}
        onClose={onClose}
        onTellMeMore={onTellMeMore}
        onExpandGraph={onExpandGraph}
      />,
    );

    expect(screen.getByText('SERVICE')).toBeTruthy();
    expect(screen.getByText('PUBLIC')).toBeTruthy();
    expect(screen.getByText('Chapter 6')).toBeTruthy();
    const connections = screen.getByRole('region', { name: 'Connections' });
    const rows = Array.from(connections.querySelectorAll('summary'));
    expect(rows.map(row => row.textContent)).toEqual(['From Question input', 'To Vector index']);
    expect(screen.getByText('queries vector index')).not.toBeVisible();
    expect(screen.getByText('submits question')).not.toBeVisible();
    expect(screen.getByText('Asynchronous')).not.toBeVisible();
    for (const row of rows) fireEvent.click(row);
    expect(screen.getByText('queries vector index')).toBeVisible();
    expect(screen.getByText('submits question')).toBeVisible();
    expect(screen.getByText('Asynchronous')).toBeVisible();

    fireEvent.click(screen.getByText('Tell me more'));
    fireEvent.click(screen.getByText('Expand graph'));
    const close = screen.getByLabelText('Close node detail');
    fireEvent.mouseEnter(close);
    fireEvent.mouseLeave(close);
    fireEvent.click(close);

    expect(onTellMeMore).toHaveBeenCalledWith(serviceNode);
    expect(onExpandGraph).toHaveBeenCalledWith(serviceNode);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('groups both directions without losing parallel exchanges, self-loops or unnamed peers', () => {
    const allEdges: GraphEdge[] = [
      ...edges,
      { ...edges[0], source: 'store', target: 'service', label: 'returns ranked chunks', technology: '', sync: 'sync' },
      { ...edges[0], label: 'records index usage', technology: 'Kafka' },
      { ...edges[0], target: 'service', label: 'retries retrieval' },
      { ...edges[0], target: 'missing-peer', label: 'exports evidence' },
    ];
    render(<NodeDetailPopup node={serviceNode} nodes={nodes} edges={allEdges}
      onClose={vi.fn()} onTellMeMore={vi.fn()} onExpandGraph={vi.fn()} />);

    const connections = screen.getByRole('region', { name: 'Connections' });
    const rows = Array.from(connections.querySelectorAll('summary'));
    expect(rows).toHaveLength(4);
    expect(rows.map(row => row.textContent)).toEqual(expect.arrayContaining([
      'To and from Vector index', 'From Question input', 'Within this component', 'To missing-peer',
    ]));
    const exchange = rows.find(row => row.textContent === 'To and from Vector index')!;
    fireEvent.click(exchange);
    const group = within(exchange.closest('details')!);
    expect(group.getByText('queries vector index')).toBeVisible();
    expect(group.getByText('returns ranked chunks')).toBeVisible();
    expect(group.getByText('records index usage')).toBeVisible();
    expect(group.getAllByText('To Vector index')).toHaveLength(2);
    expect(group.getByText('From Vector index')).toBeVisible();
    expect(group.getByText('Kafka')).toBeVisible();
    expect(screen.getByText('retries retrieval')).not.toBeVisible();
    expect(screen.getByText('exports evidence')).not.toBeVisible();
  });

  it('keeps disclosures open for enrichment but closes them when inspecting a different node', () => {
    const props = { nodes, edges, onClose: vi.fn(), onTellMeMore: vi.fn(), onExpandGraph: vi.fn() };
    const view = render(<NodeDetailPopup {...props} node={serviceNode} />);
    fireEvent.click(screen.getByText('queries vector index').closest('details')!.querySelector('summary')!);
    expect(screen.getByText('queries vector index')).toBeVisible();

    view.rerender(<NodeDetailPopup {...props} node={{ ...serviceNode, detail: 'Updated source detail.' }} />);
    expect(screen.getByText('queries vector index')).toBeVisible();
    view.rerender(<NodeDetailPopup {...props} node={nodes[1]} />);
    expect(screen.getByText('queries vector index')).not.toBeVisible();
    expect(screen.getByText('queries vector index').closest('details')!.querySelector('summary')!.textContent)
      .toBe('From Retrieval API');
  });

  it('does not claim network accessibility for applied architecture nodes', () => {
    render(
      <NodeDetailPopup
        nodes={nodes}
        node={{ ...serviceNode, design_origin: 'applied' }}
        edges={[]}
        onClose={vi.fn()}
        onTellMeMore={vi.fn()}
        onExpandGraph={vi.fn()}
      />,
    );

    expect(screen.queryByText('PUBLIC')).toBeNull();
    expect(screen.queryByText('PRIVATE')).toBeNull();
  });

  it('keeps decision nodes bounded to explanation', () => {
    render(
      <NodeDetailPopup
        nodes={nodes}
        node={{
          ...serviceNode,
          id: 'gate',
          label: 'Approval Gate',
          type: 'decision',
          technology: '',
          description: '',
          detail: null,
          book_refs: [],
          tier: 'private',
        }}
        edges={[]}
        onClose={vi.fn()}
        onTellMeMore={vi.fn()}
        onExpandGraph={vi.fn()}
      />,
    );

    expect(screen.getByText('PRIVATE')).toBeTruthy();
    expect(screen.queryByText('Expand graph')).toBeNull();
    expect(screen.queryByText('Ask the chat to explain this constraint more clearly.')).toBeNull();
    expect(screen.queryByRole('region', { name: 'Connections' })).toBeNull();
  });

  it('opens, resizes, drags, and closes a glossary derived from response text', () => {
    vi.useFakeTimers();
    const { container } = render(
      <GlossaryDrawer
        graphData={null}
        sourceTexts={['RAG calls an API and searches a vector index.']}
        bottomOffset="1rem"
      />,
    );

    const trigger = screen.getByText('Dictionary');
    fireEvent.click(trigger);
    expect(screen.getByText('RAG')).toBeTruthy();
    expect(screen.getByText('API')).toBeTruthy();
    expect(screen.getByText('Vector index')).toBeTruthy();

    fireEvent.click(screen.getByLabelText('Open larger glossary'));
    expect(screen.getByLabelText('Use compact glossary')).toBeTruthy();
    const header = screen.getByText('Acronyms & terms').parentElement?.parentElement as HTMLElement;
    fireEvent.pointerDown(header, { clientX: 10, clientY: 20 });
    fireEvent.pointerMove(window, { clientX: 30, clientY: 50 });
    expect((container.firstChild as HTMLElement).style.transform).toBe('translate(20px, 30px)');
    fireEvent.pointerUp(window);

    fireEvent.click(trigger);
    expect(screen.getByText('Acronyms & terms')).toBeTruthy();
    act(() => vi.runOnlyPendingTimers());
    fireEvent.click(screen.getByLabelText('Close glossary'));
    expect(screen.queryByText('Acronyms & terms')).toBeNull();
  });

  it('bounds glossary dragging to its canvas and resets the position when the canvas resizes', () => {
    let notifyResize: (() => void) | undefined;
    class TestResizeObserver {
      constructor(callback: ResizeObserverCallback) {
        notifyResize = () => callback([], this as ResizeObserver);
      }
      observe() {}
      unobserve() {}
      disconnect() {}
    }
    vi.stubGlobal('ResizeObserver', TestResizeObserver);
    const box = (left: number, top: number, width: number, height: number): DOMRect => ({
      left, top, width, height, right: left + width, bottom: top + height,
      x: left, y: top, toJSON: () => ({}),
    });
    const view = render(<div className="graph-canvas__surface">
      <GlossaryDrawer graphData={null} sourceTexts={['RAG calls an API.']} bottomOffset="1rem" />
    </div>);
    const canvas = view.container.querySelector<HTMLElement>('.graph-canvas__surface')!;
    const drawer = view.container.querySelector<HTMLElement>('.glossary-drawer')!;
    vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue(box(0, 0, 800, 600));
    vi.spyOn(drawer, 'getBoundingClientRect').mockReturnValue(box(464, 400, 320, 184));
    fireEvent.pointerDown(screen.getByText('Dictionary'), { clientX: 500, clientY: 500 });
    act(() => {
      fireEvent.pointerMove(window, { clientX: -500, clientY: -500 });
      fireEvent.pointerMove(window, { clientX: -600, clientY: -600 });
    });
    expect(drawer.style.transform).toBe('translate(-448px, -384px)');
    fireEvent.pointerCancel(window);
    act(() => notifyResize?.());
    expect(drawer.style.transform).toBe('translate(0px, 0px)');
  });

  it('does not render an empty glossary', () => {
    const { container } = render(
      <GlossaryDrawer graphData={null} sourceTexts={[]} bottomOffset="1rem" />,
    );
    expect(container.firstChild).toBeNull();
  });
});


describe('SequenceBar', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('supports overview navigation, scrubbing, hover feedback, and dismissal', () => {
    const onStepChange = vi.fn();
    const onDismiss = vi.fn();
    const view = render(
      <SequenceBar
        currentStep={-1}
        totalSteps={3}
        stepDescription=""
        onStepChange={onStepChange}
        onDismiss={onDismiss}
      />,
    );

    const previous = screen.getByLabelText('Previous step');
    fireEvent.mouseEnter(previous);
    fireEvent.mouseLeave(previous);
    fireEvent.click(screen.getByLabelText('Next step'));
    fireEvent.click(screen.getByLabelText('Go to step 2'));
    expect(onStepChange).toHaveBeenNthCalledWith(1, 0);
    expect(onStepChange).toHaveBeenNthCalledWith(2, 1);

    view.rerender(
      <SequenceBar
        currentStep={1}
        totalSteps={3}
        stepDescription="Validate evidence"
        onStepChange={onStepChange}
        onDismiss={onDismiss}
      />,
    );
    fireEvent.mouseEnter(screen.getByLabelText('Previous step'));
    fireEvent.mouseLeave(screen.getByLabelText('Previous step'));
    fireEvent.click(screen.getByLabelText('Previous step'));
    expect(onStepChange).toHaveBeenLastCalledWith(0);
    expect(screen.getByText('Validate evidence')).toBeTruthy();

    fireEvent.click(screen.getByLabelText('Exit walkthrough'));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it('autoplays, pauses, completes, and restarts a walkthrough', () => {
    vi.useFakeTimers();
    const onStepChange = vi.fn();
    const view = render(
      <SequenceBar
        currentStep={-1}
        totalSteps={2}
        stepDescription=""
        onStepChange={onStepChange}
        onDismiss={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByLabelText('Play'));
    expect(onStepChange).toHaveBeenCalledWith(0);
    expect(screen.getByLabelText('Pause')).toBeTruthy();
    fireEvent.click(screen.getByLabelText('Pause'));

    fireEvent.click(screen.getByLabelText('Play'));
    view.rerender(
      <SequenceBar
        currentStep={1}
        totalSteps={2}
        stepDescription="Done"
        onStepChange={onStepChange}
        onDismiss={vi.fn()}
      />,
    );
    act(() => vi.advanceTimersByTime(1800));
    expect(onStepChange).toHaveBeenCalledWith(-1);

    fireEvent.click(screen.getByLabelText('Play'));
    expect(onStepChange).toHaveBeenLastCalledWith(0);
  });

  it('uses a counter for long walkthroughs and bounds last-step navigation', () => {
    const onStepChange = vi.fn();
    render(
      <SequenceBar
        currentStep={12}
        totalSteps={13}
        stepDescription="Final review"
        onStepChange={onStepChange}
        onDismiss={vi.fn()}
      />,
    );

    expect(screen.getByText('Step 13 of 13')).toBeTruthy();
    expect(screen.getByLabelText('Next step')).toHaveProperty('disabled', true);
    fireEvent.click(screen.getByLabelText('Next step'));
    expect(onStepChange).not.toHaveBeenCalled();
  });
});
