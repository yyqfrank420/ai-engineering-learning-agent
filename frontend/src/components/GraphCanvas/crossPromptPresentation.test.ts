import { fireEvent, render, screen } from '@testing-library/react';
import { createElement } from 'react';
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';

import type { GraphData, GraphEdge, GraphGroup, GraphNode, GraphViewState, NodeType } from '../../types';
import { graphStructureKey } from '../../utils/graphStructureKey';
import { architectureRegions } from './architectureRegions';
import { D3Graph } from './D3Graph';
import { diagramConnections } from './diagramConnections';
import { GRAPH_LAYOUT_VERSION } from './graphLayout';

type NodeSeed = [id: string, label: string, type: NodeType, lane?: GraphNode['lane']];
type EdgeSeed = [source: string, target: string, label?: string, flow?: GraphEdge['flow']];

function architecture(
  title: string,
  nodeSeeds: NodeSeed[],
  edgeSeeds: EdgeSeed[],
  groupSeeds: Array<[label: string, ids: string[]]>,
): GraphData {
  return {
    graph_type: 'architecture', title, design_origin: 'applied', version: 'same-generation-version',
    nodes: nodeSeeds.map(([id, label, type, lane = 'main']) => ({
      id, label, type, lane, technology: `${type} implementation`, description: `${label} responsibility.`,
      detail: null, design_origin: 'applied',
    })),
    edges: edgeSeeds.map(([source, target, label = 'passes data', flow = 'runtime']) => ({
      source, target, label, flow, technology: 'Typed payload', sync: 'sync', description: label,
    })),
    groups: groupSeeds.map(([label, nodeIds], index): GraphGroup => ({
      id: `zone_${index}`, label, nodeIds, kind: 'runtime',
    })),
    sequence: [],
  };
}

