import { hasOnlyEventFields } from "$lib/api/responseValidation/fields";
import type { LiveRunEvent } from "$lib/api/generated";
import { isFiniteDateTime, isRecord } from "$lib/valueGuards";
import {
  isEquityChartPayload,
  isMarketChartPayload,
  isStreamHealthPayload,
  isWalletChartPayload,
} from "../dashboardPayloads";
import { LIVE_EVENT_KIND } from "../eventKinds";

export function liveRunEvent(data: unknown, runId: string): LiveRunEvent | null {
  if (!isRecord(data)) return null;
  const candidate = data;
  if (
    candidate.run_id !== runId ||
    candidate.id !== undefined ||
    !isFiniteDateTime(candidate.occurred_at) ||
    !isRecord(candidate.payload)
  )
    return null;
  const payload = candidate.payload;
  if (
    !isLiveKind(candidate.kind) ||
    !hasOnlyEventFields(candidate, candidate.kind, "live") ||
    !isLivePayload(candidate.kind, payload)
  ) {
    return null;
  }
  return candidate as unknown as LiveRunEvent;
}

function isLiveKind(kind: unknown): kind is LiveRunEvent["kind"] {
  return Object.values(LIVE_EVENT_KIND).includes(kind as never);
}

function isLivePayload(kind: LiveRunEvent["kind"], payload: Record<string, unknown>): boolean {
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
