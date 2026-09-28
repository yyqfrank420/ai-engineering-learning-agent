import { act, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('./D3Graph', async () => {
  const React = await import('react');
  return {
    D3Graph: ({
      minimumTitlePx,
      layoutReadiness,
      onLayoutReady,
    }: {
      minimumTitlePx?: number;
      layoutReadiness?: string;
      onLayoutReady?: (key: string) => void;
    }) => {
      const onLayoutReadyRef = React.useRef(onLayoutReady);
      React.useEffect(() => onLayoutReadyRef.current?.('candidate-layout'), []);
      return (
        <svg width="100%" height="100%" data-minimum-title-px={minimumTitlePx} data-layout-readiness={layoutReadiness}>
          <text>{'学生 & <Teacher> #1: café 🧠'}</text>
        </svg>
      );
    },
  };
});

vi.mock('./diagramMeasurement', () => ({
  measureDiagram: vi.fn(() => ({
    viewport_width: 1440,
    viewport_height: 960,
    rendered_nodes: 2,
    rendered_edges: 1,
    overlap_count: 0,
    clipped_nodes: 0,
    clipped_edges: 0,
    minimum_text_px: 12,
    overview_required_edge_labels: 1,
    visible_overview_required_edge_labels: 1,
    grouped_nodes: 0,
    group_labelled_nodes: 0,
    visible_group_boundaries: 0,
    group_boundary_overlap_count: 0,
  })),
}));

vi.mock('../../services/agentTransport', () => ({
  agentTransport: {
    submitDiagramEvaluation: vi.fn(() => true),
  },
}));

import { agentTransport } from '../../services/agentTransport';
import type { GraphCandidate } from '../../types';
import { measureDiagram } from './diagramMeasurement';
import { HiddenGraphEvaluator } from './HiddenGraphEvaluator';
import { DIAGRAM_EVALUATION_VIEWPORT } from './graphLayout';


const candidate: GraphCandidate = {
  evaluationId: 'evaluation-1',
  graphVersion: 'graph-v1',
  criteria: {
    viewport_width: 1440,
    viewport_height: 960,
    minimum_text_px: 11,
  },
  data: {
    graph_type: 'architecture',
    title: 'Private candidate',
    nodes: [],
    edges: [{
      source: 'one',
      target: 'two',
      label: 'routes request',
      technology: 'HTTPS',
      sync: 'sync',
      description: 'Carries a request.',
    }],
    sequence: [],
  },
};

let imageSources: string[] = [];
let rasterizedCanvasSize: { width: number; height: number } | null = null;


describe('HiddenGraphEvaluator browser boundary', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    vi.stubGlobal('URL', {
      createObjectURL: vi.fn(() => 'blob:candidate'),
      revokeObjectURL: vi.fn(),
    });
    imageSources = [];
    class LoadedImage {
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;

      set src(value: string) {
        imageSources.push(value);
        queueMicrotask(() => this.onload?.());
      }
    }
    vi.stubGlobal('Image', LoadedImage);
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
      fillStyle: '',
      fillRect: vi.fn(),
      drawImage: vi.fn(),
    } as unknown as CanvasRenderingContext2D);
    rasterizedCanvasSize = null;
    vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockImplementation(function (
      this: HTMLCanvasElement,
    ) {
      rasterizedCanvasSize = { width: this.width, height: this.height };
      return 'data:image/jpeg;base64,candidate';
    });
    vi.mocked(agentTransport.submitDiagramEvaluation).mockReturnValue(true);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('measures, rasterizes, and submits one private candidate', async () => {
    const view = render(
      <HiddenGraphEvaluator candidate={candidate} />,
    );

    await act(async () => vi.runAllTimersAsync());

    expect(measureDiagram).toHaveBeenCalledWith(expect.any(SVGSVGElement));
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();
    expect(imageSources).toHaveLength(1);
    expect(imageSources[0]).toMatch(/^data:image\/svg\+xml;charset=utf-8,%3Csvg/);
    const xml = decodeURIComponent(imageSources[0].split(',')[1]);
    expect(xml).toContain('xmlns="http://www.w3.org/2000/svg"');
    expect(xml).toContain('width="1440"');
    expect(xml).toContain('height="960"');
    expect(xml).toContain('<text>学生 &amp; &lt;Teacher&gt; #1: café 🧠</text>');
    expect(imageSources[0]).not.toContain('#');
    const hiddenRoot = view.container.querySelector('[aria-hidden="true"]') as HTMLElement;
    expect(hiddenRoot.style.width).toBe(`${DIAGRAM_EVALUATION_VIEWPORT.width}px`);
    expect(hiddenRoot.style.height).toBe(`${DIAGRAM_EVALUATION_VIEWPORT.height}px`);
    expect(rasterizedCanvasSize).toEqual(DIAGRAM_EVALUATION_VIEWPORT);
    expect(view.container.querySelector('svg')?.getAttribute('data-minimum-title-px')).toBe('11');
    expect(view.container.querySelector('svg')?.getAttribute('data-layout-readiness')).toBe('geometry');
    expect(agentTransport.submitDiagramEvaluation).toHaveBeenCalledWith(
      'evaluation-1',
      'graph-v1',
      expect.objectContaining({ overlap_count: 0 }),
      'data:image/jpeg;base64,candidate',
    );

    view.rerender(<HiddenGraphEvaluator candidate={candidate} />);
    await act(async () => vi.runAllTimersAsync());
    expect(agentTransport.submitDiagramEvaluation).toHaveBeenCalledTimes(1);
  });

  it('evaluates a new request for an unchanged candidate', async () => {
    const view = render(
      <HiddenGraphEvaluator candidate={candidate} />,
    );
    await act(async () => vi.runAllTimersAsync());

    view.rerender(
      <HiddenGraphEvaluator
        candidate={{ ...candidate, evaluationId: 'evaluation-2' }}
      />,
    );
    await act(async () => vi.runAllTimersAsync());

    expect(agentTransport.submitDiagramEvaluation).toHaveBeenCalledTimes(2);
    expect(agentTransport.submitDiagramEvaluation).toHaveBeenNthCalledWith(
      2,
      'evaluation-2',
      'graph-v1',
      expect.any(Object),
      'data:image/jpeg;base64,candidate',
    );
  });

  it('retries a temporarily unavailable transport with bounded delays', async () => {
    vi.mocked(agentTransport.submitDiagramEvaluation)
      .mockReturnValueOnce(false)
      .mockReturnValueOnce(false)
      .mockReturnValueOnce(true);
    render(<HiddenGraphEvaluator candidate={candidate} />);

    await act(async () => vi.runAllTimersAsync());

    expect(agentTransport.submitDiagramEvaluation).toHaveBeenCalledTimes(3);
  });

  it('submits a failure report with a tiny fallback image when capture fails', async () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
    vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue(
      expect.stringContaining('data:image/png;base64,'),
    );
    render(<HiddenGraphEvaluator candidate={candidate} />);

    await act(async () => vi.runAllTimersAsync());

    expect(agentTransport.submitDiagramEvaluation).toHaveBeenCalledWith(
      'evaluation-1',
      'graph-v1',
      expect.objectContaining({ capture_error: 'Browser diagram capture failed' }),
      expect.stringContaining('data:image/png;base64,'),
    );
  });

  it('reports measurement exceptions without exposing exception text', async () => {
    vi.mocked(measureDiagram).mockImplementationOnce(() => { throw new Error('secret'); });
    render(<HiddenGraphEvaluator candidate={candidate} />);
    await act(async () => vi.runAllTimersAsync());
    expect(agentTransport.submitDiagramEvaluation).toHaveBeenCalledWith(
      'evaluation-1', 'graph-v1',
      expect.objectContaining({ rendered_nodes: 0, capture_error: 'Browser diagram capture failed' }),
      expect.stringContaining('data:image/png;base64,'),
    );
  });

  it('bounds a stalled image and sends a failure rather than an approval', async () => {
    vi.stubGlobal('Image', class { src = ''; onload = null; onerror = null; });
    render(<HiddenGraphEvaluator candidate={candidate} />);
    await act(async () => vi.advanceTimersByTimeAsync(2_999));
    expect(agentTransport.submitDiagramEvaluation).not.toHaveBeenCalled();
    await act(async () => vi.advanceTimersByTimeAsync(1));
    expect(agentTransport.submitDiagramEvaluation).toHaveBeenCalledWith(
      'evaluation-1', 'graph-v1',
      expect.objectContaining({ capture_error: 'Browser diagram capture failed' }),
      expect.stringContaining('data:image/png;base64,'),
    );
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();
  });

  it('reports an image load failure without approving the candidate', async () => {
    vi.stubGlobal('Image', class {
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      set src(value: string) {
        if (value) queueMicrotask(() => this.onerror?.());
      }
    });
    render(<HiddenGraphEvaluator candidate={candidate} />);
    await act(async () => vi.runAllTimersAsync());
    expect(agentTransport.submitDiagramEvaluation).toHaveBeenCalledExactlyOnceWith(
      'evaluation-1', 'graph-v1',
      expect.objectContaining({ capture_error: 'Browser diagram capture failed' }),
      expect.stringContaining('data:image/png;base64,'),
    );
    expect(vi.getTimerCount()).toBe(0);
  });

  it('cancels image handlers and timers when a candidate is replaced', async () => {
    const images: { src: string; onload: (() => void) | null; onerror: (() => void) | null }[] = [];
    vi.stubGlobal('Image', class {
      src = '';
      onload = null;
      onerror = null;
      constructor() { images.push(this); }
    });
    const view = render(<HiddenGraphEvaluator candidate={candidate} />);
    view.rerender(<HiddenGraphEvaluator candidate={{ ...candidate, evaluationId: 'replacement' }} />);
    expect(images[0].src).toBe('');
    expect(images[0].onload).toBeNull();
    expect(images[0].onerror).toBeNull();
    await act(async () => vi.advanceTimersByTimeAsync(3_000));
    expect(agentTransport.submitDiagramEvaluation).toHaveBeenCalledTimes(1);
    expect(vi.mocked(agentTransport.submitDiagramEvaluation).mock.calls[0][0]).toBe('replacement');
    view.unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('stops retry timers on unmount', async () => {
    vi.mocked(agentTransport.submitDiagramEvaluation).mockReturnValue(false);
    const view = render(<HiddenGraphEvaluator candidate={candidate} />);
    await act(async () => vi.advanceTimersByTimeAsync(0));
    expect(agentTransport.submitDiagramEvaluation).toHaveBeenCalledTimes(1);
    view.unmount();
    await act(async () => vi.runAllTimersAsync());
    expect(agentTransport.submitDiagramEvaluation).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('contains exhausted transport failures without a second retry budget', async () => {
    vi.mocked(agentTransport.submitDiagramEvaluation).mockImplementation(() => { throw new Error('offline'); });
    render(<HiddenGraphEvaluator candidate={candidate} />);
    await act(async () => vi.runAllTimersAsync());
    expect(agentTransport.submitDiagramEvaluation).toHaveBeenCalledTimes(4);
  });

  it('cancels pending work on unmount and renders nothing without a candidate', async () => {
    const view = render(
      <HiddenGraphEvaluator candidate={candidate} />,
    );
    view.unmount();
    await act(async () => vi.runAllTimersAsync());
    expect(agentTransport.submitDiagramEvaluation).not.toHaveBeenCalled();

    const empty = render(<HiddenGraphEvaluator candidate={null} />);
    expect(empty.container.firstChild).toBeNull();
  });
});
