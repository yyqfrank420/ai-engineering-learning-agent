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
export interface ConnectionZone {
  id: string;
  nodeIds: readonly string[];
  x: number;
  y: number;
  width: number;
  height: number;
}
interface ConnectionRoute { path: string; anchorX: number; anchorY: number; zoneRoutingBlocked?: boolean }

function connectionPorts(node: Point, width: number, height: number, lead = 16): Point[][] {
  return [
    [{ x: node.x + width / 2, y: node.y }, { x: node.x + width / 2 + lead, y: node.y }],
    [{ x: node.x - width / 2, y: node.y }, { x: node.x - width / 2 - lead, y: node.y }],
    [{ x: node.x, y: node.y + height / 2 }, { x: node.x, y: node.y + height / 2 + lead }],
    [{ x: node.x, y: node.y - height / 2 }, { x: node.x, y: node.y - height / 2 - lead }],
  ];
}

function corridorCandidates(source: ConnectionPoint, target: ConnectionPoint,
  width: number, height: number, xs: readonly number[], ys: readonly number[],
  sourcePorts = connectionPorts(source, width, height), targetPorts = connectionPorts(target, width, height)): Point[][] {
  const candidates: Point[][] = [];
  for (const [start, a] of sourcePorts) {
    for (const [end, b] of targetPorts) {
      if (source.id === target.id && start.x === end.x && start.y === end.y) continue;
      candidates.push([start, a, { x: b.x, y: a.y }, b, end], [start, a, { x: a.x, y: b.y }, b, end]);
      for (const x of xs) candidates.push([start, a, { x, y: a.y }, { x, y: b.y }, b, end]);
      for (const y of ys) candidates.push([start, a, { x: a.x, y }, { x: b.x, y }, b, end]);
    }
  }
  return candidates;
}

function serializeRoute(best: Point[], source: ConnectionPoint): ConnectionRoute {
  const points = best.filter((point, index) => index === 0 || point.x !== best[index - 1].x || point.y !== best[index - 1].y);
  let anchor: Point = source;
  let longest = 0;
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1], b = points[i];
    const length = Math.abs(a.x - b.x) + Math.abs(a.y - b.y);
    if (length > longest) { longest = length; anchor = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }; }
  }
  return { path: points.map((point, i) => `${i ? 'L' : 'M'}${point.x},${point.y}`).join(' '), anchorX: anchor.x, anchorY: anchor.y };
}

// Try short orthogonal corridors beside cards before taking an outer detour.
// The same router handles requests and returns, so replies do not get a
// second, diagram-wide route. Overlapping user-placed cards use the route
// with the fewest intersections until the cards are moved apart.
function routeUnzoned(source: ConnectionPoint, target: ConnectionPoint,
  nodes: ConnectionPoint[], width: number, height: number): ConnectionRoute {
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
  const xs = [...new Set(nodes.flatMap(node => [node.x - width / 2 - 20, node.x + width / 2 + 20]))];
  const ys = [...new Set(nodes.flatMap(node => [node.y - height / 2 - 20, node.y + height / 2 + 20]))];
  const candidates = corridorCandidates(source, target, width, height, xs, ys);
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
  return serializeRoute(best, source);
}

const ZONE_INSET = 4;
const ZONE_HEADING_HEIGHT = 34;
const ZONE_CONTENT_TOP = ZONE_HEADING_HEIGHT + ZONE_INSET;
// Discourage long endpoint-zone traversals when a nearby exterior exit is available.
const ZONE_ACCESS_LENGTH_PENALTY = 8;

