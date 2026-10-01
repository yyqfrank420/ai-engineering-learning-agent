import { describe, expect, it } from 'vitest';
import type { GraphEdge } from '../../types';
import { diagramConnections, overviewConnections, routeConnection, type ConnectionZone } from './diagramConnections';

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

const routePoints = (path: string) => [...path.matchAll(/[ML](-?[\d.]+),(-?[\d.]+)/g)]
  .map(match => ({ x: Number(match[1]), y: Number(match[2]) }));
const crossesBox = (a: { x: number; y: number }, b: { x: number; y: number }, box: { x: number; y: number; width: number; height: number }) =>
  a.x === b.x ? a.x > box.x && a.x < box.x + box.width && Math.max(a.y, b.y) > box.y && Math.min(a.y, b.y) < box.y + box.height
    : a.y > box.y && a.y < box.y + box.height && Math.max(a.x, b.x) > box.x && Math.min(a.x, b.x) < box.x + box.width;
const zone = (id: string, nodeIds: string[], x: number, y: number, width: number, height: number): ConnectionZone =>
  ({ id, nodeIds, x, y, width, height });
const assertClearCards = (path: string, nodes: Array<{ id: string; x: number; y: number }>, width = 40, height = 30) => {
  const points = routePoints(path);
  for (let i = 1; i < points.length; i++) {
    expect(points[i].x === points[i - 1].x || points[i].y === points[i - 1].y).toBe(true);
    for (const node of nodes) expect(crossesBox(points[i - 1], points[i], { x: node.x - width / 2, y: node.y - height / 2, width, height })).toBe(false);
  }
};
const assertEndpointAccess = (path: string, zones: ConnectionZone[], sourceOwner?: string, targetOwner?: string) => {
  const points = routePoints(path);
  const membership: string[] = [];
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1], b = points[i];
    const parameters = [0, 1];
    for (const frame of zones) {
      if (a.x !== b.x) parameters.push((frame.x - a.x) / (b.x - a.x), (frame.x + frame.width - a.x) / (b.x - a.x));
      if (a.y !== b.y) parameters.push((frame.y - a.y) / (b.y - a.y), (frame.y + frame.height - a.y) / (b.y - a.y));
      expect(crossesBox(a, b, { ...frame, height: 34 })).toBe(false);
    }
    const sorted = [...new Set(parameters.filter(value => value >= 0 && value <= 1))].sort((x, y) => x - y);
    for (let j = 1; j < sorted.length; j++) {
      const t = (sorted[j - 1] + sorted[j]) / 2;
      const x = a.x + (b.x - a.x) * t, y = a.y + (b.y - a.y) * t;
      const inside = zones.filter(frame => x > frame.x && x < frame.x + frame.width && y > frame.y && y < frame.y + frame.height);
      expect(inside.length).toBeLessThanOrEqual(1);
      const id = inside[0]?.id ?? 'outside';
      expect([sourceOwner, targetOwner, 'outside']).toContain(id);
      if (membership.at(-1) !== id) membership.push(id);
    }
  }
  expect(membership).toEqual([...(sourceOwner ? [sourceOwner] : []), 'outside', ...(targetOwner ? [targetOwner] : [])]);
};