const cases = [
  architecture('Support with escalation', [
    ['user', 'Customer web chat', 'client'], ['api', 'Support gateway', 'gateway'],
    ['agent', 'Support agent', 'service'], ['history', 'Conversation store', 'datastore'],
    ['audit', 'Audit Log', 'datastore', 'bottom'], ['crm', 'Customer CRM', 'external'],
  ], [
    ['user', 'api'], ['api', 'agent'], ['agent', 'history'], ['agent', 'crm'],
    ['agent', 'audit', 'records decision', 'control'], ['crm', 'agent', 'returns result', 'feedback'],
  ], [['Runtime', ['user', 'api', 'agent']], ['Data', ['history']], ['Operations', ['audit']], ['External', ['crm']]]),
  architecture('RAG with optional retrieval', [
    ['reader', 'Reader app', 'client'], ['api', 'Answer API', 'gateway'],
    ['retriever', 'Knowledge retriever', 'service'], ['model', 'Answer model', 'service'],
    ['vectors', 'Vector index', 'datastore'], ['provider', 'Model provider', 'external'],
  ], [
    ['reader', 'api'], ['api', 'retriever'], ['retriever', 'vectors'],
    ['retriever', 'model'], ['model', 'provider'], ['model', 'api', 'draft answer', 'feedback'],
  ], [['Runtime', ['reader', 'api', 'retriever', 'model']], ['Data', ['vectors']], ['External', ['provider']]]),
  architecture('Marketing approval workflow', [
    ['marketer', 'Campaign console', 'client'], ['planner', 'Campaign planner', 'service'],
    ['policy', 'Consent approval', 'decision'], ['warehouse', 'Campaign warehouse', 'datastore'],
    ['telemetry', 'Campaign Metrics', 'control', 'bottom'], ['channel', 'Ad channel API', 'external'],
  ], [
    ['marketer', 'planner'], ['planner', 'policy'], ['policy', 'channel'],
    ['planner', 'warehouse'], ['channel', 'telemetry', 'delivery event', 'feedback'],
  ], [['Runtime', ['marketer', 'planner', 'policy']], ['Data', ['warehouse']], ['Operations', ['telemetry']], ['External', ['channel']]]),
  architecture('Trading with two clients', [
    ['terminal', 'Trader terminal', 'client'], ['mobile', 'Mobile dashboard', 'client'],
    ['router', 'Order router', 'gateway'], ['risk', 'Risk engine', 'service'],
    ['ledger', 'Portfolio ledger', 'datastore'], ['logs', 'Order Logs', 'datastore', 'bottom'],
    ['broker', 'Broker exchange', 'external'],
  ], [
    ['terminal', 'router'], ['mobile', 'router'], ['router', 'risk'],
    ['risk', 'ledger'], ['risk', 'broker'], ['broker', 'risk', 'execution receipt', 'feedback'],
    ['risk', 'logs', 'audit order', 'control'],
  ], [['Runtime', ['terminal', 'mobile', 'router', 'risk']], ['Data', ['ledger']], ['Operations', ['logs']], ['External', ['broker']]]),
  architecture('Private document summarizer', [
    ['writer', 'Document upload UI', 'client'], ['ingest', 'Ingestion queue', 'queue'],
    ['summarizer', 'Summary worker', 'service'], ['documents', 'Document store', 'datastore'],
  ], [
    ['writer', 'ingest'], ['ingest', 'summarizer'], ['summarizer', 'documents'],
  ], [['Runtime', ['writer', 'ingest', 'summarizer']], ['Data', ['documents']]]),
  architecture('Agent with guarded tools', [
    ['operator', 'Operator console', 'client'], ['orchestrator', 'Agent coordinator', 'service'],
    ['guard', 'Tool permission gate', 'control'], ['memory', 'Task memory', 'datastore'],
    ['tool', 'Calendar API', 'external'], ['trace', 'Trace Logs', 'service', 'bottom'],
  ], [
    ['operator', 'orchestrator'], ['orchestrator', 'guard'], ['guard', 'tool'],
    ['orchestrator', 'memory'], ['orchestrator', 'trace', 'trace call', 'control'],
  ], [['Runtime', ['operator', 'orchestrator', 'guard']], ['Data', ['memory']], ['External', ['tool']], ['Operations', ['trace']]]),
  architecture('Event driven delivery', [
    ['producer', 'Publisher app', 'client'], ['intake', 'Event intake', 'gateway'],
    ['private_link', 'Private network link', 'network'], ['bus', 'Event bus', 'queue'],
    ['consumer', 'Delivery worker', 'service'],
    ['receipts', 'Receipt store', 'datastore'], ['metrics', 'Delivery Metrics', 'service', 'bottom'],
    ['webhook', 'Partner webhook', 'external'],
  ], [
    ['producer', 'intake'], ['intake', 'private_link'], ['private_link', 'bus'], ['bus', 'consumer'],
    ['consumer', 'receipts'], ['consumer', 'webhook'], ['consumer', 'metrics', 'records attempt', 'control'],
  ], [['Runtime', ['producer', 'intake', 'private_link', 'bus', 'consumer']], ['Data', ['receipts']], ['Operations', ['metrics']], ['External', ['webhook']]]),
  architecture('RAG disabled for a short answer', [
    ['reader', 'Reader app', 'client'], ['api', 'Answer API', 'gateway'],
    ['model', 'Answer model', 'service'], ['cache', 'Response cache', 'datastore'],
  ], [
    ['reader', 'api'], ['api', 'model'], ['model', 'cache'],
  ], [['Runtime', ['reader', 'api', 'model']], ['Data', ['cache']]]),
];

const getBBox = Object.getOwnPropertyDescriptor(SVGGraphicsElement.prototype, 'getBBox');
const elementGetBBox = Object.getOwnPropertyDescriptor(SVGElement.prototype, 'getBBox');
const svgWidth = Object.getOwnPropertyDescriptor(SVGSVGElement.prototype, 'width');
const svgHeight = Object.getOwnPropertyDescriptor(SVGSVGElement.prototype, 'height');

beforeAll(() => {
  Object.defineProperty(SVGGraphicsElement.prototype, 'getBBox', {
    configurable: true, value: () => ({ x: 0, y: 0, width: 48, height: 12 }),
  });
  Object.defineProperty(SVGElement.prototype, 'getBBox', {
    configurable: true, value: () => ({ x: 0, y: 0, width: 48, height: 12 }),
  });
  Object.defineProperty(SVGSVGElement.prototype, 'width', {
    configurable: true, get: () => ({ baseVal: { value: 760 } }),
  });
  Object.defineProperty(SVGSVGElement.prototype, 'height', {
    configurable: true, get: () => ({ baseVal: { value: 500 } }),
  });
});

