import type {
  DurableEvent,
  LiveRunEvent,
  StreamRunEventsApiV1RunsRunIdEventsStreamGetData,
} from '$lib/api/generated';
import { client } from '$lib/api/generated/client.gen';
import {
  isEquityChartPayload,
  isMarketChartPayload,
  isRecord,
  isStreamHealthPayload,
  isWalletChartPayload
} from './dashboardPayloads';
import {
  eventCursorQuery,
  isTerminalLifecycleEvent,
  persistedDurableEvent,
  type PersistedDurableEvent
} from './durableEvents';
import { LIVE_EVENT_KIND } from './eventKinds';

export { LIVE_EVENT_KIND } from './eventKinds';

type StreamRequest = StreamRunEventsApiV1RunsRunIdEventsStreamGetData;
export type { LiveRunEvent } from '$lib/api/generated';
const RUN_EVENTS_STREAM_PATH: StreamRequest['url'] =
  '/api/v1/runs/{run_id}/events/stream';

export type EventStreamOpener = (
  runId: string,
  afterEventId: number,
  onDurableEvent: (event: PersistedDurableEvent) => void,
  onLiveEvent: (event: LiveRunEvent) => void
) => () => void;

export const openRunEventStream: EventStreamOpener = (
  runId,
  afterEventId,
  onDurableEvent,
  onLiveEvent
) => {
  const url = runEventStreamUrl(runId, afterEventId);
  const source = new EventSource(url);
  let cursor = afterEventId;

  source.onmessage = (message) => {
    const payload: unknown = parseJson(message.data);
    const event = parseDurableEvent(payload, runId);
    if (event !== null) {
      if (event.id <= cursor) return;
      cursor = event.id;
      onDurableEvent(event);
      if (isTerminalLifecycleEvent(event)) source.close();
      return;
    }
    const live = parseLiveEvent(payload, runId);
    if (live !== null) onLiveEvent(live);
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
  data: unknown,
  runId: string
): PersistedDurableEvent | null {
  try {
    return persistedDurableEvent(data as DurableEvent, runId);
  } catch {
    return null;
  }
}

function parseLiveEvent(data: unknown, runId: string): LiveRunEvent | null {
  if (!isRecord(data)) return null;
  const candidate = data;
  if (
    candidate.run_id !== runId ||
    candidate.id !== undefined ||
    typeof candidate.occurred_at !== 'string' ||
    !Number.isFinite(Date.parse(candidate.occurred_at)) ||
    !isRecord(candidate.payload)
  ) return null;
  const payload = candidate.payload;
  if (!isLiveKind(candidate.kind) || !isLivePayload(candidate.kind, payload)) {
    return null;
  }
  return candidate as unknown as LiveRunEvent;
}

function isLiveKind(kind: unknown): kind is LiveRunEvent['kind'] {
  return Object.values(LIVE_EVENT_KIND).includes(kind as never);
}

function isLivePayload(
  kind: LiveRunEvent['kind'],
  payload: Record<string, unknown>
): boolean {
  switch (kind) {
    case LIVE_EVENT_KIND.market:
      return isMarketChartPayload(payload);
    case LIVE_EVENT_KIND.equity:
      return isEquityChartPayload(payload);
    case LIVE_EVENT_KIND.wallet:
      return isWalletChartPayload(payload);
    case LIVE_EVENT_KIND.streamHealth:
      return isStreamHealthPayload(payload);
    default:
      return kind satisfies never;
  }
}

function parseJson(data: string): unknown {
  try {
    return JSON.parse(data);
  } catch {
    return null;
  }
}
