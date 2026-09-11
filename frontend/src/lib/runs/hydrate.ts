import {
  readRunApiV1RunsRunIdGet,
  readRunEventsApiV1RunsRunIdEventsGet,
  type LiveRunEvent,
  type RunRead,
} from "$lib/api/generated";
import {
  EVENT_KIND,
  isTerminalLifecycleEvent,
  requirePersistedEventPage,
  type PersistedDurableEvent,
  type PersistedEventPage,
} from "./durableEvents";
import { openRunEventStream, type EventStreamOpener, type StreamConnectionState } from "./events";
import { isTerminalRunStatus } from "./status";
import { EVENT_VIEW, type ActivityEventView } from "./eventViews";
import type { EventView } from "$lib/api/generated";
import { HTTP_STATUS } from "$lib/api/http";

export class RunNotFoundError extends Error {}

export type RunHydration = PersistedEventPage & {
  run: RunRead;
  cursor: number;
  dashboardPage: PersistedEventPage;
};

export async function hydrateRunDetail(
  runId: string,
  view: ActivityEventView = EVENT_VIEW.ACTIVITY,
): Promise<RunHydration> {
  let run = await readRun(runId);
  const [page, dashboardPage] = await Promise.all([
    loadRunEvents(run.id, view),
    loadRunEvents(run.id, EVENT_VIEW.DASHBOARD),
  ]);
  const events = page.events;
  const cursor = Math.min(page.streamCursor, dashboardPage.streamCursor);
  // A transition can commit between the run read and the event-page read. Once
  // included in this cursor it will not replay over SSE, so refresh its state.
  if (
    !isTerminalRunStatus(run.status) &&
    events.some((event) => event.kind === EVENT_KIND.runLifecycle && event.payload.status !== run.status)
  ) {
    run = await readRun(run.id);
  }
  return {
    run,
    events,
    cursor,
    nextBeforeEventId: page.nextBeforeEventId,
    streamCursor: page.streamCursor,
    dashboardPage,
  };
}

export async function loadAndContinueRunDetail(
  runId: string,
  onHydrated: (hydration: RunHydration) => void,
  onDurableEvent: (event: PersistedDurableEvent) => void,
  onLiveEvent: (event: LiveRunEvent) => void,
  openStream: EventStreamOpener = openRunEventStream,
  onConnectionState?: (state: StreamConnectionState) => void,
  view: ActivityEventView = EVENT_VIEW.ACTIVITY,
  onDashboardEvent: (event: PersistedDurableEvent) => void = () => {},
): Promise<() => void> {
  const hydration = await hydrateRunDetail(runId, view);
  onHydrated(hydration);
  if (isTerminalRunStatus(hydration.run.status) || hydration.events.some(isTerminalLifecycleEvent)) {
    return () => {};
  }
  return openStream(
    hydration.run.id,
    hydration.cursor,
    (event) => {
      if (event.id > hydration.streamCursor) onDurableEvent(event);
    },
    onLiveEvent,
    onConnectionState,
    {
      view,
      onDashboardEvent: (event) => {
        if (event.id > hydration.dashboardPage.streamCursor) onDashboardEvent(event);
      },
    },
  );
}

export async function loadRunEvents(
  runId: string,
  view: EventView = EVENT_VIEW.ACTIVITY,
  beforeEventId?: number,
): Promise<PersistedEventPage> {
  const response = await readRunEventsApiV1RunsRunIdEventsGet({
    path: { run_id: runId },
    query: { view, ...(beforeEventId === undefined ? {} : { before_event_id: beforeEventId }) },
    throwOnError: true,
  });
  return requirePersistedEventPage(response.data, runId);
}

async function readRun(runId: string): Promise<RunRead> {
  const response = await readRunApiV1RunsRunIdGet({ path: { run_id: runId } });
  if (!response.data) {
    if (response.response?.status === HTTP_STATUS.NOT_FOUND) throw new RunNotFoundError();
    throw new Error("Run unavailable");
  }
  return response.data;
}