describe('zone-constrained orthogonal routes', () => {
  const source = { id: 'source', x: 80, y: 100 };
  const target = { id: 'target', x: 300, y: 100 };

  it('preserves exact legacy routes without zone input', () => {
    const a = { id: 'a', x: 100, y: 100 }, b = { id: 'b', x: 500, y: 100 };
    expect(routeConnection(a, b, [a, b], 100, 60)).toEqual({ path: 'M150,100 L450,100', anchorX: 300, anchorY: 100 });
    const nodes = [a, b, { id: 'middle', x: 300, y: 100 }];
    expect(routeConnection(a, b, nodes, 100, 60)).toEqual({ path: 'M150,100 L166,100 L166,50 L434,50 L434,100 L450,100', anchorX: 300, anchorY: 50 });
    expect(routeConnection(a, b, nodes, 100, 60, [])).toEqual(routeConnection(a, b, nodes, 100, 60));
  });

  it('keeps shared-zone routes below the heading and inside the inset around cards', () => {
    const nodes = [source, target, { id: 'obstacle', x: 180, y: 100 }];
    const frame = zone('shared', nodes.map(node => node.id), 20, 40, 340, 150);
    const route = routeConnection(source, target, nodes, 40, 30, [frame]);
    expect(route.zoneRoutingBlocked).toBeUndefined();
    assertClearCards(route.path, nodes);
    expect(routePoints(route.path).every(point => point.x >= 24 && point.x <= 356 && point.y >= 78 && point.y <= 186)).toBe(true);
    expect(routePoints(route.path).some(point => point.y !== 100)).toBe(true);
  });

  it('crosses endpoint zones only in a contiguous access prefix and suffix', () => {
    const zones = [zone('left', ['source'], 20, 40, 130, 140), zone('right', ['target'], 250, 40, 130, 140)];
    for (const [a, b] of [[source, target], [target, source]]) {
      const route = routeConnection(a, b, [source, target], 40, 30, zones);
      expect(route.zoneRoutingBlocked).toBeUndefined();
      assertClearCards(route.path, [source, target]);
      assertEndpointAccess(route.path, zones, a === source ? 'left' : 'right', a === source ? 'right' : 'left');
    }
  });

  it('avoids the empty interior of an unrelated zone', () => {
    const zones = [zone('left', ['source'], 20, 40, 130, 140), zone('middle', [], 170, 20, 60, 170), zone('right', ['target'], 250, 40, 130, 140)];
    const route = routeConnection(source, target, [source, target], 40, 30, zones);
    expect(route.zoneRoutingBlocked).toBeUndefined();
    assertEndpointAccess(route.path, zones, 'left', 'right');
  });

  it('prefers a nearby source exit over a long traversal across its interior', () => {
    const a = { id: 'a', x: 80, y: 100 }, b = { id: 'b', x: 680, y: 100 };
    const zones = [zone('wide', ['a'], 20, 40, 480, 140), zone('target', ['b'], 620, 40, 130, 140)];
    const route = routeConnection(a, b, [a, b], 40, 30, zones);
    expect(route.zoneRoutingBlocked).toBeUndefined();
    assertEndpointAccess(route.path, zones, 'wide', 'target');
    const firstOutside = routePoints(route.path).find(point => point.x <= zones[0].x || point.x >= zones[0].x + zones[0].width
      || point.y <= zones[0].y || point.y >= zones[0].y + zones[0].height)!;
    expect(Math.abs(firstOutside.x - a.x) + Math.abs(firstOutside.y - a.y)).toBeLessThan(100);
  });

  it('searches a feasible maze with more turns than a single corridor', () => {
    const a = { id: 'a', x: 60, y: 100 }, b = { id: 'b', x: 420, y: 100 };
    const nodes = [a, b, { id: 'wall1', x: 160, y: 130 }, { id: 'wall2', x: 280, y: 90 }];
    const zones = [zone('shared', ['a', 'b'], 20, 40, 440, 180),
      zone('upper-wall', [], 140, 40, 40, 115), zone('lower-wall', [], 260, 130, 40, 90)];
    const route = routeConnection(a, b, nodes, 40, 30, zones);
    // The walls overlap the owner's geometry, but an interior corridor remains between them.
    expect(route.zoneRoutingBlocked).toBeUndefined();
    assertClearCards(route.path, nodes);
    const points = routePoints(route.path);
    for (let i = 1; i < points.length; i++) {
      for (const obstacle of zones.slice(1)) expect(crossesBox(points[i - 1], points[i], obstacle)).toBe(false);
    }
    expect(points.every(point => point.x >= 24 && point.x <= 456 && point.y >= 78 && point.y <= 216)).toBe(true);
    expect(points.length).toBeGreaterThan(6);
    expect(routeConnection(a, b, nodes, 40, 30, zones)).toEqual(route);
  });

  it('keeps self-loops inside their owner and clear of cards', () => {
    const frame = zone('owner', ['source'], 20, 40, 130, 140);
    const route = routeConnection(source, source, [source], 40, 30, [frame]);
    expect(route.zoneRoutingBlocked).toBeUndefined();
    assertClearCards(route.path, [source]);
    const points = routePoints(route.path);
    expect(points[0]).not.toEqual(points.at(-1));
    expect(points.every(point => point.x >= 24 && point.x <= 146 && point.y >= 78 && point.y <= 176)).toBe(true);
  });

  it('gives ungrouped endpoints no unrelated-zone access exemption', () => {
    const zones = [zone('middle', [], 150, 40, 80, 140)];
    const route = routeConnection(source, target, [source, target], 40, 30, zones);
    expect(route.zoneRoutingBlocked).toBeUndefined();
    assertEndpointAccess(route.path, zones);
    const blocked = routeConnection(source, target, [source, target], 40, 30, [zone('cover', [], 20, 40, 130, 140)]);
    expect(blocked.zoneRoutingBlocked).toBe(true);
    expect(blocked.path).toBeTruthy();
  });

  it('uses the first membership deterministically and reports impossible overlap', () => {
    const owned = zone('first', ['source', 'target'], 20, 40, 340, 150);
    const duplicate = zone('second', ['source'], 40, 60, 80, 80);
    expect(routeConnection(source, target, [source, target], 40, 30, [owned, duplicate]).zoneRoutingBlocked).toBe(true);
    const farMembership = zone('far', ['source'], 600, 40, 120, 140);
    const preferred = routeConnection(source, target, [source, target], 40, 30, [owned, farMembership]);
    expect(preferred.zoneRoutingBlocked).toBeUndefined();
    const route = routeConnection(source, target, [source, target], 40, 30, [farMembership, owned]);
    expect(route.zoneRoutingBlocked).toBe(true);
    expect(route.path).toBeTruthy();
  });

  it('allows a narrow manual gap using shorter outward leads in the search', () => {
    const a = { id: 'a', x: 70, y: 100 }, b = { id: 'b', x: 250, y: 100 };
    const nodes = [a, b, { id: 'near', x: 116, y: 100 }, { id: 'above', x: 70, y: 60 }, { id: 'below', x: 70, y: 140 }];
    const frame = zone('owner', ['a', 'b'], 20, 20, 280, 170);
    const route = routeConnection(a, b, nodes, 40, 30, [frame]);
    expect(route.zoneRoutingBlocked).toBeUndefined();
    assertClearCards(route.path, nodes);
  });
});