afterAll(() => {
  if (getBBox) Object.defineProperty(SVGGraphicsElement.prototype, 'getBBox', getBBox);
  else delete (SVGGraphicsElement.prototype as unknown as { getBBox?: unknown }).getBBox;
  if (elementGetBBox) Object.defineProperty(SVGElement.prototype, 'getBBox', elementGetBBox);
  else delete (SVGElement.prototype as unknown as { getBBox?: unknown }).getBBox;
  if (svgWidth) Object.defineProperty(SVGSVGElement.prototype, 'width', svgWidth);
  else delete (SVGSVGElement.prototype as unknown as { width?: unknown }).width;
  if (svgHeight) Object.defineProperty(SVGSVGElement.prototype, 'height', svgHeight);
  else delete (SVGSVGElement.prototype as unknown as { height?: unknown }).height;
});

function position(container: HTMLElement, id: string): { x: number; y: number } {
  const transform = container.querySelector(`[data-node-id="${id}"]`)?.getAttribute('transform');
  const match = transform?.match(/^translate\(([^,]+),\s*([^)]+)\)$/);
  if (!match) throw new Error(`Missing position for ${id}: ${transform}`);
  return { x: Number(match[1]), y: Number(match[2]) };
}

describe('presentation across generated prompt shapes', () => {
  it.each(cases.map(graph => [graph.title, graph] as const))('keeps every node and directed edge in %s', (_title, graph) => {
    const projected = architectureRegions(graph.nodes, graph.groups ?? []);
    expect(new Set(projected.flatMap(group => group.nodeIds)))
      .toEqual(new Set(graph.nodes.map(node => node.id)));

    const connections = diagramConnections(graph.edges);
    expect(new Set(connections.flatMap(connection => connection.members)))
      .toEqual(new Set(graph.edges));

    const { container } = render(createElement(D3Graph, { graphData: graph, currentStep: -1,
      activeNodeIds: new Set<string>(), onNodeClick: () => undefined, navigation: true }));
    const renderedNodes = Array.from(container.querySelectorAll('g.node'), node => node.getAttribute('data-node-id'));
    expect(renderedNodes).toHaveLength(graph.nodes.length);
    expect(new Set(renderedNodes))
      .toEqual(new Set(graph.nodes.map(node => node.id)));
    expect(container.querySelectorAll('.edge-vis')).toHaveLength(connections.length);

    const clients = graph.nodes.filter(node => node.type === 'client');
    const services = graph.nodes.filter(node => node.type !== 'client'
      && node.type !== 'datastore' && node.type !== 'external' && node.lane !== 'bottom');
    const data = graph.nodes.filter(node => node.type === 'datastore' && node.lane !== 'bottom');
    if (clients.length && services.length) {
      expect(Math.max(...clients.map(node => position(container, node.id).x)))
        .toBeLessThan(Math.min(...services.map(node => position(container, node.id).x)));
    }
    if (services.length && data.length) {
      expect(Math.max(...services.map(node => position(container, node.id).x)))
        .toBeLessThan(Math.min(...data.map(node => position(container, node.id).x)));
    }
    const external = graph.nodes.filter(node => node.type === 'external');
    if (external.length) {
      expect(Math.min(...external.map(node => position(container, node.id).x)))
        .toBeGreaterThan(Math.min(...services.map(node => position(container, node.id).x)));
      expect(Math.max(...external.map(node => position(container, node.id).y)))
        .toBeLessThan(Math.min(...services.map(node => position(container, node.id).y)));
    }
    const bottom = graph.nodes.filter(node => node.lane === 'bottom');
    if (bottom.length) {
      expect(Math.min(...bottom.map(node => position(container, node.id).y)))
        .toBeGreaterThan(Math.max(...graph.nodes.filter(node => node.lane !== 'bottom')
          .filter(node => node.type !== 'external').map(node => position(container, node.id).y)));
    }
  });

  it('renders a concept map without architecture groups or external systems', () => {
    const concept: GraphData = {
      graph_type: 'concept', title: 'Queue ordering tradeoffs', version: 'same-generation-version',
      nodes: [
        ['ordering', 'Message ordering', 'decision'],
        ['partition', 'Partition key', 'control'],
        ['consumer', 'Consumer state', 'datastore'],
      ].map(([id, label, type]) => ({
        id, label, type: type as NodeType, technology: 'Concept', description: label, detail: null,
      })),
      edges: [
        { source: 'ordering', target: 'partition', label: 'constrains', technology: 'Concept', sync: 'sync', description: 'Consequence' },
        { source: 'partition', target: 'consumer', label: 'shapes', technology: 'Concept', sync: 'sync', description: 'Consequence' },
      ], sequence: [],
    };
    const { container } = render(createElement(D3Graph, { graphData: concept, currentStep: -1,
      activeNodeIds: new Set<string>(), onNodeClick: () => undefined, navigation: true }));
    expect(container.querySelectorAll('g.node')).toHaveLength(concept.nodes.length);
    expect(container.querySelectorAll('.edge-vis')).toHaveLength(concept.edges.length);
    expect(container.querySelectorAll('.group-box')).toHaveLength(0);
  });

  it('retains a two-way connection identity when a later generation revises its meaning', () => {
    const first = cases[0];
    const revised: GraphData = {
      ...first,
      edges: first.edges.map(edge => edge.source === 'crm' && edge.target === 'agent'
        ? { ...edge, label: 'returns approved account result', description: 'Approved account result.' }
        : edge),
    };
    const pair = (graph: GraphData) => diagramConnections(graph.edges).find(connection =>
      connection.members.some(edge => edge.source === 'crm' && edge.target === 'agent'))!;
    expect(pair(first).id).toBe(pair(revised).id);
    expect(pair(revised).members).toHaveLength(2);
    expect(pair(revised).bidirectional).toBe(true);
    expect(graphStructureKey(first)).not.toBe(graphStructureKey(revised));

    const props = { currentStep: -1, activeNodeIds: new Set<string>(),
      onNodeClick: () => undefined, navigation: true };
    const view = render(createElement(D3Graph, { ...props, graphData: first }));
    fireEvent.click(screen.getByRole('button', { name: 'Connections' }));
    const index = diagramConnections(first.edges).findIndex(connection => connection.id === pair(first).id);
    fireEvent.click(view.container.querySelectorAll('.edge-hit')[index]);
    expect(screen.getByRole('region', { name: 'Connection details' }).textContent)
      .toContain('returns result');

    view.rerender(createElement(D3Graph, { ...props, graphData: revised }));
    const details = screen.getByRole('region', { name: 'Connection details' }).textContent;
    expect(details).toContain('returns approved account result');
    expect(details).not.toContain('returns result');
  });

  it('uses changed content with the same server version and retains saved positions through expansion', () => {
    const first = cases[4];
    const expanded: GraphData = {
      ...first,
      nodes: [...first.nodes, {
        id: 'review', label: 'Summary review', type: 'service', technology: 'Human review',
        description: 'Checks high-impact summaries.', detail: null, design_origin: 'applied', lane: 'main',
      }],
      edges: [...first.edges, {
        source: 'summarizer', target: 'review', label: 'requests approval',
        technology: 'Typed payload', sync: 'sync', description: 'requests approval', flow: 'control',
      }],
      groups: first.groups?.map(group => group.id === 'zone_0'
        ? { ...group, nodeIds: [...group.nodeIds, 'review'] } : group),
    };
    const saved: GraphViewState = {
      layoutVersion: GRAPH_LAYOUT_VERSION,
      nodePositions: { writer: { x: 220, y: 250 }, summarizer: { x: 580, y: 250 } },
      viewport: { x: 0, y: 0, k: 1 },
    };
    expect(graphStructureKey(expanded)).not.toBe(graphStructureKey(first));
    const onViewStateChange = vi.fn();
    const props = { currentStep: -1, activeNodeIds: new Set<string>(),
      onNodeClick: () => undefined, onViewStateChange, navigation: true };
    const view = render(createElement(D3Graph, { ...props, graphData: first, initialViewState: saved }));
    expect(position(view.container, 'writer')).toEqual(saved.nodePositions.writer);
    expect(position(view.container, 'summarizer')).toEqual(saved.nodePositions.summarizer);

    view.rerender(createElement(D3Graph, { ...props, graphData: expanded, initialViewState: saved }));
    expect(position(view.container, 'writer')).toEqual(saved.nodePositions.writer);
    expect(position(view.container, 'summarizer')).toEqual(saved.nodePositions.summarizer);
    expect(view.container.querySelectorAll('g.node')).toHaveLength(expanded.nodes.length);
    expect(view.container.querySelectorAll('.edge-vis')).toHaveLength(diagramConnections(expanded.edges).length);
    expect(onViewStateChange.mock.lastCall?.[0].nodePositions.review).toBeDefined();
  });
});
