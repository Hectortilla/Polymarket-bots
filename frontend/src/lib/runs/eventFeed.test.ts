import { RUN_EVENT_COPY } from "./copy";
import { describe, expect, it } from "vitest";
import { EVENT_KIND, type PersistedDurableEvent } from "./durableEvents";
import { eventLabel } from "./eventFeed";
import { eventSummary } from "./eventSummary";

const BASE_EVENT = { id: 1, run_id: "run", occurred_at: "2026-09-11T00:00:00Z" };

describe("event presentation", () => {
  it("labels settlements and reports zero payouts for losses", () => {
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
    expect(eventLabel(event)).toBe(RUN_EVENT_COPY.SETTLEMENT);
    event.payload.settlement.paper_positions.push({
      owner: "paper",
      token_id: "no",
      size: "5",
      payout_per_token: "0",
      cash_payout_usdc: "0",
    });

    expect(eventSummary(event)).toBe("example-market · Yes won · Payout 0 USDC");
  });
});
