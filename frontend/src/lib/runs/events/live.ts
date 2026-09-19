import { hasOnlyEventFields, hasOnlyResponseFields } from "$lib/api/responseValidation/fields";
import type { LiveRunEvent } from "$lib/api/generated";
import { isFiniteDateTime, isNonnegativeInteger, isRecord } from "$lib/valueGuards";
import { isEquityPoint, isMarketPoint, isStreamHealthPayload } from "../dashboardPayloads";
import { MAX_CHART_TOKENS } from "$lib/charts/contracts";
import { LIVE_EVENT_KIND } from "../eventKinds";

export function liveRunEvent(data: unknown, runId: string): LiveRunEvent | null {
  if (
    !isRecord(data) ||
    data.kind !== LIVE_EVENT_KIND.snapshot ||
    data.run_id !== runId ||
    !isFiniteDateTime(data.occurred_at) ||
    !hasOnlyEventFields(data, LIVE_EVENT_KIND.snapshot, "live") ||
    !isPositiveSafeInteger(data.generation) ||
    !isPositiveSafeInteger(data.sequence) ||
    !isNonnegativeInteger(data.sampled_at_ms) ||
    !isSnapshotMarkets(data.markets) ||
    !isEquityPoint(data.equity) ||
    !isHealthObservation(data.health)
  )
    return null;
  return data as LiveRunEvent;
}

function isPositiveSafeInteger(value: unknown): boolean {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

function isSnapshotMarkets(value: unknown): boolean {
  if (!Array.isArray(value) || value.length > MAX_CHART_TOKENS) return false;
  return (
    value.every((point) => isMarketPoint(point) && Array.isArray(point.markers) && point.markers.length === 0) &&
    new Set(value.map((point) => point.token_id)).size === value.length
  );
}

function isHealthObservation(value: unknown): boolean {
  return (
    value === undefined ||
    value === null ||
    (isRecord(value) &&
      hasOnlyResponseFields(value, "FeedObservation") &&
      isFiniteDateTime(value.observed_at) &&
      isRecord(value.health) &&
      isStreamHealthPayload(value.health))
  );
}

export type LiveIdentity = readonly [generation: number, sequence: number];

export function isNewerLiveEvent(event: LiveRunEvent, previous: LiveIdentity): boolean {
  return event.generation > previous[0] || (event.generation === previous[0] && event.sequence > previous[1]);
}
