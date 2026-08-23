import type { StreamRunEventsApiV1RunsRunIdEventsStreamGetData } from '$lib/api/generated';
import { client } from '$lib/api/generated/client.gen';

import {
  eventCursorQuery,
  isTerminalLifecycleEvent,
  persistedDurableEvent,
  type PersistedDurableEvent
} from './durableEvents';

type StreamRequest = StreamRunEventsApiV1RunsRunIdEventsStreamGetData;
const RUN_EVENTS_STREAM_PATH: StreamRequest['url'] =
  '/api/v1/runs/{run_id}/events/stream';

export type EventStreamOpener = (
  runId: string,
  afterEventId: number,
  onEvent: (event: PersistedDurableEvent) => void
) => () => void;

export const openRunEventStream: EventStreamOpener = (
  runId,
  afterEventId,
  onEvent
) => {
  const url = runEventStreamUrl(runId, afterEventId);
  const source = new EventSource(url);
  let cursor = afterEventId;

  source.onmessage = (message) => {
    const event = parseDurableEvent(message.data, runId);
    if (event === null || event.id <= cursor) return;
    cursor = event.id;
    onEvent(event);
    if (isTerminalLifecycleEvent(event)) source.close();
  };

  return () => source.close();
};

export function runEventStreamUrl(runId: string, afterEventId: number): string {
  return client.buildUrl({
    url: RUN_EVENTS_STREAM_PATH,
    path: { run_id: runId },
    query: eventCursorQuery(afterEventId)
  });
}

function parseDurableEvent(
  data: string,
  runId: string
): PersistedDurableEvent | null {
  try {
    return persistedDurableEvent(JSON.parse(data), runId);
  } catch {
    return null;
  }
}