function gapAwarePorts(node: ConnectionPoint, nodes: ConnectionPoint[], width: number, height: number): Point[][] {
  return connectionPorts(node, width, height).flatMap(([port, outward]) => {
    const horizontal = port.y === outward.y;
    const direction = Math.sign(horizontal ? outward.x - port.x : outward.y - port.y);
    let gap = Infinity;
    for (const other of nodes) {
      if (other.id === node.id) continue;
      const fixed = horizontal ? port.y : port.x;
      const center = horizontal ? other.y : other.x;
      const half = horizontal ? height / 2 : width / 2;
      if (fixed <= center - half || fixed >= center + half) continue;
      const near = (horizontal ? other.x : other.y) - direction * (horizontal ? width / 2 : height / 2);
      const distance = direction * (near - (horizontal ? port.x : port.y));
      if (distance >= 0) gap = Math.min(gap, distance);
    }
    if (!Number.isFinite(gap) || gap <= 0) return [];
    const lead = Math.min(16, gap / 2);
    return [[port, { x: port.x + (horizontal ? direction * lead : 0), y: port.y + (horizontal ? 0 : direction * lead) }]];
  });
}

// Interior intervals distinguish contiguous endpoint access from a later reentry.
function interiorInterval(a: Point, b: Point, box: { x: number; y: number; width: number; height: number }): [number, number] | null {
  const horizontal = a.y === b.y;
  const fixed = horizontal ? a.y : a.x;
  const lower = horizontal ? box.y : box.x;
  const upper = lower + (horizontal ? box.height : box.width);
  if (fixed <= lower || fixed >= upper) return null;
  const origin = horizontal ? a.x : a.y;
  const delta = horizontal ? b.x - a.x : b.y - a.y;
  if (delta === 0) return null;
  const first = ((horizontal ? box.x : box.y) - origin) / delta;
  const last = ((horizontal ? box.x + box.width : box.y + box.height) - origin) / delta;
  const start = Math.max(0, Math.min(first, last));
  const end = Math.min(1, Math.max(first, last));
  return end > start ? [start, end] : null;
}

