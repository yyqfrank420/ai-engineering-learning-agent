import { describe, expect, it } from 'vitest';
import type { GraphEdge } from '../../types';
import {
  boundLabelCenter,
  COMPACT_LAYOUT_COLUMNS,
  COMPACT_LAYOUT_ROWS,
  filterRenderableEdges,
  initialFitScale,
  isPublishedLayoutScale,
  labelAxisCandidates,
  MAX_PUBLISHED_GRAPH_NODES,
  MIN_PUBLISHED_TITLE_PX,
  NODE_TITLE_PX,
  NODE_W,
  NODE_H,
  placeAddedNodes,
  overviewEdgeLabelOpacity,
  partitionVerticalLevels,
  planCompactLayout,
  planVerticalLayout,
  selectGraphLayout,
  selectOverviewEdgeIndices,
  VERTICAL_LEVEL_H,
  VERTICAL_PAD,
  wrapNodeLabel,
  wrapNodeTechnology,
} from './graphLayout';


describe('incremental component placement', () => {
  const parent = { id: 'runtime', x: 371.34765625, y: 156.17384338378906 };
  const planner = { id: 'planner', x: 617.34765625, y: 156.17384338378906 };
  const children = ['intake', 'loader', 'runner'].map((id, index) => ({
    id, x: 1631 + index * 210, y: 90, parent_service_id: 'runtime',
  }));
  const saved = new Set(['runtime', 'planner']);

  it('places internals near the saved parent with spacing in both dimensions', () => {
    const positions = placeAddedNodes([parent, planner, ...children], saved);
    expect(positions.get(parent.id)).toEqual({ x: parent.x, y: parent.y });
    expect(positions.get(planner.id)).toEqual({ x: planner.x, y: planner.y });
    for (const child of children) {
      const position = positions.get(child.id)!;
      expect(Math.abs(position.x - parent.x)).toBeLessThanOrEqual(NODE_W + 24);
      expect(Math.abs(position.y - parent.y)).toBeLessThanOrEqual(NODE_H + 24);
    }
    const values = [...positions.values()];
    for (let left = 0; left < values.length; left += 1) {
      for (let right = left + 1; right < values.length; right += 1) {
        expect(Math.abs(values[left].x - values[right].x) >= NODE_W + 24
          || Math.abs(values[left].y - values[right].y) >= NODE_H + 24).toBe(true);
      }
    }
  });

  it('uses stable component ordering and searches around occupied nearby slots', () => {
    const blockers = [
      { id: 'below', x: parent.x, y: parent.y + NODE_H + 24 },
      { id: 'above', x: parent.x, y: parent.y - NODE_H - 24 },
    ];
    const fixed = new Set([...saved, ...blockers.map(node => node.id)]);
    const first = placeAddedNodes([parent, planner, ...blockers, ...children], fixed);
    const reordered = placeAddedNodes([...children.slice().reverse(), parent, planner, ...blockers], fixed);
    for (const child of children) expect(reordered.get(child.id)).toEqual(first.get(child.id));
    for (const blocker of blockers) expect(first.get(blocker.id)).toEqual({ x: blocker.x, y: blocker.y });
  });

  it('places a newly added parent before its dependent child', () => {
    const positions = placeAddedNodes([parent,
      { id: 'a-child', x: 3000, y: 0, parent_service_id: 'z-parent' },
      { id: 'z-parent', x: 2000, y: 0, parent_service_id: parent.id },
    ], new Set([parent.id]));
    const owner = positions.get('z-parent')!;
    const child = positions.get('a-child')!;
    expect(Math.hypot(owner.x - parent.x, owner.y - parent.y)).toBeLessThan(250);
    expect(Math.hypot(child.x - owner.x, child.y - owner.y)).toBeLessThan(250);
    expect(child).not.toEqual(owner);
  });

  it('preserves rightward placement when blockers cover consecutive default slots', () => {
    const spacing = NODE_W + 24;
    const positions = placeAddedNodes([
      { id: 'first', x: spacing / 2, y: 100 },
      { id: 'second', x: 2.5 * spacing, y: 100 },
      { id: 'added', x: 0, y: 100 },
    ], new Set(['first', 'second']));
    expect(positions.get('added')).toEqual({ x: 4 * spacing, y: 100 });
  });

  it('bounds searches when finite coordinates cannot represent nearby offsets', () => {
    const distant = { id: 'distant', x: 1e308, y: 1e308 };
    const positions = placeAddedNodes([distant,
      { ...distant, id: 'internal', parent_service_id: 'distant' },
      { id: 'generic', x: distant.x, y: distant.y },
    ], new Set(['distant']));
    expect(positions.get('distant')).toEqual({ x: 1e308, y: 1e308 });
    expect(positions.get('internal')).toEqual({ x: (NODE_W + 24) * 2, y: 0 });
    expect(positions.get('generic')).toEqual({ x: 0, y: 0 });
  });

  it('rejects nonfinite coordinates before searching for placement', () => {
    expect(() => placeAddedNodes([{ id: 'invalid', x: Infinity, y: 0 }], new Set()))
      .toThrow('Graph node positions must be finite.');
  });

  it('retains default placement for generic additions and handles unavailable ownership', () => {
    const positions = placeAddedNodes([parent,
      { id: 'generic', x: parent.x, y: parent.y },
      { id: 'orphan', x: 1200, y: 800, parent_service_id: 'missing' },
      { id: 'cycle-a', x: 1400, y: 400, parent_service_id: 'cycle-b' },
      { id: 'cycle-b', x: 1600, y: 400, parent_service_id: 'cycle-a' },
    ], new Set([parent.id]));
    expect(positions.get('generic')).toEqual({ x: parent.x + NODE_W + 24, y: parent.y });
    expect(positions.get('orphan')).toEqual({ x: 1200, y: 800 });
    expect(positions.size).toBe(5);
  });
});

