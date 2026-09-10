import { describe, expect, it } from "vitest";

import type { FillRejectReason, OrderStatus } from "$lib/api/generated";
import runtimeContract from "$lib/runtimeContract.fixture.json";
import { SIDE } from "$lib/sides";
import { EVENT_KIND, type PersistedDurableEvent } from "./durableEvents";
import { combinedFailureDetail, eventFailureDetail, eventSummary } from "./eventSummary";
import { RUN_STATUS } from "./status";

const RUN_ID = "00000000-0000-0000-0000-000000000001";
type BrokerFillEvent = Extract<PersistedDurableEvent, { kind: typeof EVENT_KIND.brokerFill }>;

describe("event summary", () => {
  it("includes a fill rejection reason and message when provided", () => {
    expect(eventSummary(rejectedFill())).toBe(
      "Buy rejected · 0 shares filled · bad_size: order size is below the market minimum · Token token",
    );
  });

  it("does not add an empty rejection detail to a completed fill", () => {
    const fill = rejectedFill();
    fill.payload.fill = {
      ...fill.payload.fill,
      status: runtimeContract.orderStatus.FILLED as OrderStatus,
      filled_size: "5",
      average_price: "0.5",
      reject_reason: null,
      reject_message: null,
    };

    expect(eventSummary(fill)).toBe("Buy filled · 5 shares filled at 0.5 USDC · Fee 0 USDC · Token token");
  });

  it("identifies partial sells with the executed quantity, price, and fee", () => {
    const event = rejectedFill();
    event.payload.fill = {
      ...event.payload.fill,
      side: SIDE.sell,
      status: runtimeContract.orderStatus.PARTIAL as OrderStatus,
      filled_size: "2",
      average_price: "0.6",
      fee_usdc: "0.012",
      reject_reason: null,
      reject_message: null,
    };
    expect(eventSummary(event)).toBe(
      "Sell partially filled · 2 of 5 shares at 0.6 USDC · Fee 0.012 USDC · Token token",
    );
  });

  it("prefers the latest runtime error and retains a distinct recorded outcome", () => {
    const firstFailure = runFailure(1, "ValueError: first failure");
    const latestFailure = runFailure(2, "ConnectionError: stream closed");
    const lifecycle = failedLifecycle(3);

    expect(
      eventFailureDetail(lifecycle, [firstFailure, latestFailure, lifecycle], "ConnectionError: paper run failed"),
    ).toBe("ConnectionError: stream closed\nRecorded failure: ConnectionError: paper run failed");
  });

  it("uses the durable run failure detail when no runtime error event is loaded", () => {
    const lifecycle = failedLifecycle(2);

    expect(eventFailureDetail(lifecycle, [lifecycle], "RuntimeError: run launch failed")).toBe(
      "RuntimeError: run launch failed",
    );
  });

  it("composes a list-projected runtime error with its recorded outcome", () => {
    expect(combinedFailureDetail("ConnectionError: stream closed", "ConnectionError: paper run failed")).toBe(
      "ConnectionError: stream closed\nRecorded failure: ConnectionError: paper run failed",
    );
  });
});

function runFailure(id: number, error: string): Extract<PersistedDurableEvent, { kind: typeof EVENT_KIND.runFailure }> {
  return {
    id,
    kind: EVENT_KIND.runFailure,
    run_id: RUN_ID,
    occurred_at: "2026-08-24T00:00:00Z",
    payload: { error },
  };
}

function failedLifecycle(id: number): Extract<PersistedDurableEvent, { kind: typeof EVENT_KIND.runLifecycle }> {
  return {
    id,
    kind: EVENT_KIND.runLifecycle,
    run_id: RUN_ID,
    occurred_at: "2026-08-24T00:00:00Z",
    payload: { status: RUN_STATUS.FAILED },
  };
}

function rejectedFill(): BrokerFillEvent {
  return {
    id: 1,
    kind: EVENT_KIND.brokerFill,
    run_id: RUN_ID,
    occurred_at: "2026-08-24T00:00:00Z",
    payload: {
      order: {
        token_id: "token",
        side: SIDE.buy,
        price: "0.5",
        size: "5",
      },
      fill: {
        order_id: "order",
        token_id: "token",
        side: SIDE.buy,
        status: runtimeContract.orderStatus.REJECTED as OrderStatus,
        requested_size: "5",
        filled_size: "0",
        average_price: null,
        fee_usdc: "0",
        received_at_ms: 1,
        reject_reason: runtimeContract.fillRejectReason.BAD_SIZE as FillRejectReason,
        reject_message: "order size is below the market minimum",
      },
      latency_ms: 0,
      portfolio: null,
    },
  };
}
