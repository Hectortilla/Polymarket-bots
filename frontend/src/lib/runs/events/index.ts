import type {
  LiveRunEvent,
  PersistedDurableEvent as GeneratedPersistedDurableEvent,
  StreamRunEventsApiV1RunsRunIdEventsStreamGetData,
} from "$lib/api/generated";
import { accountSession } from "$lib/auth/session";
import { client } from "$lib/api/generated/client.gen";
import runtimeContract from "$lib/runtimeContract.fixture.json";
import {
  eventCursorQuery,
  isTerminalLifecycleEvent,
  persistedDurableEvent,
  type PersistedDurableEvent,
} from "../durableEvents";
import { liveRunEvent } from "./live";
import { EVENT_VIEW, type RunEventView } from "../eventViews";

export const STREAM_CONNECTION_STATE = { CONNECTED: "connected", RECONNECTING: "reconnecting" } as const;
export type StreamConnectionState = (typeof STREAM_CONNECTION_STATE)[keyof typeof STREAM_CONNECTION_STATE];
const RUN_EVENTS_STREAM_PATH = runtimeContract.apiPaths
  .runEventsStream as StreamRunEventsApiV1RunsRunIdEventsStreamGetData["url"];

export type EventStreamOptions = {
  view: RunEventView;
  onDashboardEvent: (event: PersistedDurableEvent) => void;
};

export type EventStreamOpener = (
  runId: string,
  afterEventId: number,
  onDurableEvent: (event: PersistedDurableEvent) => void,
  onLiveEvent: (event: LiveRunEvent) => void,
  onConnectionState?: (state: StreamConnectionState) => void,
  options?: EventStreamOptions,
) => () => void;

export const openRunEventStream: EventStreamOpener = (
  runId,
  afterEventId,
  onDurableEvent,
  onLiveEvent,
  onConnectionState,
  options,
) => {
  const url = runEventStreamUrl(runId, afterEventId, options?.view);
  const source = new EventSource(url);
  const close = accountSession.streams.track(() => source.close());
  source.onopen = () => onConnectionState?.(STREAM_CONNECTION_STATE.CONNECTED);
  source.onerror = () => {
    onConnectionState?.(STREAM_CONNECTION_STATE.RECONNECTING);
    // EventSource hides HTTP status; separately confirm whether the session expired.
    void accountSession.restore();
  };
  let cursor = afterEventId;

  source.addEventListener(runtimeContract.dashboardSseEvent, (message) => {
    const event = parseDurableEvent(parseJson((message as MessageEvent).data), runId);
    if (event === null || event.id <= cursor) return;
    cursor = event.id;
    options?.onDashboardEvent(event);
  });

  source.onmessage = (message) => {
    const payload: unknown = parseJson(message.data);
    const event = parseDurableEvent(payload, runId);
    if (event !== null) {
      if (event.id <= cursor) return;
      cursor = event.id;
      onDurableEvent(event);
      if (isTerminalLifecycleEvent(event)) close();
      return;
    }
    const live = liveRunEvent(payload, runId);
    if (live !== null) onLiveEvent(live);
  };

  return close;
};

export function runEventStreamUrl(
  runId: string,
  afterEventId: number,
  view: RunEventView = EVENT_VIEW.ACTIVITY,
): string {
  return client.buildUrl({
    url: RUN_EVENTS_STREAM_PATH,
    path: { run_id: runId },
    query: eventCursorQuery(afterEventId, view),
  });
}

function parseDurableEvent(data: unknown, runId: string): PersistedDurableEvent | null {
  try {
    return persistedDurableEvent(data as GeneratedPersistedDurableEvent, runId);
  } catch {
    return null;
  }
}

function parseJson(data: string): unknown {
  try {
    return JSON.parse(data);
  } catch {
    return null;
  }
}