describe('graph layout policy', () => {
  it('samples a half-pixel free corridor without touching either obstacle', () => {
    const candidates = labelAxisCandidates(50, 300, 50, [
      { start: 0, end: 100 }, { start: 150.5, end: 250 },
    ]);
    const fitting = candidates.filter(center => center - 25 > 100 && center + 25 < 150.5);
    expect(fitting).toContain(125.25);
    expect(candidates.every(center => center >= 29 && center <= 271)).toBe(true);
  });

  it('includes narrow viewport gaps and rejects labels wider than the viewport', () => {
    expect(labelAxisCandidates(200, 300, 50, [{ start: 54.5, end: 300 }])).toContain(29.25);
    expect(labelAxisCandidates(200, 300, 400, [])).toEqual([]);
  });

  it('selects the first layout that meets the title-size contract', () => {
    expect(selectGraphLayout(0.75, 0.8)).toBe('horizontal');
    expect(selectGraphLayout(0.7, 0.75)).toBe('vertical');
    expect(selectGraphLayout(0.7, 0.7)).toBe('compact');
  });

  it('falls back to the rank-ordered compact grid when a 60-node vertical plan misses the title gate', () => {
    const levelSizes = Array.from({ length: 10 }, () => [1, 5]).flat();
    const verticalPlan = planVerticalLayout(1440, 960, levelSizes);
    const compactPlan = planCompactLayout(1440, 960, levelSizes.reduce((sum, size) => sum + size, 0));

    expect(levelSizes.reduce((sum, size) => sum + size, 0)).toBe(MAX_PUBLISHED_GRAPH_NODES);
    expect(NODE_TITLE_PX * verticalPlan.scale).toBeLessThan(MIN_PUBLISHED_TITLE_PX);
    expect(compactPlan.columns).toBe(COMPACT_LAYOUT_COLUMNS);
    expect(compactPlan.rows).toBe(COMPACT_LAYOUT_ROWS);
    expect(isPublishedLayoutScale(compactPlan.scale)).toBe(true);
    expect(selectGraphLayout(0.7, verticalPlan.scale)).toBe('compact');
  });

  it('proves compact capacity at the published schema boundary', () => {
    const compactPlan = planCompactLayout(1440, 960, MAX_PUBLISHED_GRAPH_NODES);

    expect(COMPACT_LAYOUT_COLUMNS * COMPACT_LAYOUT_ROWS).toBeGreaterThanOrEqual(MAX_PUBLISHED_GRAPH_NODES);
    expect(NODE_TITLE_PX * compactPlan.scale).toBeGreaterThanOrEqual(MIN_PUBLISHED_TITLE_PX);
  });

  it('keeps the maximum supported deep graph readable in the evaluation viewport', () => {
    const tenLevelLayoutHeight = 2 * VERTICAL_PAD + 10 * VERTICAL_LEVEL_H;

    expect(initialFitScale(760, 500, 760, tenLevelLayoutHeight)).toBeGreaterThanOrEqual(0.5);
  });

  it('bounds edge-label centers inside the fitted layout', () => {
    expect(boundLabelCenter(
      { x: 8, y: 152 },
      { width: 113, height: 13 },
      { width: 1440, height: 880 },
    )).toEqual({ x: 60.5, y: 152 });
    expect(boundLabelCenter(
      { x: 1432, y: 878 },
      { width: 113, height: 13 },
      { width: 1440, height: 880 },
    )).toEqual({ x: 1379.5, y: 869.5 });
  });

  it.each([
    ['25-node mixed topology', [2, 2, 3, 2, 1, 3, 1, 1, 2, 1, 1, 2, 1, 1, 1, 1]],
    ['37-node deep topology', [4, 2, 2, 2, 4, 3, 1, 1, 1, 1, 2, 1, 1, 1, 2, 1, 1, 1, 1, 3, 1, 1]],
    ['39-node deep topology', [3, 2, 3, 3, 1, 5, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 1, 1, 1, 2, 1, 1]],
    ['40-node mixed topology', [5, 5, 4, 4, 3, ...Array.from({ length: 19 }, () => 1)]],
  ])('plans a readable virtual canvas for a %s', (_name, levelSizes) => {
    const plan = planVerticalLayout(656, 848, levelSizes as number[]);

    expect((levelSizes as number[]).reduce((total, size) => total + size, 0)).toBeGreaterThanOrEqual(25);
    expect(15.36 * plan.scale).toBeGreaterThanOrEqual(6);
    expect(plan.nodesPerRow).toBeGreaterThan(1);
  });

  it('packs deep levels into deterministic alternating tracks', () => {
    const levelSizes = Array.from({ length: 42 }, () => 1);
    const plan = planVerticalLayout(1440, 960, levelSizes);
    const tracks = [...new Set(plan.levels.map(level => level.track))];

    expect(plan.levels).toHaveLength(42);
    expect(plan.scale).toBeGreaterThanOrEqual(0.9);
    expect(tracks.length).toBeGreaterThan(1);
    expect(plan.levels.map(level => level.track)).toEqual(
      [...plan.levels.map(level => level.track)].sort((left, right) => left - right),
    );
    for (const track of tracks) {
      const placements = plan.levels.filter(level => level.track === track);
      expect(new Set(placements.map(level => level.direction))).toEqual(
        new Set([track % 2 === 0 ? 1 : -1]),
      );
      const yValues = placements.map(level => level.y);
      expect(yValues).toEqual(
        [...yValues].sort((left, right) => (track % 2 === 0 ? left - right : right - left)),
      );
    }
    expect(planVerticalLayout(1440, 960, levelSizes)).toEqual(plan);
  });

  it('keeps a mixed 40-node topology above publication text size', () => {
    const levelSizes = [5, 5, 4, 4, 3, ...Array.from({ length: 19 }, () => 1)];
    const plan = planVerticalLayout(1440, 960, levelSizes);

    expect(levelSizes.reduce((total, size) => total + size, 0)).toBe(40);
    expect(plan.levels).toHaveLength(levelSizes.length);
    expect(plan.nodesPerRow).toBeGreaterThanOrEqual(3);
    expect(15.36 * plan.scale).toBeGreaterThanOrEqual(12);
    expect(plan.levels.every(level => (
      level.y >= VERTICAL_PAD
      && level.y + VERTICAL_LEVEL_H <= plan.layoutHeight - VERTICAL_PAD + VERTICAL_LEVEL_H
    ))).toBe(true);
  });

  it.each([
    [[1, 1, 5, 1, 1], 3],
    [[1, 8, 1], 3],
  ])('preserves the parallel shape of %j', (levelSizes, minimumNodesPerRow) => {
    const plan = planVerticalLayout(760, 500, levelSizes as number[]);

    expect(plan.nodesPerRow).toBeGreaterThanOrEqual(minimumNodesPerRow);
  });

  it('finds the minimum-height contiguous partition before minimizing width', () => {
    const rows = [1, 1, 1, 3, 1];
    const ranges = partitionVerticalLevels(rows, rows, 1, 3);
    const loads = ranges.map(([start, end]) => (
      rows.slice(start, end).reduce((total, value) => total + value, 0)
    ));

    expect(ranges).toEqual([[0, 3], [3, 4], [4, 5]]);
    expect(Math.max(...loads)).toBe(3);
  });

  it('keeps backward edges when both endpoints exist', () => {
    const edges = [
      { source: 'a', target: 'b', label: 'forward' },
      { source: 'b', target: 'a', label: 'return' },
      { source: 'b', target: 'missing', label: 'invalid' },
    ] as GraphEdge[];

    expect(filterRenderableEdges(edges, new Set(['a', 'b']))).toEqual(edges.slice(0, 2));
  });

  it('wraps long domain labels without dropping their distinguishing words', () => {
    expect(wrapNodeLabel('AI Severity & Narrative Assistant', text => text.length * 8)).toEqual([
      'AI Severity &',
      'Narrative Assistant',
    ]);
  });

  it('wraps wide labels even when they contain fewer than 24 characters', () => {
    const measureTextWidth = (text: string) => text.length * 9;
    const lines = wrapNodeLabel('Flagged Run Review Queue', measureTextWidth);

    expect(lines).toEqual(['Flagged Run', 'Review Queue']);
    expect(lines.join(' ')).toBe('Flagged Run Review Queue');
    expect(lines.every(line => measureTextWidth(line) <= 162)).toBe(true);
    expect(wrapNodeLabel('iiiiiiiiiiiiiiiiiiiiiiiii', text => text.length * 3))
      .toEqual(['iiiiiiiiiiiiiiiiiiiiiiiii']);
  });

  it('truncates unbroken wide labels to measured card width', () => {
    const measureTextWidth = (text: string) => text.length * 15;
    const lines = wrapNodeLabel('WWWWWWWWWWWWWWWWWWWW', measureTextWidth);

    expect(lines).toEqual(['WWWWWWWWW…']);
    expect(measureTextWidth(lines[0])).toBeLessThanOrEqual(162);
  });

  it('preserves deployable technology detail across two compact lines', () => {
    expect(wrapNodeTechnology('Hybrid vector and metadata retrieval with ACL filtering')).toEqual([
      'Hybrid vector and metadata',
      'retrieval with ACL filtering',
    ]);
  });

  it('shows semantic spine labels without turning feedback into overview noise', () => {
    expect(overviewEdgeLabelOpacity({ flow: 'runtime' }, true)).toBeGreaterThan(0.7);
    expect(overviewEdgeLabelOpacity({ flow: 'control' }, true)).toBeGreaterThan(0.5);
    expect(overviewEdgeLabelOpacity({ flow: 'control' }, false)).toBe(0);
    expect(overviewEdgeLabelOpacity({ flow: 'runtime' }, false)).toBe(0);
    expect(overviewEdgeLabelOpacity({ flow: 'deployment' }, true)).toBe(0);
    expect(overviewEdgeLabelOpacity({ flow: 'feedback', type: 'loop' }, true)).toBe(0);
  });

  it('bounds dense out-of-sample overview labels using structure rather than domain words', () => {
    const edges = Array.from({ length: 12 }, (_, index) => ({
      source: `stage_${index}`,
      target: `stage_${index + 1}`,
      label: `moves payload ${index}`,
      technology: 'Typed event',
      sync: 'async' as const,
      description: 'Carries a versioned payload.',
      flow: index % 4 === 3 ? 'control' as const : 'runtime' as const,
    }));
    const sequence = Array.from({ length: 13 }, (_, index) => ({
      step: index + 1,
      nodes: [`stage_${index}`],
      description: `Stage ${index + 1}`,
    }));

    const selected = selectOverviewEdgeIndices(edges, sequence);

    expect(selected.size).toBe(8);
    expect([...selected].every(index => index >= 0 && index < edges.length)).toBe(true);
    expect([...selected].some(index => edges[index].flow === 'control')).toBe(true);
    expect([...selected].some(index => edges[index].flow === 'runtime')).toBe(true);
  });
});
