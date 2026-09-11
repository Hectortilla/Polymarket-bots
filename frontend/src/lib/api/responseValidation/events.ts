import { persistedDurableEvent, persistedEventPage } from "$lib/runs/durableEvents";

import { liveRunEvent } from "$lib/runs/events/live";

import { isNonemptyString } from "$lib/valueGuards";

export function isEventPage(value: Record<string, unknown>, expectedRunId?: string): boolean {
  return persistedEventPage(value, expectedRunId) !== null;
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
