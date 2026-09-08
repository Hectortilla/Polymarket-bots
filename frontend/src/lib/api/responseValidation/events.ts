import {
  isPersistedEventId,
  persistedDurableEvent,
  persistedEventPage,
} from '$lib/runs/durableEvents';

import { liveRunEvent } from '$lib/runs/events/live';

import { isNonemptyString, isRecord } from '$lib/valueGuards';

export function isEventPage(value: Record<string, unknown>, expectedRunId?: string): boolean {
  if (!Array.isArray(value.events)) return false;
  if (value.next_before_event_id !== null && !isPersistedEventId(value.next_before_event_id))
    return false;
  if (expectedRunId !== undefined) {
    return persistedEventPage(value, expectedRunId) !== null;
  }
  return value.events.every(
    (event) =>
      isRecord(event) &&
      typeof event.run_id === 'string' &&
      persistedDurableEvent(event, event.run_id) !== null,
  );
}

export function isRunEvent(value: Record<string, unknown>): boolean {
  if (!isNonemptyString(value.run_id)) return false;
  try {
    if (value.id !== undefined) {
      return persistedDurableEvent(value, value.run_id) !== null;
    }
    return liveRunEvent(value, value.run_id) !== null;
  } catch {
    return false;
  }
}