it.each([0, 54])('routes through positive manual gaps with %s distant zones', distantCount => {
  const a = { id: 'a', x: 0, y: 0 }, b = { id: 'b', x: 150, y: 0 };
  const nodes = [a, b, { id: 'right', x: 42, y: 0 }, { id: 'left', x: -42, y: 0 },
    { id: 'above', x: 0, y: -32 }, { id: 'below', x: 0, y: 32 }];
  const zones = [zone('source', ['a', 'right', 'left', 'above', 'below'], -86, -89, 172, 156),
    zone('target', ['b'], 106, -57, 88, 92)];
  for (let i = 0; i < distantCount; i++) {
    const node = { id: `far${i}`, x: 1000 + i * 100.13, y: 1000 + i * 100.17 };
    nodes.push(node);
    zones.push(zone(node.id, [node.id], node.x - 44, node.y - 57, 88, 92));
  }
  const route = routeConnection(a, b, nodes, 40, 30, zones);
  expect(route.zoneRoutingBlocked).toBeUndefined();
  assertClearCards(route.path, nodes);
  assertEndpointAccess(route.path, zones, 'source', 'target');
});

it.each([0, 15])('keeps overlapping aligned relationships nonzero at separation %s', separation => {
  const a = { id: 'a', x: 100, y: 100 }, b = { id: 'b', x: 100 + separation, y: 100 };
  const route = routeConnection(a, b, [a, b], 40, 30, [zone('shared', ['a', 'b'], 20, 40, 180, 160)]);
  const points = routePoints(route.path);
  expect(points.length).toBeGreaterThan(1);
  expect(points.slice(1).some((point, index) => point.x !== points[index].x || point.y !== points[index].y)).toBe(true);
});

it('routes every connection in a jittered 60-zone diagram', () => {
  const nodes = Array.from({ length: 60 }, (_, i) => ({ id: String(i),
    x: i % 10 * 350 + Math.floor(i / 10) * 0.13, y: Math.floor(i / 10) * 150 + i % 10 * 0.17 }));
  const zones = nodes.map(node => zone(node.id, [node.id], node.x - 117, node.y - 76, 234, 130));
  for (let i = 1; i < nodes.length; i++) {
    const route = routeConnection(nodes[i - 1], nodes[i], nodes, 186, 68, zones);
    expect(route.zoneRoutingBlocked).toBeUndefined();
    assertEndpointAccess(route.path, zones, nodes[i - 1].id, nodes[i].id);
  }
});

it('uses exact boundary channels between zones less than eight pixels apart', () => {
  const a = { id: 'a', x: 60, y: 100 }, b = { id: 'b', x: 350, y: 180 };
  const zones = [zone('owner', ['a', 'b'], 20, 40, 400, 180),
    zone('upper', [], 140, 40, 60, 110), zone('lower', [], 202, 100, 58, 120)];
  const route = routeConnection(a, b, [a, b], 40, 30, zones);
  expect(route.zoneRoutingBlocked).toBeUndefined();
  assertClearCards(route.path, [a, b]);
  const points = routePoints(route.path);
  expect(points.every(point => point.x >= 24 && point.x <= 416 && point.y >= 78 && point.y <= 216)).toBe(true);
  for (let i = 1; i < points.length; i++) {
    for (const obstacle of zones.slice(1)) expect(crossesBox(points[i - 1], points[i], obstacle)).toBe(false);
  }
});
