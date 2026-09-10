import { describe, expect, it } from "vitest";
import type { ActivitySeverity, OrderStatus } from "$lib/api/generated";
import runtimeContract from "$lib/runtimeContract.fixture.json";
import { SIDE } from "$lib/sides";
import { EVENT_KIND, type PersistedDurableEvent } from "./durableEvents";
import { eventLabel, isUserFacingEvent } from "./eventFeed";
import { eventSummary } from "./eventSummary";
import { RUN_STATUS } from "./status";

const BASE_EVENT = { id: 1, run_id: "run", occurred_at: "2026-09-11T00:00:00Z" };
const ORDER = { token_id: "yes", side: SIDE.buy, price: "0.5", size: "5" };

describe("user-facing event feed", () => {
  it.each([
    [runtimeContract.activitySeverity.INFO, false],
    [runtimeContract.activitySeverity.SUCCESS, false],
    [runtimeContract.activitySeverity.WARNING, true],
    [runtimeContract.activitySeverity.ERROR, true],
  ] as const)("uses %s severity rather than message text to select activity", (severity, visible) => {
    const event: PersistedDurableEvent = {
      ...BASE_EVENT,
      kind: EVENT_KIND.botActivity,
      payload: { message: "An arbitrary bot message", severity: severity as ActivitySeverity },
    };
    expect(isUserFacingEvent(event)).toBe(visible);
  });

  it.each([
    [runtimeContract.orderStatus.ACCEPTED, false],
    [runtimeContract.orderStatus.FILLED, true],
    [runtimeContract.orderStatus.PARTIAL, true],
    [runtimeContract.orderStatus.REJECTED, true],
    [runtimeContract.orderStatus.CANCELED, true],
  ] as const)("shows %s order outcomes: %s", (status, visible) => {
    const hasExecution =
      status === runtimeContract.orderStatus.FILLED || status === runtimeContract.orderStatus.PARTIAL;
    const event: PersistedDurableEvent = {
      ...BASE_EVENT,
      kind: EVENT_KIND.brokerFill,
      payload: {
        order: ORDER,
        fill: {
          order_id: "order",
          token_id: ORDER.token_id,
          side: ORDER.side,
          status: status as OrderStatus,
          requested_size: ORDER.size,
          filled_size: status === runtimeContract.orderStatus.FILLED ? ORDER.size : hasExecution ? "2" : "0",
          average_price: hasExecution ? ORDER.price : null,
          fee_usdc: "0",
          received_at_ms: 1,
        },
        latency_ms: 0,
        portfolio: null,
      },
    };
    expect(isUserFacingEvent(event)).toBe(visible);
  });

  it("hides submission notices but keeps execution errors and run lifecycle events", () => {
    const order: PersistedDurableEvent = { ...BASE_EVENT, kind: EVENT_KIND.brokerOrder, payload: { order: ORDER } };
    const failure: PersistedDurableEvent = {
      ...BASE_EVENT,
      kind: EVENT_KIND.brokerFailure,
      payload: { order: ORDER, error: "Order unavailable" },
    };
    const runFailure: PersistedDurableEvent = {
      ...BASE_EVENT,
      kind: EVENT_KIND.runFailure,
      payload: { error: "Run unavailable" },
    };
    expect(isUserFacingEvent(order)).toBe(false);
    expect(isUserFacingEvent(failure)).toBe(true);
    expect(eventLabel(failure)).toBe("Order error");
    expect(isUserFacingEvent(runFailure)).toBe(true);
    for (const status of Object.values(RUN_STATUS)) {
      expect(isUserFacingEvent({ ...BASE_EVENT, kind: EVENT_KIND.runLifecycle, payload: { status } })).toBe(true);
    }
  });

  it("shows settlements only for bot positions, including losses with zero payout", () => {
    const event: Extract<PersistedDurableEvent, { kind: typeof EVENT_KIND.marketSettlement }> = {
      ...BASE_EVENT,
      kind: EVENT_KIND.marketSettlement,
      payload: {
        portfolio: { cash_usdc: "100", cumulative_fees_usdc: "0", positions: [] },
        settlement: {
          settled_at_ms: 1,
          resolution: {
            condition_id: "condition",
            market_slug: "example-market",
            resolved_at_ms: 1,
            source: "test",
            token_ids: ["yes", "no"],
            winning_token_id: "yes",
            winning_outcome: "Yes",
          },
          paper_positions: [],
          followed_wallet_positions: [],
        },
      },
    };
    expect(isUserFacingEvent(event)).toBe(false);
    event.payload.settlement.paper_positions.push({
      owner: "paper",
      token_id: "no",
      size: "5",
      payout_per_token: "0",
      cash_payout_usdc: "0",
    });
    expect(isUserFacingEvent(event)).toBe(true);
    expect(eventSummary(event)).toBe("example-market · Yes won · Payout 0 USDC");
  });
});
