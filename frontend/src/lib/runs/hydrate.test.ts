import { beforeEach, describe, expect, it, vi } from "vitest";
import type { RunRead } from "$lib/api/generated";
import type { PersistedDurableEvent } from "./durableEvents";
import { readRunApiV1RunsRunIdGet, readRunEventsApiV1RunsRunIdEventsGet } from "$lib/api/generated";
import { GRAPH_NODE_TYPE } from "$lib/catalog/graphContracts";
import { ON_START_TRIGGER } from "$lib/catalog/nodeGraphTestFixtures";
import runtimeContract from "$lib/runtimeContract.fixture.json";
import { EVENT_VIEW } from "./eventViews";
import { EVENT_KIND } from "./durableEvents";
import { hydrateRunDetail, RunNotFoundError, loadAndContinueRunDetail, loadRunEvents } from "./hydrate";
import { HTTP_STATUS } from "$lib/api/http";
import { RUN_STATUS } from "./status";
vi.mock("$lib/api/generated", async (importOriginal) => {
  const original = await importOriginal<typeof import("$lib/api/generated")>();
  return {
    ...original,
    readRunApiV1RunsRunIdGet: vi.fn(),
    readRunEventsApiV1RunsRunIdEventsGet: vi.fn(),
  };
});
const RUN: RunRead = {
  id: "aaaaaaaa-0000-0000-0000-000000000001",
  bot_id: "bbbbbbbb-0000-0000-0000-000000000001",
  definition_id: "test-definition",
  config: {
    name: "Hydrated run",
    stream_rules: [],
    data_trades_budget_per_10s: runtimeContract.config.maximumDataTradesBudget,
    max_order_size: "10",
    max_slippage_pct: "0.02",
    paper_latency_ms: 250,
    paper_latency_jitter_ms: 100,
    event_max_age_ms: 5000,
    paper_portfolio_usdc: "1000",
    graph: {
      nodes: [
        {
          id: "on-start",
          type: GRAPH_NODE_TYPE.trigger,
          position: { x: 0, y: 0 },
          data: { hook_name: ON_START_TRIGGER.hook_name },
        },
      ],
      edges: [],
    },
  },
  status: RUN_STATUS.RUNNING,
  created_at: "2026-08-23T00:00:00Z",
};
const EVENT: PersistedDurableEvent = {
  id: 7,
  kind: EVENT_KIND.runLifecycle,
  run_id: RUN.id,
  occurred_at: "2026-08-23T00:00:01Z",
  payload: { status: RUN_STATUS.RUNNING },
};
describe("run reload", () => {
  beforeEach(() => vi.clearAllMocks());
  it("hydrates ordinary HTTP state before opening SSE from the durable cursor", async () => {
    vi.mocked(readRunApiV1RunsRunIdGet).mockResolvedValue({ data: RUN } as never);
    vi.mocked(readRunEventsApiV1RunsRunIdEventsGet).mockResolvedValue({
      data: { events: [EVENT], stream_cursor: 7, next_before_event_id: 7 },
    } as never);
    const calls: string[] = [];
    const openStream = vi.fn(() => {
      calls.push("stream");
      return () => {};
    });
    await loadAndContinueRunDetail(
      RUN.id.toUpperCase(),
      (hydration) => {
        calls.push("hydrated");
        expect(hydration.run).toEqual(RUN);
        expect(hydration.events).toEqual([EVENT]);
        expect(hydration.nextBeforeEventId).toBe(7);
      },
      vi.fn(),
      vi.fn(),
      openStream,
    );
    expect(calls).toEqual(["hydrated", "stream"]);
    expect(openStream).toHaveBeenCalledWith(
      RUN.id,
      7,
      expect.any(Function),
      expect.any(Function),
      undefined,
      expect.objectContaining({ view: EVENT_VIEW.ACTIVITY }),
    );
    expect(readRunEventsApiV1RunsRunIdEventsGet).toHaveBeenCalledWith({
      path: { run_id: RUN.id },
      query: { view: EVENT_VIEW.ACTIVITY },
      throwOnError: true,
    });
  });
  it("does not open SSE when the hydrated run is terminal", async () => {
    vi.mocked(readRunApiV1RunsRunIdGet).mockResolvedValue({
      data: { ...RUN, status: RUN_STATUS.STOPPED },
    } as never);
    vi.mocked(readRunEventsApiV1RunsRunIdEventsGet).mockResolvedValue({
      data: { events: [EVENT], stream_cursor: 7, next_before_event_id: null },
    } as never);
    const openStream = vi.fn();
    const close = await loadAndContinueRunDetail(RUN.id, vi.fn(), vi.fn(), vi.fn(), openStream);
    expect(openStream).not.toHaveBeenCalled();
    expect(close()).toBeUndefined();
  });
  it("does not open SSE past a terminal event committed during hydration", async () => {
    vi.mocked(readRunApiV1RunsRunIdGet)
      .mockResolvedValueOnce({ data: RUN } as never)
      .mockResolvedValueOnce({ data: { ...RUN, status: RUN_STATUS.STOPPED } } as never);
    vi.mocked(readRunEventsApiV1RunsRunIdEventsGet).mockResolvedValue({
      data: {
        events: [{ ...EVENT, payload: { status: RUN_STATUS.STOPPED } }],
        stream_cursor: 7,
        next_before_event_id: null,
      },
    } as never);
    const openStream = vi.fn();
    const hydrated = vi.fn();
    await loadAndContinueRunDetail(RUN.id, hydrated, vi.fn(), vi.fn(), openStream);
    expect(openStream).not.toHaveBeenCalled();
    expect(hydrated.mock.calls[0][0].run.status).toBe(RUN_STATUS.STOPPED);
  });
  it("refreshes a queued snapshot when the running event is already in the SSE cursor", async () => {
    vi.mocked(readRunApiV1RunsRunIdGet)
      .mockResolvedValueOnce({ data: { ...RUN, status: RUN_STATUS.QUEUED } } as never)
      .mockResolvedValueOnce({ data: RUN } as never);
    vi.mocked(readRunEventsApiV1RunsRunIdEventsGet).mockResolvedValue({
      data: { events: [EVENT], stream_cursor: 7, next_before_event_id: null },
    } as never);
    const hydrated = vi.fn();
    const openStream = vi.fn(() => () => {});
    await loadAndContinueRunDetail(RUN.id, hydrated, vi.fn(), vi.fn(), openStream);
    expect(hydrated.mock.calls[0][0].run.status).toBe(RUN_STATUS.RUNNING);
    expect(openStream).toHaveBeenCalledWith(
      RUN.id,
      EVENT.id,
      expect.any(Function),
      expect.any(Function),
      undefined,
      expect.objectContaining({ view: EVENT_VIEW.ACTIVITY }),
    );
  });
  it("loads only the older page selected by the server cursor", async () => {
    const olderEvent = { ...EVENT, id: 3 };
    vi.mocked(readRunEventsApiV1RunsRunIdEventsGet).mockResolvedValue({
      data: { events: [olderEvent], stream_cursor: 7, next_before_event_id: null },
    } as never);
    const page = await loadRunEvents(RUN.id, EVENT_VIEW.ACTIVITY, 7);
    expect(page).toEqual({ events: [olderEvent], nextBeforeEventId: null, streamCursor: 7 });
    expect(readRunEventsApiV1RunsRunIdEventsGet).toHaveBeenCalledWith({
      path: { run_id: RUN.id },
      query: { before_event_id: 7, view: EVENT_VIEW.ACTIVITY },
      throwOnError: true,
    });
    vi.mocked(readRunEventsApiV1RunsRunIdEventsGet).mockResolvedValue({
      data: { events: [olderEvent], stream_cursor: 7, next_before_event_id: 4 },
    } as never);
    await expect(loadRunEvents(RUN.id, EVENT_VIEW.ACTIVITY, 7)).rejects.toThrow("Invalid run event page cursor");
  });
});
it("keeps run denial distinct from infrastructure failure", async () => {
  vi.mocked(readRunApiV1RunsRunIdGet).mockResolvedValue({ response: { status: HTTP_STATUS.NOT_FOUND } } as never);
  await expect(hydrateRunDetail(RUN.id)).rejects.toBeInstanceOf(RunNotFoundError);
  vi.mocked(readRunApiV1RunsRunIdGet).mockResolvedValue({
    response: { status: HTTP_STATUS.SERVICE_UNAVAILABLE },
  } as never);
  await expect(hydrateRunDetail(RUN.id)).rejects.toThrow("Run unavailable");
});

