import {
  readRunApiV1RunsRunIdGet,
  readRunEventsApiV1RunsRunIdEventsGet,
  type RunRead
} from '$lib/api/generated';
import {
  isTerminalLifecycleEvent,
  latestEventCursor,
  requirePersistedEventPage,
  type PersistedDurableEvent,
  type PersistedEventPage
} from './durableEvents';
import { openRunEventStream, type EventStreamOpener } from './events';
import { isTerminalRunStatus } from './status';

export type RunHydration = PersistedEventPage & {
  run: RunRead;
  cursor: number;
};

export async function hydrateRunDetail(runId: string): Promise<RunHydration> {
  const runResponse = await readRunApiV1RunsRunIdGet({
    path: { run_id: runId },
    throwOnError: true
  });
  const run = runResponse.data;
  const eventsResponse = await readRunEventsApiV1RunsRunIdEventsGet({
    path: { run_id: run.id },
    throwOnError: true
  });
  const page = requirePersistedEventPage(eventsResponse.data, run.id);
  const events = page.events;
  const cursor = latestEventCursor(events);
  return {
    run,
    events,
    cursor,
    nextBeforeEventId: page.nextBeforeEventId
  };
}

export async function loadOlderRunEvents(
  runId: string,
  beforeEventId: number
): Promise<PersistedEventPage> {
  const response = await readRunEventsApiV1RunsRunIdEventsGet({
    path: { run_id: runId },
    query: { before_event_id: beforeEventId },
    throwOnError: true
  });
  return requirePersistedEventPage(response.data, runId);
}

export async function loadAndContinueRunDetail(
  runId: string,
  onHydrated: (hydration: RunHydration) => void,
  onEvent: (event: PersistedDurableEvent) => void,
  openStream: EventStreamOpener = openRunEventStream
): Promise<() => void> {
  const hydration = await hydrateRunDetail(runId);
  onHydrated(hydration);
  if (
    isTerminalRunStatus(hydration.run.status) ||
    hydration.events.some(isTerminalLifecycleEvent)
  ) {
    return () => {};
  }
  return openStream(hydration.run.id, hydration.cursor, onEvent);
}
