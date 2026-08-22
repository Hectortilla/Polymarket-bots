import {
  readRunApiV1RunsRunIdGet,
  readRunEventsApiV1RunsRunIdEventsGet,
  type RunRead
} from '$lib/api/generated';
import {
  INITIAL_EVENT_CURSOR,
  eventCursorQuery,
  latestEventCursor,
  requirePersistedDurableEvents,
  type PersistedDurableEvent
} from './durableEvents';
import { openRunEventStream, type EventStreamOpener } from './events';

export type RunHydration = {
  run: RunRead;
  events: PersistedDurableEvent[];
  cursor: number;
};

export async function hydrateRunDetail(runId: string): Promise<RunHydration> {
  const [runResponse, eventsResponse] = await Promise.all([
    readRunApiV1RunsRunIdGet({ path: { run_id: runId }, throwOnError: true }),
    readRunEventsApiV1RunsRunIdEventsGet({
      path: { run_id: runId },
      query: eventCursorQuery(INITIAL_EVENT_CURSOR),
      throwOnError: true
    })
  ]);
  const run = runResponse.data;
  const events = requirePersistedDurableEvents(eventsResponse.data, run.id);
  const cursor = latestEventCursor(events);
  return { run, events, cursor };
}

export async function loadAndContinueRunDetail(
  runId: string,
  onHydrated: (hydration: RunHydration) => void,
  onEvent: (event: PersistedDurableEvent) => void,
  openStream: EventStreamOpener = openRunEventStream
): Promise<() => void> {
  const hydration = await hydrateRunDetail(runId);
  onHydrated(hydration);
  return openStream(hydration.run.id, hydration.cursor, onEvent);
}
