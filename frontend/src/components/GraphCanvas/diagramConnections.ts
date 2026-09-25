import type { GraphEdge } from '../../types';

export interface DiagramConnection {
  id: string;
  edge: GraphEdge;
  members: GraphEdge[];
  bidirectional: boolean;
}

const flowPriority = (edge: GraphEdge) =>
  ({ runtime: 0, control: 1, deployment: 2, feedback: 3 })[edge.flow ?? (edge.type === 'loop' ? 'feedback' : 'runtime')];

// This projection is presentation-only. Every directed record stays available
// for details, walkthroughs, persistence, and later graph expansion.
export function diagramConnections(edges: GraphEdge[]): DiagramConnection[] {
  const pairs = new Map<string, GraphEdge[]>();
  for (const edge of edges) {
    const id = JSON.stringify([edge.source, edge.target].sort());
    const members = pairs.get(id) ?? [];
    members.push(edge);
    pairs.set(id, members);
  }
  return Array.from(pairs, ([id, members]) => {
    const sorted = [...members].sort((a, b) => flowPriority(a) - flowPriority(b)
      || a.source.localeCompare(b.source) || a.target.localeCompare(b.target)
      || a.label.localeCompare(b.label));
    const edge = sorted[0];
    return { id, edge, members: sorted, bidirectional: edge.source !== edge.target
      && sorted.some(member => member.source === edge.target && member.target === edge.source) };
  }).sort((a, b) => a.id.localeCompare(b.id));
}

export interface ConnectionPoint { id: string; x: number; y: number }

// Keep a connected overview using real relationships. Extra cycles and return
// paths remain available on focus or through the Connections toggle.
export function overviewConnections(connections: DiagramConnection[], nodes: ConnectionPoint[]): Set<string> {
  const byId = new Map(nodes.map(node => [node.id, node]));
  const roots = new Map(nodes.map(node => [node.id, node.id]));
  const root = (id: string): string => {
    let current = id;
    while (roots.get(current) !== current && roots.has(current)) current = roots.get(current)!;
    return current;
  };
  const distance = ({ edge }: DiagramConnection) => {
    const a = byId.get(edge.source)!;
    const b = byId.get(edge.target)!;
    return Math.abs(a.x - b.x) + Math.abs(a.y - b.y);
  };
  const ordered = connections.filter(({ edge }) => byId.has(edge.source) && byId.has(edge.target))
    .sort((a, b) => flowPriority(a.edge) - flowPriority(b.edge) || distance(a) - distance(b) || a.id.localeCompare(b.id));
  const selected = new Set<string>();
  for (const connection of ordered) {
    const a = root(connection.edge.source);
    const b = root(connection.edge.target);
    if (a === b) continue;
    roots.set(a, b);
    selected.add(connection.id);
  }
  return selected;
}

interface Point { x: number; y: number }

// Try short orthogonal corridors beside cards before taking an outer detour.
// The same router handles requests and returns, so replies do not get a
// second, diagram-wide route. Overlapping user-placed cards use the route
// with the fewest intersections until the cards are moved apart.
export function routeConnection(source: ConnectionPoint, target: ConnectionPoint,
  nodes: ConnectionPoint[], width: number, height: number): { path: string; anchorX: number; anchorY: number } {
  const intersects = (a: Point, b: Point, node: Point) => a.x === b.x
    ? a.x > node.x - width / 2 && a.x < node.x + width / 2
      && Math.max(a.y, b.y) > node.y - height / 2 && Math.min(a.y, b.y) < node.y + height / 2
    : a.y > node.y - height / 2 && a.y < node.y + height / 2
      && Math.max(a.x, b.x) > node.x - width / 2 && Math.min(a.x, b.x) < node.x + width / 2;
  const horizontal = source.y === target.y && Math.abs(source.x - target.x) > width;
  const vertical = source.x === target.x && Math.abs(source.y - target.y) > height;
  if (horizontal || vertical) {
    const dx = horizontal ? Math.sign(target.x - source.x) * width / 2 : 0;
    const dy = vertical ? Math.sign(target.y - source.y) * height / 2 : 0;
    const start = { x: source.x + dx, y: source.y + dy };
    const end = { x: target.x - dx, y: target.y - dy };
    if (!nodes.some(node => intersects(start, end, node))) return {
      path: `M${start.x},${start.y} L${end.x},${end.y}`,
      anchorX: (start.x + end.x) / 2, anchorY: (start.y + end.y) / 2,
    };
  }
  const ports = (node: Point) => [
    [{ x: node.x + width / 2, y: node.y }, { x: node.x + width / 2 + 16, y: node.y }],
    [{ x: node.x - width / 2, y: node.y }, { x: node.x - width / 2 - 16, y: node.y }],
    [{ x: node.x, y: node.y + height / 2 }, { x: node.x, y: node.y + height / 2 + 16 }],
    [{ x: node.x, y: node.y - height / 2 }, { x: node.x, y: node.y - height / 2 - 16 }],
  ];
  const xs = [...new Set(nodes.flatMap(node => [node.x - width / 2 - 20, node.x + width / 2 + 20]))];
  const ys = [...new Set(nodes.flatMap(node => [node.y - height / 2 - 20, node.y + height / 2 + 20]))];
  const candidates: Point[][] = [];
  for (const [start, a] of ports(source)) {
    for (const [end, b] of ports(target)) {
      if (source.id === target.id && start.x === end.x && start.y === end.y) continue;
      candidates.push([start, a, { x: b.x, y: a.y }, b, end], [start, a, { x: a.x, y: b.y }, b, end]);
      for (const x of xs) candidates.push([start, a, { x, y: a.y }, { x, y: b.y }, b, end]);
      for (const y of ys) candidates.push([start, a, { x: a.x, y }, { x: b.x, y }, b, end]);
    }
  }
  let best = candidates[0];
  let bestScore = Infinity;
  for (const candidate of candidates) {
    let score = 0;
    for (let i = 1; i < candidate.length; i++) {
      const a = candidate[i - 1], b = candidate[i];
      if (a.x === b.x && a.y === b.y) continue;
      score += Math.abs(a.x - b.x) + Math.abs(a.y - b.y) + 12;
      for (const node of nodes) {
        if (intersects(a, b, node)) score += 1_000_000;
        if (score >= bestScore) break;
      }
      if (score >= bestScore) break;
    }
    if (score < bestScore) { best = candidate; bestScore = score; }
  }
  const points = best.filter((point, index) => index === 0 || point.x !== best[index - 1].x || point.y !== best[index - 1].y);
  let anchor = source;
  let longest = 0;
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1], b = points[i];
    const length = Math.abs(a.x - b.x) + Math.abs(a.y - b.y);
    if (length > longest) { longest = length; anchor = { id: '', x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }; }
  }
  return { path: points.map((point, i) => `${i ? 'L' : 'M'}${point.x},${point.y}`).join(' '), anchorX: anchor.x, anchorY: anchor.y };
}
