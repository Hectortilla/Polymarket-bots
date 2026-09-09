import {
  readRunApiV1RunsRunIdGet,
  readRunEventsApiV1RunsRunIdEventsGet,
  type LiveRunEvent,
  type RunRead
} from '$lib/api/generated';
import {
  EVENT_KIND,
  isTerminalLifecycleEvent,
  latestEventCursor,
  requirePersistedEventPage,
  type PersistedDurableEvent,
  type PersistedEventPage
} from './durableEvents';
import {
  openRunEventStream,
  type EventStreamOpener,
  type StreamConnectionState
} from './events';
import { isTerminalRunStatus } from './status';
import { HTTP_STATUS } from '$lib/api/http';

export class RunNotFoundError extends Error {}

export type RunHydration = PersistedEventPage & {
  run: RunRead;
  cursor: number;
};

export async function hydrateRunDetail(runId: string): Promise<RunHydration> {
  let run = await readRun(runId);
  const eventsResponse = await readRunEventsApiV1RunsRunIdEventsGet({
    path: { run_id: run.id },
    throwOnError: true
  });
  const page = requirePersistedEventPage(eventsResponse.data, run.id);
  const events = page.events;
  const cursor = latestEventCursor(events);
  // A transition can commit between the run read and the event-page read. Once
  // included in this cursor it will not replay over SSE, so refresh its state.
  if (!isTerminalRunStatus(run.status) && events.some((event) =>
    event.kind === EVENT_KIND.runLifecycle && event.payload.status !== run.status
  )) {
    run = await readRun(run.id);
  }
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
  onDurableEvent: (event: PersistedDurableEvent) => void,
  onLiveEvent: (event: LiveRunEvent) => void,
  openStream: EventStreamOpener = openRunEventStream,
  onConnectionState?: (state: StreamConnectionState) => void
): Promise<() => void> {
  const hydration = await hydrateRunDetail(runId);
  onHydrated(hydration);
  if (
    isTerminalRunStatus(hydration.run.status) ||
    hydration.events.some(isTerminalLifecycleEvent)
  ) {
    return () => {};
  }
  return openStream(
    hydration.run.id,
    hydration.cursor,
    onDurableEvent,
    onLiveEvent,
    onConnectionState
  );
}

async function readRun(runId: string): Promise<RunRead> {
  const response = await readRunApiV1RunsRunIdGet({ path: { run_id: runId } });
  if (!response.data) {
    if (response.response?.status === HTTP_STATUS.NOT_FOUND) throw new RunNotFoundError();
    throw new Error('Run unavailable');
  }
  return response.data;
}
