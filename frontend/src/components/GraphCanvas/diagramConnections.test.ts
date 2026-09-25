import { describe, expect, it } from 'vitest';
import type { GraphEdge } from '../../types';
import { diagramConnections, overviewConnections, routeConnection } from './diagramConnections';

const edge = (source: string, target: string, label = 'Request', flow: GraphEdge['flow'] = 'runtime'): GraphEdge =>
  ({ source, target, label, flow, technology: 'HTTPS', sync: 'sync', description: label });

describe('diagram connection projection', () => {
  it('bundles both directions and parallel exchanges without losing records or mutating input', () => {
    const input = [edge('a', 'b'), edge('b', 'a', 'Reply'), edge('a', 'b', 'Retry'), edge('b', 'c')];
    const before = structuredClone(input);
    const projected = diagramConnections(input);
    expect(projected).toHaveLength(2);
    expect(projected.flatMap(connection => connection.members)).toHaveLength(input.length);
    expect(projected[0].bidirectional).toBe(true);
    expect(projected[1].bidirectional).toBe(false);
    expect(input).toEqual(before);
    expect(diagramConnections([...input].reverse())).toEqual(projected);
  });

  it('prefers runtime over feedback and handles empty graphs, self-loops, and IDs with delimiters', () => {
    expect(diagramConnections([])).toEqual([]);
    const projected = diagramConnections([edge('b', 'a', 'Feedback', 'feedback'), edge('a', 'b'), edge('a', 'a'),
      edge('a:b', 'c'), edge('a', 'b:c')]);
    expect(projected).toHaveLength(4);
    expect(projected.find(c => c.bidirectional)?.edge.flow).toBe('runtime');
    expect(projected.find(c => c.edge.source === c.edge.target)?.bidirectional).toBe(false);
  });

  it('keeps each connected component connected in overview without extra cycles', () => {
    const connections = diagramConnections([edge('a', 'b'), edge('b', 'c'), edge('c', 'a', 'Return', 'feedback'),
      edge('c', 'd', 'Audit', 'control'), edge('e', 'f'), edge('a', 'missing')]);
    const nodes = ['a', 'b', 'c', 'd', 'e', 'f'].map((id, i) => ({ id, x: i * 200, y: 100 }));
    const ids = overviewConnections(connections, nodes);
    expect(ids.size).toBe(4);
    expect(connections.filter(c => ids.has(c.id)).map(c => [c.edge.source, c.edge.target])).toEqual([
      ['a', 'b'], ['b', 'c'], ['c', 'd'], ['e', 'f'],
    ]);
  });
});

describe('local orthogonal routes', () => {
  const source = { id: 'a', x: 100, y: 100 };
  const target = { id: 'b', x: 500, y: 100 };
  const points = (path: string) => [...path.matchAll(/[ML](-?[\d.]+),(-?[\d.]+)/g)]
    .map(match => ({ x: Number(match[1]), y: Number(match[2]) }));

  it('takes the direct corridor for request and response', () => {
    for (const [a, b] of [[source, target], [target, source]]) {
      const route = points(routeConnection(a, b, [source, target], 100, 60).path);
      expect(route.every(point => point.y === 100)).toBe(true);
      expect(route[0].x).toBe(a.x < b.x ? 150 : 450);
      expect(route.at(-1)?.x).toBe(a.x < b.x ? 450 : 150);
    }
  });

  it('routes around cards, including a card moved into the path', () => {
    const obstacle = { id: 'obstacle', x: 300, y: 100 };
    const nodes = [source, target, obstacle];
    const path = routeConnection(source, target, nodes, 100, 60).path;
    const route = points(path);
    for (let i = 1; i < route.length; i++) {
      const a = route[i - 1], b = route[i];
      expect(a.x === b.x || a.y === b.y).toBe(true);
      for (const node of nodes) {
        const crosses = a.x === b.x
          ? a.x > node.x - 50 && a.x < node.x + 50 && Math.max(a.y, b.y) > node.y - 30 && Math.min(a.y, b.y) < node.y + 30
          : a.y > node.y - 30 && a.y < node.y + 30 && Math.max(a.x, b.x) > node.x - 50 && Math.min(a.x, b.x) < node.x + 50;
        expect(crosses).toBe(false);
      }
    }
    expect(route.some(point => point.y !== 100)).toBe(true);
    expect(routeConnection(source, target, [source, target, { ...obstacle, y: 250 }], 100, 60).path).not.toBe(path);
  });

  it('keeps a self-loop nonzero and finite', () => {
    const route = points(routeConnection(source, source, [source], 100, 60).path);
    expect(route.length).toBeGreaterThan(2);
    expect(route.every(point => Number.isFinite(point.x) && Number.isFinite(point.y))).toBe(true);
    expect(route[0]).not.toEqual(route.at(-1));
  });
});
