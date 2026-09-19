import { MAX_CHART_HISTORY_POINTS } from "$lib/charts/contracts";

import { DashboardHistory } from "$lib/charts/history";
import { describe, expect, it, vi, afterEach } from "vitest";

import type { PersistedDurableEvent } from "$lib/api/generated";
import { EVENT_KIND, requirePersistedDurableEvents } from "$lib/runs/durableEvents";
import type { LiveRunEvent } from "$lib/api/generated";
import { LIVE_EVENT_KIND } from "$lib/runs/eventKinds";
import runContract from "$lib/runtimeContract.fixture.json";
import { SIDE } from "$lib/sides";
import { VALUATION_STATUS } from "./contracts";

const RUN_ID = "00000000-0000-0000-0000-000000000001";

describe("dashboard history", () => {
  it("bounds loaded durable samples and continues with live frames", () => {
    const durable = Array.from({ length: MAX_CHART_HISTORY_POINTS + 2 }, (_, index) => chartEvent(index + 1));
    let history = new DashboardHistory().mergeDurableEvents(requirePersistedDurableEvents(durable, RUN_ID));

    expect(history.samples).toHaveLength(MAX_CHART_HISTORY_POINTS);
    expect(history.samples[0].sampled_at_ms).toBe(3_000);

    history = history.mergeLiveEvent(snapshot(1, 1_000_000));

    expect(history.samples).toHaveLength(MAX_CHART_HISTORY_POINTS);
    expect(history.samples.at(-1)?.equity.value).toBe("101");
  });

  it("hydrates canonical wallet points and terminal health from durable events", () => {
    const wallet = "0x0000000000000000000000000000000000000001";
    const marketLabel = `Market${runContract.dashboard.walletMarketLabelPolicy.partSeparator}Up`;
    const events = requirePersistedDurableEvents(
      [
        {
          id: 1,
          kind: EVENT_KIND.walletTimeline,
          run_id: RUN_ID,
          occurred_at: "2026-08-23T00:00:00Z",
          payload: {
            trade: {
              wallet,
              condition_id: "condition",
              token_id: "token",
              side: SIDE.buy,
              size: "3",
              price: "0.2",
              source_id: "source",
              trade_timestamp_ms: 1,
              observed_at_ms: 1,
              market_slug: "Market",
              outcome: "Up",
            },
            outcome: { accepted: true, skip_reason: null },
            point: {
              source_key: `${wallet}${runContract.walletSourceKeySeparator}source`,
              wallet,
              trade_timestamp_ms: 1,
              side: SIDE.buy,
              notional: "0.6",
              market_label: marketLabel,
              accepted: true,
            },
          },
        },
        {
          id: 2,
          kind: EVENT_KIND.streamHealth,
          run_id: RUN_ID,
          occurred_at: "2026-08-23T00:00:01Z",
          payload: {
            queue_depth: 1,
            peak_queue_depth: 2,
            book_dispatch_lag_ms: 3,
            book_stale: true,
            book_received_count: 4,
            book_coalesced_count: 1,
          },
        },
      ],
      RUN_ID,
    );

    const history = new DashboardHistory().mergeDurableEvents(events);

    expect(history.walletTimelinePoints).toEqual([
      {
        source_key: `${wallet}${runContract.walletSourceKeySeparator}source`,
        wallet,
        trade_timestamp_ms: 1,
        side: SIDE.buy,
        notional: "0.6",
        market_label: marketLabel,
        accepted: true,
      },
    ]);
    expect(history.healthObservation?.health).toEqual(events[1].payload);
  });

  afterEach(() => vi.useRealTimers());

  it("preserves durable markers regardless of live/durable arrival order", () => {
    const durable = chartEvent(1);
    if (durable.kind !== EVENT_KIND.chartSample) throw new Error("fixture");
    durable.payload.markets = [
      { token_id: "token", label: "Market", value: "0.5", status: VALUATION_STATUS.fresh, markers: [SIDE.buy] },
    ];
    for (const liveFirst of [true, false]) {
      const history = liveFirst
        ? new DashboardHistory().mergeLiveEvent(snapshot(1, 1000)).mergeDurableEvents([durable])
        : new DashboardHistory().mergeDurableEvents([durable]).mergeLiveEvent(snapshot(1, 1000));
      expect(history.samples[0].markets[0].markers).toEqual([SIDE.buy]);
      expect(history.samples[0].equity.value).toBe("1");
    }
  });

  it("drops duplicate, reordered and older-generation snapshots", () => {
    const history = new DashboardHistory().mergeLiveEvents([
      snapshot(2, 2000),
      snapshot(1, 1000),
      snapshot(2, 3000),
      { ...snapshot(1, 4000), generation: 2 },
      snapshot(3, 5000),
    ]);
    expect(history.samples.map((s) => s.sampled_at_ms)).toEqual([2000, 4000]);
  });

  it("makes terminal durable state final for later live frames", () => {
    const history = new DashboardHistory().mergeDurableEvents([
      {
        id: 1,
        run_id: RUN_ID,
        occurred_at: new Date().toISOString(),
        kind: EVENT_KIND.runLifecycle,
        payload: { status: "stopped" },
      },
    ]);
    expect(history.terminal).toBe(true);
    expect(history.mergeLiveEvent(snapshot(1, 1000))).toBe(history);
  });

  it("keeps original health observation age across new snapshots", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-01T00:00:00Z"));
    const health = {
      observed_at: new Date().toISOString(),
      health: {
        queue_depth: 1,
        peak_queue_depth: 2,
        book_dispatch_lag_ms: 3,
        book_stale: false,
        book_received_count: 4,
        book_coalesced_count: 1,
      },
    };
    const history = new DashboardHistory().mergeLiveEvent({ ...snapshot(1, 1000), health });
    expect(history.streamHealth?.book_stale).toBe(false);
    vi.advanceTimersByTime((runContract.liveTelemetry.feedTtlSeconds + 1) * 1000);
    const later = history.mergeLiveEvent({ ...snapshot(2, 2000), health });
    expect(later.streamHealth?.book_stale).toBe(true);
    expect(later.streamHealth?.book_dispatch_lag_ms).toBeNull();
  });
});

function snapshot(sequence: number, sampled_at_ms: number): LiveRunEvent {
  return {
    kind: LIVE_EVENT_KIND.snapshot,
    run_id: RUN_ID,
    occurred_at: new Date().toISOString(),
    generation: 1,
    sequence,
    sampled_at_ms,
    markets: [],
    equity: { value: "101", status: VALUATION_STATUS.fresh },
  };
}

function chartEvent(index: number): PersistedDurableEvent {
  return {
    id: index,
    kind: EVENT_KIND.chartSample,
    run_id: RUN_ID,
    occurred_at: "2026-08-23T00:00:00Z",
    payload: {
      sampled_at_ms: index * 1_000,
      markets: [],
      equity: { value: String(index), status: VALUATION_STATUS.fresh },
    },
  };
}