it("uses snapshot watermarks and suppresses replay already present in each independent page", async () => {
  vi.mocked(readRunApiV1RunsRunIdGet).mockResolvedValue({ data: RUN } as never);
  vi.mocked(readRunEventsApiV1RunsRunIdEventsGet)
    .mockResolvedValueOnce({ data: { events: [EVENT], next_before_event_id: null, stream_cursor: 10 } } as never)
    .mockResolvedValueOnce({ data: { events: [], next_before_event_id: null, stream_cursor: 12 } } as never);
  const onActivity = vi.fn();
  const onDashboard = vi.fn();
  const openStream = vi.fn(() => () => {});
  await loadAndContinueRunDetail(
    RUN.id,
    vi.fn(),
    onActivity,
    vi.fn(),
    openStream,
    undefined,
    EVENT_VIEW.DIAGNOSTICS,
    onDashboard,
  );
  const call = openStream.mock.calls[0] as unknown as Parameters<import("./events").EventStreamOpener>;
  expect(call[1]).toBe(10);
  expect(call[5]?.view).toBe(EVENT_VIEW.DIAGNOSTICS);
  call[2]({ ...EVENT, id: 10 });
  call[2]({ ...EVENT, id: 11 });
  call[5]?.onDashboardEvent({ ...EVENT, id: 12 });
  call[5]?.onDashboardEvent({ ...EVENT, id: 13 });
  expect(onActivity.mock.calls.map(([event]) => event.id)).toEqual([11]);
  expect(onDashboard.mock.calls.map(([event]) => event.id)).toEqual([13]);
});