export function routeConnection(source: ConnectionPoint, target: ConnectionPoint,
  nodes: ConnectionPoint[], width: number, height: number, zones: readonly ConnectionZone[] = []): ConnectionRoute {
  if (!zones.length) return routeUnzoned(source, target, nodes, width, height);
  const sourceZone = zones.find(zone => zone.nodeIds.includes(source.id));
  const targetZone = zones.find(zone => zone.nodeIds.includes(target.id));
  const shared = sourceZone && sourceZone === targetZone ? sourceZone : undefined;
  const localZones = shared ? [shared] : [sourceZone, targetZone].filter((zone): zone is ConnectionZone => Boolean(zone));
  const accessPorts = (node: ConnectionPoint, owner: ConnectionZone | undefined): Point[][] => {
    const ports = connectionPorts(node, width, height);
    if (!owner || shared) return ports;
    return ports.map(([port], index) => [port, index === 0 ? { x: owner.x + owner.width + ZONE_INSET, y: port.y }
      : index === 1 ? { x: owner.x - ZONE_INSET, y: port.y }
        : index === 2 ? { x: port.x, y: owner.y + owner.height + ZONE_INSET }
          : { x: port.x, y: owner.y - ZONE_INSET }]);
  };
  const starts = accessPorts(source, sourceZone);
  const ends = accessPorts(target, targetZone);
  const searchStarts = [...starts, ...connectionPorts(source, width, height), ...connectionPorts(source, width, height, 4), ...gapAwarePorts(source, nodes, width, height)];
  const searchEnds = [...ends, ...connectionPorts(target, width, height), ...connectionPorts(target, width, height, 4), ...gapAwarePorts(target, nodes, width, height)];
  const foreignZones = zones.filter(zone => zone !== sourceZone && zone !== targetZone);
  const routingNodes = nodes.filter(node => {
    const box = { x: node.x - width / 2, y: node.y - height / 2 };
    if (shared) return box.x < shared.x + shared.width && box.x + width > shared.x
      && box.y < shared.y + shared.height && box.y + height > shared.y;
    return !foreignZones.some(zone => box.x >= zone.x && box.x + width <= zone.x + zone.width
      && box.y >= zone.y && box.y + height <= zone.y + zone.height);
  });
  const routeBoxes = routingNodes.map(node => ({ x: node.x - width / 2, y: node.y - height / 2, width, height }));
  const xs = [...new Set([
    ...routingNodes.flatMap(node => [node.x - width / 2 - 20, node.x - width / 2, node.x + width / 2, node.x + width / 2 + 20]),
    ...zones.flatMap(zone => zone === sourceZone || zone === targetZone
      ? [zone.x - ZONE_INSET, zone.x + ZONE_INSET, zone.x + zone.width - ZONE_INSET, zone.x + zone.width + ZONE_INSET]
      : [zone.x - ZONE_INSET, zone.x, zone.x + zone.width, zone.x + zone.width + ZONE_INSET]),
    ...[...searchStarts, ...searchEnds].flat().map(point => point.x),
  ])].filter(x => !shared || x >= shared.x + ZONE_INSET && x <= shared.x + shared.width - ZONE_INSET).sort((a, b) => a - b);
  const ys = [...new Set([
    ...routingNodes.flatMap(node => [node.y - height / 2 - 20, node.y - height / 2, node.y + height / 2, node.y + height / 2 + 20]),
    ...zones.flatMap(zone => zone === sourceZone || zone === targetZone
      ? [zone.y - ZONE_INSET, zone.y + ZONE_CONTENT_TOP, zone.y + zone.height - ZONE_INSET, zone.y + zone.height + ZONE_INSET]
      : [zone.y - ZONE_INSET, zone.y, zone.y + zone.height, zone.y + zone.height + ZONE_INSET]),
    ...[...searchStarts, ...searchEnds].flat().map(point => point.y),
  ])].filter(y => !shared || y >= shared.y + ZONE_CONTENT_TOP && y <= shared.y + shared.height - ZONE_INSET).sort((a, b) => a - b);
  const initialPhase = sourceZone ? 0 : 1;
  const finalPhase = shared ? 0 : targetZone ? 2 : 1;
  const segment = (a: Point, b: Point, phase: number): { phase: number; cost: number } | null => {
    const length = Math.abs(b.x - a.x) + Math.abs(b.y - a.y);
    if (!length) return { phase, cost: 0 };
    if (a.x !== b.x && a.y !== b.y) return null;
    if (routeBoxes.some(box => interiorInterval(a, b, box))) return null;
    if (foreignZones.some(zone => interiorInterval(a, b, zone))) return null;
    if (localZones.some(zone => interiorInterval(a, b, { ...zone, height: Math.min(ZONE_HEADING_HEIGHT, zone.height) }))) return null;
    if (shared) {
      if ([a, b].some(point => point.x < shared.x + ZONE_INSET || point.x > shared.x + shared.width - ZONE_INSET
        || point.y < shared.y + ZONE_CONTENT_TOP || point.y > shared.y + shared.height - ZONE_INSET)) return null;
      return { phase: 0, cost: length };
    }
    const intervals = localZones.map(zone => ({ zone, interval: interiorInterval(a, b, zone) }));
    const breaks = [...new Set([0, 1, ...intervals.flatMap(item => item.interval ?? [])])].sort((x, y) => x - y);
    let accessLength = 0;
    for (let i = 1; i < breaks.length; i++) {
      const midpoint = (breaks[i - 1] + breaks[i]) / 2;
      const inside = intervals.filter(item => item.interval && midpoint > item.interval[0] && midpoint < item.interval[1]);
      if (inside.length > 1) return null;
      const owner = inside[0]?.zone;
      if (owner === sourceZone && owner) {
        if (phase !== 0) return null;
        accessLength += length * (breaks[i] - breaks[i - 1]);
      } else if (owner === targetZone && owner) {
        if (phase === 0) return null;
        phase = 2;
        accessLength += length * (breaks[i] - breaks[i - 1]);
      } else {
        if (phase === 2) return null;
        phase = 1;
      }
    }
    return { phase, cost: length + accessLength * ZONE_ACCESS_LENGTH_PENALTY };
  };
  const scoreRoute = (points: Point[], maximum = Infinity): number | null => {
    let phase = initialPhase;
    let score = 0;
    for (let i = 1; i < points.length; i++) {
      const result = segment(points[i - 1], points[i], phase);
      if (!result) return null;
      phase = result.phase;
      score += result.cost + (result.cost ? 12 : 0);
      if (score >= maximum) return null;
    }
    return phase === finalPhase ? score : null;
  };
  if (shared && source.id !== target.id && (source.x === target.x && Math.abs(source.y - target.y) > height
    || source.y === target.y && Math.abs(source.x - target.x) > width)) {
    const horizontal = source.y === target.y;
    const direction = Math.sign(horizontal ? target.x - source.x : target.y - source.y);
    const start = { x: source.x + (horizontal ? direction * width / 2 : 0), y: source.y + (horizontal ? 0 : direction * height / 2) };
    const end = { x: target.x - (horizontal ? direction * width / 2 : 0), y: target.y - (horizontal ? 0 : direction * height / 2) };
    if (scoreRoute([start, end]) !== null) return serializeRoute([start, end], source);
  }
  const minimumAccess = (node: ConnectionPoint, owner: ConnectionZone | undefined) => !owner || shared ? 0
    : Math.max(0, Math.min(node.x - width / 2 - owner.x, owner.x + owner.width - node.x - width / 2,
      node.y - height / 2 - owner.y, owner.y + owner.height - node.y - height / 2));
  const accessBound = (minimumAccess(source, sourceZone) + minimumAccess(target, targetZone)) * ZONE_ACCESS_LENGTH_PENALTY;
  const localXs = [...new Set([...localZones.flatMap(zone => [zone.x - ZONE_INSET, zone.x + ZONE_INSET,
    zone.x + zone.width - ZONE_INSET, zone.x + zone.width + ZONE_INSET]), ...[...starts, ...ends].flat().map(point => point.x)])];
  const localYs = [...new Set([...localZones.flatMap(zone => [zone.y - ZONE_INSET, zone.y + ZONE_CONTENT_TOP,
    zone.y + zone.height - ZONE_INSET, zone.y + zone.height + ZONE_INSET]), ...[...starts, ...ends].flat().map(point => point.y)])];
  const bestCorridor = (axesX: number[], axesY: number[]): Point[] | undefined => {
    let best: Point[] | undefined;
    let bestScore = Infinity;
    for (const candidate of corridorCandidates(source, target, width, height, axesX, axesY, starts, ends)) {
      const lowerBound = candidate.slice(1).reduce((cost, point, index) => {
        const distance = Math.abs(point.x - candidate[index].x) + Math.abs(point.y - candidate[index].y);
        return cost + distance + (distance ? 12 : 0);
      }, accessBound);
      if (lowerBound >= bestScore) continue;
      const score = scoreRoute(candidate, bestScore);
      if (score !== null && score < bestScore) { best = candidate; bestScore = score; }
    }
    return best;
  };
  // Ordinary drags use endpoint corridors; obstacle axes are reserved for blocked local routes.
  const local = bestCorridor(localXs, localYs);
  if (local) return serializeRoute(local, source);
  const broad = bestCorridor(xs, ys);
  if (broad) return serializeRoute(broad, source);

  // Search only when cheap corridors fail. Bound manual-layout work during dragging.
  const search = (xs: number[], ys: number[]): ConnectionRoute | undefined => {
    if (xs.length * ys.length > 40_000) return undefined;
    interface SearchEntry { key: string; index: number; phase: number; direction: number; cost: number; start: number; previous: string | null }
    const heap: SearchEntry[] = [];
    const push = (entry: SearchEntry) => {
      heap.push(entry);
      let index = heap.length - 1;
      while (index > 0) {
        const parent = (index - 1) >> 1;
        if (heap[parent].cost <= entry.cost) break;
        heap[index] = heap[parent]; index = parent;
      }
      heap[index] = entry;
    };
    const pop = (): SearchEntry => {
      const first = heap[0], last = heap.pop()!;
      if (heap.length) {
        let index = 0;
        while (index * 2 + 1 < heap.length) {
          let child = index * 2 + 1;
          if (child + 1 < heap.length && heap[child + 1].cost < heap[child].cost) child++;
          if (heap[child].cost >= last.cost) break;
          heap[index] = heap[child]; index = child;
        }
        heap[index] = last;
      }
      return first;
    };
    const pointAt = (index: number): Point => ({ x: xs[index % xs.length], y: ys[Math.floor(index / xs.length)] });
    const indexAt = (point: Point) => {
      const x = xs.indexOf(point.x), y = ys.indexOf(point.y);
      return x < 0 || y < 0 ? -1 : y * xs.length + x;
    };
    const entries = new Map<string, SearchEntry>();
    const offer = (index: number, phase: number, direction: number, cost: number, start: number, previous: string | null) => {
      const key = `${index}:${phase}:${direction}${source.id === target.id ? `:${start}` : ''}`;
      if ((entries.get(key)?.cost ?? Infinity) <= cost) return;
      const entry = { key, index, phase, direction, cost, start, previous };
      entries.set(key, entry); push(entry);
    };
    searchStarts.forEach(([port, outward], start) => {
      const result = segment(port, outward, initialPhase);
      if (result && indexAt(outward) >= 0) offer(indexAt(outward), result.phase, port.x === outward.x ? 1 : 0, result.cost, start, null);
    });
    let expanded = 0;
    while (heap.length && expanded++ < 160_000) {
      const current = pop();
      if (entries.get(current.key) !== current) continue;
      const point = pointAt(current.index);
      for (const [end, outward] of searchEnds) {
        if (point.x !== outward.x || point.y !== outward.y) continue;
        const start = searchStarts[current.start][0];
        if (source.id === target.id && start.x === end.x && start.y === end.y) continue;
        const terminal = segment(outward, end, current.phase);
        if (!terminal || terminal.phase !== finalPhase) continue;
        const path: Point[] = [point, end];
        let entry = current;
        while (entry.previous !== null) { entry = entries.get(entry.previous)!; path.unshift(pointAt(entry.index)); }
        path.unshift(start);
        // Remove intermediate grid coordinates, preserving turns and access transitions.
        const compact = path.filter((p, i) => !i || i === path.length - 1
          || (path[i - 1].x !== p.x || p.x !== path[i + 1].x) && (path[i - 1].y !== p.y || p.y !== path[i + 1].y));
        if (scoreRoute(compact) !== null) return serializeRoute(compact, source);
      }
      const x = current.index % xs.length, y = Math.floor(current.index / xs.length);
      const adjacent = [x > 0 ? current.index - 1 : -1, x + 1 < xs.length ? current.index + 1 : -1,
        y > 0 ? current.index - xs.length : -1, y + 1 < ys.length ? current.index + xs.length : -1];
      for (const index of adjacent) {
        if (index < 0) continue;
        const next = pointAt(index);
        const result = segment(point, next, current.phase);
        if (!result) continue;
        const direction = point.x === next.x ? 1 : 0;
        offer(index, result.phase, direction, current.cost + result.cost + (direction === current.direction ? 0 : 12), current.start, current.key);
      }
    }
    return undefined;
  };
  // Distant zones must not consume the local search budget around the endpoint frames.
  const frames = [sourceZone ?? { x: source.x - width / 2, y: source.y - height / 2, width, height },
    targetZone ?? { x: target.x - width / 2, y: target.y - height / 2, width, height }];
  const minX = Math.min(...frames.map(frame => frame.x)) - 20;
  const maxX = Math.max(...frames.map(frame => frame.x + frame.width)) + 20;
  const minY = Math.min(...frames.map(frame => frame.y)) - 20;
  const maxY = Math.max(...frames.map(frame => frame.y + frame.height)) + 20;
  const windowXs = xs.filter(x => x >= minX && x <= maxX);
  const windowYs = ys.filter(y => y >= minY && y <= maxY);
  const nearby = search(windowXs, windowYs);
  if (nearby) return nearby;
  const wider = windowXs.length === xs.length && windowYs.length === ys.length ? undefined : search(xs, ys);
  return wider ?? { ...routeUnzoned(source, target, nodes, width, height), zoneRoutingBlocked: true };
}
