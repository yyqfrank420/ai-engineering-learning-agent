import { useEffect, useRef, useState } from 'react';
import type { GraphCandidate } from '../../types';
import { agentTransport } from '../../services/agentTransport';
import { D3Graph } from './D3Graph';
import { measureDiagram } from './diagramMeasurement';


interface HiddenGraphEvaluatorProps {
  candidate: GraphCandidate | null;
}

export function HiddenGraphEvaluator({ candidate }: HiddenGraphEvaluatorProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const submittedRef = useRef<string | null>(null);
  const [layoutReadyEvaluationId, setLayoutReadyEvaluationId] = useState<string | null>(null);
  const viewportWidth = candidate ? candidate.criteria.viewport_width : 0;
  const viewportHeight = candidate ? candidate.criteria.viewport_height : 0;

  useEffect(() => {
    if (
      !candidate
      || layoutReadyEvaluationId !== candidate.evaluationId
      || submittedRef.current === candidate.evaluationId
    ) return;
    const controller = new AbortController();
    const { signal } = controller;
    const evaluate = async () => {
      let report: ReturnType<typeof measureDiagram> = {
        viewport_width: viewportWidth,
        viewport_height: viewportHeight,
        rendered_nodes: 0,
        rendered_edges: 0,
        overlap_count: 0,
        clipped_nodes: 0,
        clipped_edges: 0,
        minimum_text_px: 0,
        overview_required_edge_labels: 0,
        visible_overview_required_edge_labels: 0,
        grouped_nodes: 0,
        group_labelled_nodes: 0,
        visible_group_boundaries: 0,
        group_boundary_overlap_count: 0,
      };
      let screenshot: string;
      try {
        const svg = rootRef.current?.querySelector('svg');
        if (!svg) throw new Error('Missing candidate SVG');
        report = measureDiagram(svg);
        screenshot = await rasteriseSvg(svg, {
          width: viewportWidth,
          height: viewportHeight,
        }, signal);
      } catch {
        if (signal.aborted) return;
        // This image carries a failure report only; it can never approve a graph.
        report.capture_error = 'Browser diagram capture failed';
        screenshot = blankScreenshot;
      }
      if (signal.aborted) return;
      await submitWithRetry(
        candidate.evaluationId,
        candidate.graphVersion,
        report,
        screenshot,
        signal,
      );
      if (!signal.aborted) submittedRef.current = candidate.evaluationId;
    };
    void evaluate();
    return () => controller.abort();
  }, [candidate, layoutReadyEvaluationId, viewportHeight, viewportWidth]);

  if (!candidate) return null;
  return (
    <div
      ref={rootRef}
      aria-hidden="true"
      inert
      style={{
        position: 'fixed',
        left: '-12000px',
        top: 0,
        width: viewportWidth,
        height: viewportHeight,
        opacity: 0,
        pointerEvents: 'none',
        zIndex: -1,
      }}
    >
      <D3Graph
        key={candidate.evaluationId}
        graphData={candidate.data}
        currentStep={-1}
        activeNodeIds={new Set<string>()}
        onNodeClick={() => undefined}
        minimumTitlePx={candidate.criteria.minimum_text_px}
        layoutReadiness="geometry"
        onLayoutReady={() => setLayoutReadyEvaluationId(candidate.evaluationId)}
      />
    </div>
  );
}


async function submitWithRetry(
  evaluationId: string,
  graphVersion: string | null | undefined,
  report: ReturnType<typeof measureDiagram>,
  screenshot: string,
  signal: AbortSignal,
): Promise<void> {
  const delays = [0, 250, 750, 1_500];
  for (const delay of delays) {
    if (delay > 0) await waitForRetry(delay, signal);
    if (signal.aborted) return;
    try {
      if (agentTransport.submitDiagramEvaluation(evaluationId, graphVersion, report, screenshot)) {
        return;
      }
    } catch {
      // A disconnected transport may throw; the same bounded retry budget applies.
    }
  }
  // The server deadline owns transport failure after this bounded upload attempt.
}


async function rasteriseSvg(
  svg: SVGSVGElement,
  viewport: { width: number; height: number },
  signal: AbortSignal,
): Promise<string> {
  const clone = svg.cloneNode(true) as SVGSVGElement;
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  clone.setAttribute('width', String(viewport.width));
  clone.setAttribute('height', String(viewport.height));
  const xml = new XMLSerializer().serializeToString(clone);
  const url = URL.createObjectURL(new Blob([xml], { type: 'image/svg+xml;charset=utf-8' }));
  try {
    const image = await loadImage(url, signal);
    const canvas = document.createElement('canvas');
    canvas.width = viewport.width;
    canvas.height = viewport.height;
    const context = canvas.getContext('2d');
    if (!context) throw new Error('Canvas is unavailable');
    context.fillStyle = '#080d14';
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/jpeg', 0.58);
  } finally {
    URL.revokeObjectURL(url);
  }
}


function loadImage(url: string, signal: AbortSignal): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    const finish = (loaded: boolean) => {
      window.clearTimeout(timer);
      signal.removeEventListener('abort', abort);
      image.onload = null;
      image.onerror = null;
      if (loaded) resolve(image);
      else {
        image.src = '';
        reject(new Error('SVG capture unavailable'));
      }
    };
    const abort = () => finish(false);
    const timer = window.setTimeout(abort, 3_000);
    image.onload = () => finish(true);
    image.onerror = abort;
    signal.addEventListener('abort', abort, { once: true });
    if (signal.aborted) abort();
    else image.src = url;
  });
}

function waitForRetry(delay: number, signal: AbortSignal): Promise<void> {
  return new Promise(resolve => {
    const finish = () => {
      window.clearTimeout(timer);
      signal.removeEventListener('abort', finish);
      resolve();
    };
    const timer = window.setTimeout(finish, delay);
    signal.addEventListener('abort', finish, { once: true });
    if (signal.aborted) finish();
  });
}

// A valid PNG independent of canvas availability, used only for failed capture.
const blankScreenshot = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGNgAAIAAAUAAXpeqz8AAAAASUVORK5CYII=';
