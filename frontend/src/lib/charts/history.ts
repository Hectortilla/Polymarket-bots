import type {
  ChartSamplePayload,
  FeedObservation,
  LiveRunEvent,
  StreamHealthPayload,
  WalletChartPointPayload,
} from "$lib/api/generated";
import { EVENT_KIND, isTerminalLifecycleEvent, type PersistedDurableEvent } from "$lib/runs/durableEvents";
import { MAX_CHART_HISTORY_POINTS, MAX_WALLET_TIMELINE_EVENTS } from "./contracts";
import { isNewerLiveEvent, type LiveIdentity } from "$lib/runs/events/live";
import runtimeContract from "$lib/runtimeContract.fixture.json";

export class DashboardHistory {
  constructor(
    readonly samples: ChartSamplePayload[] = [],
    readonly walletTimelinePoints: WalletChartPointPayload[] = [],
    readonly healthObservation: FeedObservation | null = null,
    private readonly durableTimes: ReadonlySet<number> = new Set(samples.map((sample) => sample.sampled_at_ms)),
    private readonly liveIdentity: LiveIdentity = [0, 0],
    readonly terminal = false,
  ) {}

  get streamHealth(): StreamHealthPayload | null {
    if (this.healthObservation === null) return null;
    const age = Date.now() - Date.parse(this.healthObservation.observed_at);
    return age < 0 || age > runtimeContract.liveTelemetry.feedTtlSeconds * 1000
      ? { ...this.healthObservation.health, book_stale: true, book_dispatch_lag_ms: null }
      : this.healthObservation.health;
  }

  mergeDurableEvents(events: PersistedDurableEvent[]): DashboardHistory {
    const samples = new Map(this.samples.map((sample) => [sample.sampled_at_ms, sample]));
    const wallets = new Map(this.walletTimelinePoints.map((point) => [point.source_key, point]));
    const durableTimes = new Set(this.durableTimes);
    let health = this.healthObservation;
    let terminal = this.terminal;
    for (const event of events) {
      if (event.kind === EVENT_KIND.chartSample) {
        samples.set(event.payload.sampled_at_ms, event.payload);
        durableTimes.add(event.payload.sampled_at_ms);
      } else if (event.kind === EVENT_KIND.walletTimeline) {
        wallets.set(event.payload.point.source_key, event.payload.point);
      } else if (
        event.kind === EVENT_KIND.streamHealth &&
        (health === null || Date.parse(event.occurred_at) >= Date.parse(health.observed_at))
      ) {
        health = { observed_at: event.occurred_at, health: event.payload };
      }
      terminal ||= isTerminalLifecycleEvent(event);
    }
    const retained = this.retainSamples(samples);
    return new DashboardHistory(
      retained,
      [...wallets.values()]
        .sort((a, b) => a.trade_timestamp_ms - b.trade_timestamp_ms)
        .slice(-MAX_WALLET_TIMELINE_EVENTS),
      health,
      new Set(
        retained.filter((sample) => durableTimes.has(sample.sampled_at_ms)).map((sample) => sample.sampled_at_ms),
      ),
      this.liveIdentity,
      terminal,
    );
  }

  finish(): DashboardHistory {
    return new DashboardHistory(
      this.samples,
      this.walletTimelinePoints,
      this.healthObservation,
      this.durableTimes,
      this.liveIdentity,
      true,
    );
  }

  mergeLiveEvent(event: LiveRunEvent): DashboardHistory {
    return this.mergeLiveEvents([event]);
  }

  mergeLiveEvents(events: LiveRunEvent[]): DashboardHistory {
    if (this.terminal) return this;
    const samples = new Map(this.samples.map((sample) => [sample.sampled_at_ms, sample]));
    let identity = this.liveIdentity;
    let health = this.healthObservation;
    for (const event of events) {
      if (!isNewerLiveEvent(event, identity)) continue;
      identity = [event.generation, event.sequence];
      if (!this.durableTimes.has(event.sampled_at_ms)) {
        samples.set(event.sampled_at_ms, {
          sampled_at_ms: event.sampled_at_ms,
          markets: event.markets,
          equity: event.equity,
        });
      }
      if (event.health && (health === null || Date.parse(event.health.observed_at) > Date.parse(health.observed_at)))
        health = event.health;
    }
    const retained = this.retainSamples(samples);
    return new DashboardHistory(
      retained,
      this.walletTimelinePoints,
      health,
      new Set(
        retained.filter((sample) => this.durableTimes.has(sample.sampled_at_ms)).map((sample) => sample.sampled_at_ms),
      ),
      identity,
    );
  }

  private retainSamples(samples: Map<number, ChartSamplePayload>): ChartSamplePayload[] {
    return [...samples.values()].sort((a, b) => a.sampled_at_ms - b.sampled_at_ms).slice(-MAX_CHART_HISTORY_POINTS);
  }
}
