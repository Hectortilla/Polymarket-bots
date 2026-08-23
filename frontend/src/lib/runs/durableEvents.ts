import type {
  DurableEvent,
  EventCursorValue,
  RunEventPage,
  StreamRunEventsApiV1RunsRunIdEventsStreamGetData,
  RunStatus
} from '$lib/api/generated';

import { INITIAL_RUN_STATUS, isTerminalRunStatus } from './status';

export const INITIAL_EVENT_CURSOR: EventCursorValue = 0;
const FIRST_DURABLE_EVENT_ID = INITIAL_EVENT_CURSOR + 1;
export const EVENT_KIND = {
  runLifecycle: 'run.lifecycle',
  runBootstrap: 'run.bootstrap',
  botActivity: 'bot.activity',
  brokerOrder: 'broker.order',
  brokerFill: 'broker.fill',
  brokerFailure: 'broker.failure',
  marketSettlement: 'market.settlement',
  portfolioSnapshot: 'portfolio.snapshot',
  walletTimeline: 'wallet.timeline',
  streamHealth: 'stream.health',
  runFailure: 'run.failure'
} as const satisfies Record<string, DurableEvent['kind']>;
type EventCursorQuery = NonNullable<
  StreamRunEventsApiV1RunsRunIdEventsStreamGetData['query']
>;

type WithPersistedId<T> = T extends DurableEvent
  ? Omit<T, 'id'> & { id: number }
  : never;

type PersistedGeneratedEvent = WithPersistedId<DurableEvent>;
type PersistedLifecycleEvent = Extract<
  PersistedGeneratedEvent,
  { kind: typeof EVENT_KIND.runLifecycle }
>;

export type PersistedDurableEvent =
  | Exclude<
      PersistedGeneratedEvent,
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
  event: DurableEvent,
  runId: string
): PersistedDurableEvent | null {
  if (
    event.run_id !== runId ||
    !Number.isSafeInteger(event.id) ||
    Number(event.id) < FIRST_DURABLE_EVENT_ID
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

export function requirePersistedDurableEvents(
  events: DurableEvent[],
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
  const events = requirePersistedDurableEvents(page.events, runId);
  const nextBeforeEventId = page.next_before_event_id;
  if (nextBeforeEventId !== null && nextBeforeEventId !== events[0]?.id) {
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
