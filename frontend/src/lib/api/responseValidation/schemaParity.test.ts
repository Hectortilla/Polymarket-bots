import document from "../../../../../backend/contracts/openapi/control-plane.json";
import catalogContract from "$lib/catalog/catalogContract.fixture.json";
import Ajv from "ajv";
import { describe, expect, it } from "vitest";
import runtimeContract from "$lib/runtimeContract.fixture.json";
import { isActivityPayload, isLifecyclePayload } from "$lib/runs/eventPayloads/lifecycle";
import { isWalletTimelinePayload } from "$lib/runs/dashboardPayloads";
import { isEventPage } from "./events";
import { isGraphValueRead } from "./graph/preview";

const ajv = new Ajv({ strict: false, validateFormats: false });

function parity(
  model: string,
  guard: (value: Record<string, unknown>) => boolean,
  value: Record<string, unknown>,
): void {
  const validate = ajv.compile({ components: document.components, $ref: `#/components/schemas/${model}` });
  expect(guard(value)).toBe(validate(value));
}

describe("backend response schema parity", () => {
  it.each([{}, { unexpected: true }])("matches closed activity fields: %j", (extra) => {
    parity("BotActivityPayload", isActivityPayload, {
      message: "Watching",
      severity: runtimeContract.activitySeverity.INFO,
      ...extra,
    });
  });

  it.each([{}, { extra: null }, { name: "partial started payload" }])("matches lifecycle variants: %j", (extra) => {
    parity("RunStatusPayload", isLifecyclePayload, { status: runtimeContract.runStatus.values.RUNNING, ...extra });
  });

  it.each([
    {},
    { input_handle_id: null, message: null },
    { input_handle_id: "field", message: "detail" },
    { input_handle_id: 1 },
    { message: {} },
    { extra: true },
  ])("matches optional graph read fields: %j", (extra) => {
    parity("GraphValueRead", isGraphValueRead, {
      status: catalogContract.graphValueStatus.AVAILABLE,
      value: "text",
      ...extra,
    });
  });

  it.each([{}, { stream_cursor: -1 }, { stream_cursor: "0" }, { extra: true }])(
    "matches generic page cursor fields: %j",
    (extra) => {
      parity("RunEventPage", isEventPage, {
        events: [],
        next_before_event_id: null,
        stream_cursor: runtimeContract.durableEventIds.firstCursor,
        ...extra,
      });
    },
  );

  it.each([undefined, null, "transaction", 1, {}])("matches wallet transaction-hash type: %j", (transaction_hash) => {
    const wallet = "0x" + "a".repeat(40);
    const trade = {
      wallet,
      condition_id: "condition",
      token_id: "token",
      side: runtimeContract.side.BUY,
      size: "2",
      price: "0.5",
      source_id: "source",
      trade_timestamp_ms: 1,
      observed_at_ms: 1,
      kind: runtimeContract.walletTradeKind.TRADE,
      transaction_hash,
    };
    const payload = {
      trade,
      outcome: { accepted: true, skip_reason: null },
      point: {
        source_key: `${wallet}${runtimeContract.walletSourceKeySeparator}source`,
        wallet,
        trade_timestamp_ms: 1,
        side: trade.side,
        notional: "1",
        market_label: "token",
        accepted: true,
      },
    };
    parity("WalletTimelinePayload", isWalletTimelinePayload, payload);
  });
});
