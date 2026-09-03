import type {
  EventCursorValue,
  PersistedDurableEvent as GeneratedPersistedDurableEvent,
  RunEventPage,
  StreamRunEventsApiV1RunsRunIdEventsStreamGetData,
  RunStatus
} from '$lib/api/generated';
import runtimeContract from '$lib/runtimeContract.fixture.json';

import { isRecord } from '$lib/valueGuards';
import { isDurableEventPayload } from './eventPayloads';
import { EVENT_KIND } from './eventKinds';
import { INITIAL_RUN_STATUS, isTerminalRunStatus } from './status';

export { EVENT_KIND } from './eventKinds';

export const INITIAL_EVENT_CURSOR: EventCursorValue = runtimeContract.durableEventIds.firstCursor;
type EventCursorQuery = NonNullable<
  StreamRunEventsApiV1RunsRunIdEventsStreamGetData['query']
>;

type PersistedLifecycleEvent = Extract<
  GeneratedPersistedDurableEvent,
  { kind: typeof EVENT_KIND.runLifecycle }
>;

export type PersistedDurableEvent =
  | Exclude<
      GeneratedPersistedDurableEvent,
      { kind: typeof EVENT_KIND.runLifecycle }
    >
  | (Omit<PersistedLifecycleEvent, 'payload'> & {
      payload: PersistedLifecycleEvent['payload'] & { status: RunStatus };
    });

export type PersistedEventPage = {
  events: PersistedDurableEvent[];
  nextBeforeEventId: number | null;
};

export function eventCursorQuery(afterEventId: number): EventCursorQuery {
  return { after_event_id: afterEventId };
}

export function persistedDurableEvent(
  value: unknown,
  runId: string
): PersistedDurableEvent | null {
  if (!isRecord(value) || !isDurableEventKind(value.kind) || !isRecord(value.payload)) {
    return null;
  }
  const event = value as unknown as GeneratedPersistedDurableEvent;
  if (
    event.run_id !== runId ||
    typeof event.occurred_at !== 'string' ||
    !Number.isFinite(Date.parse(event.occurred_at)) ||
    !isPersistedEventId(event.id) ||
    !isDurableEventPayload(value.kind, value.payload)
  ) {
    return null;
  }

  if (
    event.kind === EVENT_KIND.runLifecycle &&
    event.payload.status === undefined
  ) {
    return {
      ...event,
      id: Number(event.id),
      payload: { ...event.payload, status: INITIAL_RUN_STATUS }
    };
  }

  return event as PersistedDurableEvent;
}

export function isPersistedEventId(value: unknown): value is number {
  return typeof value === 'number'
    && Number.isSafeInteger(value)
    && value >= runtimeContract.durableEventIds.firstEventId
    && value <= runtimeContract.durableEventIds.maximumEventId;
}

function isDurableEventKind(kind: unknown): kind is GeneratedPersistedDurableEvent['kind'] {
  return Object.values(EVENT_KIND).includes(kind as never);
}

export function requirePersistedDurableEvents(
  events: GeneratedPersistedDurableEvent[],
  runId: string
): PersistedDurableEvent[] {
  return events.map((event) => {
    const persisted = persistedDurableEvent(event, runId);
    if (persisted === null) throw new Error('Invalid persisted run event');
    return persisted;
  });
}

export function requirePersistedEventPage(
  page: RunEventPage,
  runId: string
): PersistedEventPage {
  return parsePersistedEventPage(page, runId);
}

export function persistedEventPage(
  value: unknown,
  runId: string
): PersistedEventPage | null {
  try {
    return parsePersistedEventPage(value, runId);
  } catch {
    return null;
  }
}

function parsePersistedEventPage(
  value: unknown,
  runId: string
): PersistedEventPage {
  if (!isRecord(value) || !Array.isArray(value.events)) {
    throw new Error('Invalid run event page');
  }
  const events = requirePersistedDurableEvents(
    value.events as GeneratedPersistedDurableEvent[],
    runId
  );
  const nextBeforeEventId = value.next_before_event_id;
  const cursorEvent = events[
    runtimeContract.eventPagination.nextCursorEventIndex
  ];
  if (nextBeforeEventId !== null && (
    !isPersistedEventId(nextBeforeEventId)
    || nextBeforeEventId !== cursorEvent?.id
  )) {
    throw new Error('Invalid run event page cursor');
  }
  return { events, nextBeforeEventId };
}

export function isTerminalLifecycleEvent(
  event: PersistedDurableEvent
): boolean {
  return (
    event.kind === EVENT_KIND.runLifecycle &&
    isTerminalRunStatus(event.payload.status)
  );
}

export function latestEventCursor(events: PersistedDurableEvent[]): number {
  return events.reduce(
    (latest, event) => Math.max(latest, event.id),
    INITIAL_EVENT_CURSOR
  );
}
