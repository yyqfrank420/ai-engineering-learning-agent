import type { ActivityStep, MessageActivity } from '../types';

const phases = new Set(['context', 'book', 'web', 'components', 'connections', 'synthesis', 'evidence',
  'architect', 'challenger', 'integrate', 'render', 'review', 'revise', 'explain']);
const statuses = new Set(['active', 'complete', 'retry', 'rejected', 'degraded']);
const stepFields = new Set(['sequence', 'kind', 'phase', 'status', 'text', 'elapsed_ms']);
const maximumDuration = 86_400_000;

function boundedInteger(value: unknown, maximum: number): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 && value <= maximum;
}

export function parseActivityStep(value: unknown): ActivityStep | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined;
  const step = value as Partial<ActivityStep>;
  if (Object.keys(value).some(key => !stepFields.has(key))
    || !boundedInteger(step.sequence, Number.MAX_SAFE_INTEGER)
    || !boundedInteger(step.elapsed_ms, maximumDuration)
    || (step.kind !== 'update' && step.kind !== 'tool')
    || typeof step.phase !== 'string' || !phases.has(step.phase)
    || typeof step.status !== 'string' || !statuses.has(step.status)
    || typeof step.text !== 'string' || !step.text.trim() || [...step.text].length > 400) return undefined;
  return { sequence: step.sequence, kind: step.kind, phase: step.phase,
    status: step.status, text: step.text, elapsed_ms: step.elapsed_ms };
}

export function parseMessageActivity(value: unknown): MessageActivity | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined;
  const activity = value as Partial<MessageActivity>;
  if (Object.keys(value).some(key => key !== 'duration_ms' && key !== 'steps')
    || !boundedInteger(activity.duration_ms, maximumDuration)
    || !Array.isArray(activity.steps) || activity.steps.length > 48) return undefined;
  const steps: ActivityStep[] = [];
  for (const value of activity.steps) {
    const step = parseActivityStep(value);
    const previous = steps.at(-1);
    if (!step || step.elapsed_ms > activity.duration_ms
      || (previous && (step.sequence <= previous.sequence || step.elapsed_ms < previous.elapsed_ms))) return undefined;
    steps.push(step);
  }
  const parsed = { duration_ms: activity.duration_ms, steps };
  return new TextEncoder().encode(JSON.stringify(parsed)).length <= 32768 ? parsed : undefined;
}
