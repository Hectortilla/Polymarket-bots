import type {
  ChartSamplePayload,
  StreamHealthPayload,
  WalletChartPointPayload
} from '$lib/api/generated';

import { EVENT_KIND, type PersistedDurableEvent } from '$lib/runs/durableEvents';
import type { LiveRunEvent } from '$lib/runs/events';
import { LIVE_EVENT_KIND } from '$lib/runs/eventKinds';

import {
  MAX_CHART_HISTORY_POINTS,
  MAX_WALLET_TIMELINE_EVENTS,
  VALUATION_STATUS
} from './contracts';

export { MAX_CHART_HISTORY_POINTS } from './contracts';

export type DashboardHistory = {
  samples: ChartSamplePayload[];
  walletTimelinePoints: WalletChartPointPayload[];
  streamHealth: StreamHealthPayload | null;
};

export function emptyDashboardHistory(): DashboardHistory {
  return { samples: [], walletTimelinePoints: [], streamHealth: null };
}

export function mergeDurableEvents(
  history: DashboardHistory,
  events: PersistedDurableEvent[]
): DashboardHistory {
  const samples: ChartSamplePayload[] = [];
  const walletPoints: WalletChartPointPayload[] = [];
  let streamHealth = history.streamHealth;
  let streamHealthChanged = false;

  for (const event of events) {
    if (event.kind === EVENT_KIND.chartSample) {
      samples.push(event.payload);
    } else if (event.kind === EVENT_KIND.walletTimeline) {
      walletPoints.push(event.payload.point);
    } else if (event.kind === EVENT_KIND.streamHealth) {
      streamHealth = event.payload;
      streamHealthChanged = true;
    }
  }

  const next = withWalletTimelinePoints(withSamples(history, samples), walletPoints);
  return streamHealthChanged ? { ...next, streamHealth } : next;
}

export function mergeLiveEvent(
  history: DashboardHistory,
  event: LiveRunEvent
): DashboardHistory {
  return mergeLiveEvents(history, [event]);
}

export function mergeLiveEvents(
  history: DashboardHistory,
  events: LiveRunEvent[]
): DashboardHistory {
  const samplesByTimestamp = new Map<number, ChartSamplePayload>();
  const walletPoints: WalletChartPointPayload[] = [];
  let streamHealth: StreamHealthPayload | null = history.streamHealth;
  let streamHealthChanged = false;

  const sampleAtTimestamp = (sampledAtMs: number): ChartSamplePayload =>
    samplesByTimestamp.get(sampledAtMs)
    ?? sampleAt(history, sampledAtMs)
    ?? {
      sampled_at_ms: sampledAtMs,
      markets: [],
      equity: { value: null, status: VALUATION_STATUS.unavailable }
    };

  for (const event of events) {
    switch (event.kind) {
      case LIVE_EVENT_KIND.market: {
        const sample = sampleAtTimestamp(event.payload.sampled_at_ms);
        samplesByTimestamp.set(event.payload.sampled_at_ms, {
          ...sample,
          markets: event.payload.points
        });
        break;
      }
      case LIVE_EVENT_KIND.equity: {
        const sample = sampleAtTimestamp(event.payload.sampled_at_ms);
        samplesByTimestamp.set(event.payload.sampled_at_ms, {
          ...sample,
          equity: event.payload.point
        });
        break;
      }
      case LIVE_EVENT_KIND.wallet:
        walletPoints.push(...event.payload.points);
        break;
      case LIVE_EVENT_KIND.streamHealth:
        streamHealth = event.payload;
        streamHealthChanged = true;
        break;
      default:
        event satisfies never;
    }
  }

  const next = withWalletTimelinePoints(
    withSamples(history, [...samplesByTimestamp.values()]),
    walletPoints
  );
  return streamHealthChanged ? { ...next, streamHealth } : next;
}

function withSamples(
  history: DashboardHistory,
  incoming: ChartSamplePayload[]
): DashboardHistory {
  if (incoming.length === 0) return history;
  const byTimestamp = new Map(
    history.samples.map((sample) => [sample.sampled_at_ms, sample])
  );
  for (const sample of incoming) byTimestamp.set(sample.sampled_at_ms, sample);
  return {
    ...history,
    samples: [...byTimestamp.values()]
      .sort((left, right) => left.sampled_at_ms - right.sampled_at_ms)
      .slice(-MAX_CHART_HISTORY_POINTS)
  };
}

function withWalletTimelinePoints(
  history: DashboardHistory,
  points: WalletChartPointPayload[]
): DashboardHistory {
  if (points.length === 0) return history;
  const bySource = new Map(
    history.walletTimelinePoints.map((point) => [point.source_key, point])
  );
  for (const point of points) bySource.set(point.source_key, point);
  return {
    ...history,
    walletTimelinePoints: [...bySource.values()]
      .sort((left, right) => left.trade_timestamp_ms - right.trade_timestamp_ms)
      .slice(-MAX_WALLET_TIMELINE_EVENTS)
  };
}

function sampleAt(
  history: DashboardHistory,
  sampledAtMs: number
): ChartSamplePayload | undefined {
  return history.samples.find((sample) => sample.sampled_at_ms === sampledAtMs);
}
