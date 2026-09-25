import { describe, expect, it } from 'vitest';
import { resizeCenteredZone, snapBounds, zoneFrame } from './diagramAlignment';

describe('smart alignment guides', () => {
  const box = { x: 4, y: 97, width: 100, height: 60 };
  const target = { x: 0, y: 200, width: 100, height: 60 };

  it('snaps matching edges and centers within the supplied distance', () => {
    const snap = snapBounds(box, [target], 6);
    expect(snap.dx).toBe(-4);
    expect(snap.dy).toBe(0);
    expect(snap.guides).toEqual([{ axis: 'x', position: 0, start: 85, end: 272 }]);
    const centered = snapBounds({ x: 46, y: 0, width: 100, height: 60 }, [{ x: 0, y: 200, width: 200, height: 60 }], 6);
    expect(centered.dx).toBe(4);
    expect(centered.guides[0].position).toBe(100);
  });

  it('respects zoom-adjusted thresholds, disabled axes, and empty targets', () => {
    expect(snapBounds(box, [target], 3).guides).toEqual([]);
    expect(snapBounds(box, [target], 6, { x: [] }).guides).toEqual([]);
    expect(snapBounds(box, [], 6)).toEqual({ dx: 0, dy: 0, guides: [] });
    expect(snapBounds({ ...box, x: 6 }, [target], 6).dx).toBe(-6);
  });

  it('chooses the same guide regardless of target order', () => {
    const targets = [target, { ...target, x: 8 }];
    expect(snapBounds(box, targets, 6)).toEqual(snapBounds(box, [...targets].reverse(), 6));
  });
});

describe('centered zone frames', () => {
  const content = { x: 100, y: 100, width: 300, height: 150 };
  const padding = { left: 100, right: 0, top: 30, bottom: 10 };
  const frame = zoneFrame(content, padding);

  it('centers an old asymmetric frame without changing its boundaries', () => {
    const result = resizeCenteredZone(frame, content, '', 0, 0);
    expect(result.frame).toEqual(frame);
    expect(result.contentOffset).toEqual({ x: -50, y: -10 });
    expect(result.padding).toEqual({ left: 50, right: 50, top: 20, bottom: 20 });
    expect(zoneFrame({ ...content, x: 50, y: 90 }, result.padding)).toEqual(frame);
  });

  it.each(['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'])('keeps opposite boundaries fixed while resizing %s', side => {
    const result = resizeCenteredZone(frame, content, side, 20, 10);
    if (side.includes('w')) expect(result.frame.x + result.frame.width).toBe(frame.x + frame.width);
    else expect(result.frame.x).toBe(frame.x);
    if (side.includes('n')) expect(result.frame.y + result.frame.height).toBe(frame.y + frame.height);
    else expect(result.frame.y).toBe(frame.y);
    const moved = { ...content, x: content.x + result.contentOffset.x, y: content.y + result.contentOffset.y };
    expect(zoneFrame(moved, result.padding)).toEqual(result.frame);
    expect(result.padding.left).toBe(result.padding.right);
    expect(result.padding.top).toBe(result.padding.bottom);
  });

  it('clamps to the contents and bounds expansion without mutating input', () => {
    const min = resizeCenteredZone(frame, content, 'nw', 10000, 10000);
    expect(min.frame.width).toBe(content.width + 48);
    expect(min.frame.height).toBe(content.height + 62);
    const max = resizeCenteredZone(frame, content, 'se', 50000, 50000);
    expect(Object.values(max.padding).every(value => value === 10000)).toBe(true);
    expect(content.x).toBe(100);
    expect(padding.left).toBe(100);
  });
});
