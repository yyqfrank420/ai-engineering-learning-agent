import { describe, expect, it } from 'vitest';
import { parseActivityStep, parseMessageActivity } from '../messageActivity';

const step = { sequence: 0, kind: 'update', phase: 'context', status: 'active', text: 'I am checking your request.', elapsed_ms: 0 };

describe('optional message activity boundary', () => {
  it.each([null, [], 4, {}, { ...step, text: null }, { ...step, sequence: -1 },
    { ...step, elapsed_ms: 86400001 }, { ...step, elapsed_ms: 0.5 },
    { ...step, kind: 'reasoning' }, { ...step, phase: 'private' }, { ...step, status: 'unknown' },
    { ...step, text: ' ' }, { ...step, text: 'x'.repeat(401) }, { ...step, diagnostic: 'private' }])('omits invalid public steps %j', value => {
    expect(parseActivityStep(value)).toBeUndefined();
  });

  it('accepts ordered metadata and measures text bounds in Unicode characters', () => {
    expect(parseActivityStep({ ...step, text: '😀'.repeat(400) })).toBeDefined();
    expect(parseMessageActivity({ duration_ms: 10, steps: [step, { ...step, sequence: 2, elapsed_ms: 10 }] }))
      .toEqual({ duration_ms: 10, steps: [step, { ...step, sequence: 2, elapsed_ms: 10 }] });
  });

  it.each([null, {}, { duration_ms: -1, steps: [] }, { duration_ms: 1, steps: [step, step] },
    { duration_ms: 1, steps: [{ ...step, elapsed_ms: 2 }] },
    { duration_ms: 10, steps: [{ ...step, elapsed_ms: 9 }, { ...step, sequence: 1, elapsed_ms: 8 }] },
    { duration_ms: 1, steps: Array.from({ length: 49 }, (_, sequence) => ({ ...step, sequence })) },
    { duration_ms: 1, steps: [], private: 'reasoning' }])('omits corrupt metadata %j', value => {
    expect(parseMessageActivity(value)).toBeUndefined();
  });

  it('bounds serialized UTF-8 bytes independently of step count and text length', () => {
    const activity = { duration_ms: 1, steps: Array.from({ length: 48 }, (_, sequence) => ({ ...step, sequence, text: '😀'.repeat(400) })) };
    expect(parseMessageActivity(activity)).toBeUndefined();
  });
});
