export interface Box { x: number; y: number; width: number; height: number }
export interface AlignmentGuide { axis: 'x' | 'y'; position: number; start: number; end: number }
export interface ZonePadding { top: number; right: number; bottom: number; left: number }

export function snapBounds(box: Box, targets: Box[], threshold: number,
  anchors: { x?: number[]; y?: number[] } = {}): { dx: number; dy: number; guides: AlignmentGuide[] } {
  const result = { dx: 0, dy: 0, guides: [] as AlignmentGuide[] };
  for (const axis of ['x', 'y'] as const) {
    const size = axis === 'x' ? 'width' : 'height';
    const cross = axis === 'x' ? 'y' : 'x';
    const crossSize = axis === 'x' ? 'height' : 'width';
    const candidates = targets.flatMap(target => (anchors[axis] ?? [0, 0.5, 1]).map(anchor => ({
      delta: target[axis] + target[size] * anchor - box[axis] - box[size] * anchor,
      position: target[axis] + target[size] * anchor,
      target,
    }))).filter(candidate => Math.abs(candidate.delta) <= threshold)
      .sort((a, b) => Math.abs(a.delta) - Math.abs(b.delta) || a.position - b.position
        || a.target[cross] - b.target[cross]);
    const nearest = candidates[0];
    if (!nearest) continue;
    result[axis === 'x' ? 'dx' : 'dy'] = nearest.delta;
    result.guides.push({ axis, position: nearest.position,
      start: Math.min(box[cross], nearest.target[cross]) - 12,
      end: Math.max(box[cross] + box[crossSize], nearest.target[cross] + nearest.target[crossSize]) + 12 });
  }
  return result;
}

export function zoneFrame(content: Box, padding: ZonePadding): Box {
  return { x: content.x - 24 - padding.left, y: content.y - 42 - padding.top,
    width: content.width + 48 + padding.left + padding.right,
    height: content.height + 62 + padding.top + padding.bottom };
}

export function resizeCenteredZone(frame: Box, content: Box, side: string, dx: number, dy: number) {
  const width = Math.max(content.width + 48, Math.min(content.width + 20048,
    frame.width + (side.includes('w') ? -dx : side.includes('e') ? dx : 0)));
  const height = Math.max(content.height + 62, Math.min(content.height + 20062,
    frame.height + (side.includes('n') ? -dy : side.includes('s') ? dy : 0)));
  const next = { x: frame.x + (side.includes('w') ? frame.width - width : 0),
    y: frame.y + (side.includes('n') ? frame.height - height : 0), width, height };
  const horizontal = (width - content.width - 48) / 2;
  const vertical = (height - content.height - 62) / 2;
  return { frame: next,
    contentOffset: { x: next.x + width / 2 - content.x - content.width / 2,
      y: next.y + 42 + (height - 62) / 2 - content.y - content.height / 2 },
    padding: { top: vertical, bottom: vertical, left: horizontal, right: horizontal } };
}
