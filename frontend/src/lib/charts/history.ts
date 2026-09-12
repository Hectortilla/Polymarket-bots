import type { ChartSamplePayload, StreamHealthPayload, WalletChartPointPayload } from "$lib/api/generated";

import { EVENT_KIND, type PersistedDurableEvent } from "$lib/runs/durableEvents";
import type { LiveRunEvent } from "$lib/api/generated";
import { LIVE_EVENT_KIND } from "$lib/runs/eventKinds";

import { MAX_CHART_HISTORY_POINTS, MAX_WALLET_TIMELINE_EVENTS, VALUATION_STATUS } from "./contracts";

export class DashboardHistory {
  constructor(
    readonly samples: ChartSamplePayload[] = [],
    readonly walletTimelinePoints: WalletChartPointPayload[] = [],
    readonly streamHealth: StreamHealthPayload | null = null,
  ) {}

  mergeDurableEvents(events: PersistedDurableEvent[]): DashboardHistory {
    const samples: ChartSamplePayload[] = [];
    const walletPoints: WalletChartPointPayload[] = [];
    let streamHealth = this.streamHealth;
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

    const next = this.withSamples(samples).withWalletTimelinePoints(walletPoints);
    return streamHealthChanged ? new DashboardHistory(next.samples, next.walletTimelinePoints, streamHealth) : next;
  }

  mergeLiveEvent(event: LiveRunEvent): DashboardHistory {
    return this.mergeLiveEvents([event]);
  }

  mergeLiveEvents(events: LiveRunEvent[]): DashboardHistory {
    const samplesByTimestamp = new Map<number, ChartSamplePayload>();
    const walletPoints: WalletChartPointPayload[] = [];
    let streamHealth: StreamHealthPayload | null = this.streamHealth;
    let streamHealthChanged = false;

    const sampleAtTimestamp = (sampledAtMs: number): ChartSamplePayload =>
      samplesByTimestamp.get(sampledAtMs) ??
      this.sampleAt(sampledAtMs) ?? {
        sampled_at_ms: sampledAtMs,
        markets: [],
        equity: { value: null, status: VALUATION_STATUS.unavailable },
      };

    for (const event of events) {
      switch (event.kind) {
        case LIVE_EVENT_KIND.market: {
          const sample = sampleAtTimestamp(event.payload.sampled_at_ms);
          samplesByTimestamp.set(event.payload.sampled_at_ms, {
            ...sample,
            markets: event.payload.points,
          });
          break;
        }
        case LIVE_EVENT_KIND.equity: {
          const sample = sampleAtTimestamp(event.payload.sampled_at_ms);
          samplesByTimestamp.set(event.payload.sampled_at_ms, {
            ...sample,
            equity: event.payload.point,
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

    const next = this.withSamples([...samplesByTimestamp.values()]).withWalletTimelinePoints(walletPoints);
    return streamHealthChanged ? new DashboardHistory(next.samples, next.walletTimelinePoints, streamHealth) : next;
  }

  private withSamples(incoming: ChartSamplePayload[]): DashboardHistory {
    if (incoming.length === 0) return this;
    const byTimestamp = new Map(this.samples.map((sample) => [sample.sampled_at_ms, sample]));
    for (const sample of incoming) byTimestamp.set(sample.sampled_at_ms, sample);
    return new DashboardHistory(
      [...byTimestamp.values()]
        .sort((left, right) => left.sampled_at_ms - right.sampled_at_ms)
        .slice(-MAX_CHART_HISTORY_POINTS),
      this.walletTimelinePoints,
      this.streamHealth,
    );
  }

  private withWalletTimelinePoints(points: WalletChartPointPayload[]): DashboardHistory {
    if (points.length === 0) return this;
    const bySource = new Map(this.walletTimelinePoints.map((point) => [point.source_key, point]));
    for (const point of points) bySource.set(point.source_key, point);
    return new DashboardHistory(
      this.samples,
      [...bySource.values()]
        .sort((left, right) => left.trade_timestamp_ms - right.trade_timestamp_ms)
        .slice(-MAX_WALLET_TIMELINE_EVENTS),
      this.streamHealth,
    );
  }

  private sampleAt(sampledAtMs: number): ChartSamplePayload | undefined {
    return this.samples.find((sample) => sample.sampled_at_ms === sampledAtMs);
  }
}
