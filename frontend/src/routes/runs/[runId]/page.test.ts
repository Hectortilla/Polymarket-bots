import { DASHBOARD_COPY } from "$lib/charts/copy";
import { RUN_GUIDE_COPY } from "$lib/runs/runGuide";
import { STREAM_CONNECTION_STATE, type StreamConnectionState } from "$lib/runs/events";
import { ADD_NODE_LABEL } from "$lib/catalog/NodePalette.svelte";
import { VALUATION_STATUS } from "$lib/charts/contracts";
import { eventSummary } from "$lib/runs/eventSummary";
import { RUN_STATUS_PRESENTATION } from "$lib/runs/status";
import type { ActivitySeverity, LiveRunEvent } from "$lib/api/generated";
import { LIVE_EVENT_KIND } from "$lib/runs/eventKinds";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { BotDefinitionDescriptor, RunRead } from "$lib/api/generated";
import { TEST_GRAPH, TEST_GRAPH_CATALOG } from "$lib/catalog/nodeGraphTestFixtures";
import { BOT_DEFINITION_LABEL, SELECTION_MODE, WIDGET_KIND, WIDGET_SCHEMA_KEY } from "$lib/catalog/schema/contracts";
import { fieldLabel } from "$lib/catalog/schema/presentation";
import { launchFields } from "$lib/catalog/schema/fields";
import { BOT_BUILDER_COPY } from "$lib/bots/copy";
import { botPath } from "$lib/navigation";
import runtimeContract from "$lib/runtimeContract.fixture.json";
import { formatTime } from "$lib/time";
import { EVENT_KIND, INITIAL_EVENT_CURSOR, type PersistedDurableEvent } from "$lib/runs/durableEvents";
import { EVENT_VIEW } from "$lib/runs/eventViews";
import { RUN_STATUS } from "$lib/runs/status";
const mocks = vi.hoisted(() => ({
  listDefinitions: vi.fn(),
  loadRun: vi.fn(),
  loadOlderEvents: vi.fn(),
  stopRun: vi.fn(),
}));
vi.mock("$app/state", () => ({
  page: { params: { runId: "aaaaaaaa-0000-0000-0000-000000000001" } },
}));
vi.mock("$lib/runs/hydrate", () => ({
  loadAndContinueRunDetail: mocks.loadRun,
  loadRunEvents: mocks.loadOlderEvents,
  RunNotFoundError: class extends Error {},
}));
vi.mock("$lib/api/generated", () => ({
  listBotDefinitionsApiV1BotDefinitionsGet: mocks.listDefinitions,
  stopRunApiV1RunsRunIdStopPost: mocks.stopRun,
}));
import Page from "./+page.svelte";
import { loadedEventsLabel, RUN_DETAIL_COPY } from "./copy";
const RUN = {
  id: "aaaaaaaa-0000-0000-0000-000000000001",
  bot_id: "bbbbbbbb-0000-0000-0000-000000000001",
  definition_id: "node-based-bot",
  config: {
    name: "Historical graph run",
    stream_rules: [],
    data_trades_budget_per_10s: runtimeContract.config.maximumDataTradesBudget,
    max_order_size: "10",
    max_slippage_pct: "0.02",
    paper_latency_ms: 250,
    paper_latency_jitter_ms: 100,
    event_max_age_ms: 5000,
    paper_portfolio_usdc: "1000",
    graph: TEST_GRAPH,
  },
  status: RUN_STATUS.STOPPED,
  created_at: "2026-08-30T00:00:00Z",
} satisfies RunRead;
const GRAPHLESS_RUN = {
  ...RUN,
  config: {
    ...RUN.config,
    graph: null,
  },
} satisfies RunRead;
const GRAPH_DEFINITION = {
  definition_id: RUN.definition_id,
  display_name: "Node-based bot",
  description: "A graph-capable test definition.",
  label: BOT_DEFINITION_LABEL.STANDARD,
  market_selection: SELECTION_MODE.USER_CONFIGURED,
  wallet_selection: SELECTION_MODE.ABSENT,
  input_schema: {
    type: "object",
    properties: {
      name: { type: "string" },
      max_order_size: { type: "string" },
      market_slugs: { type: "array", title: "Markets", [WIDGET_SCHEMA_KEY]: WIDGET_KIND.MARKET_SLUGS },
    },
  },
  graph_catalog: TEST_GRAPH_CATALOG,
  starter_graph: TEST_GRAPH,
} satisfies BotDefinitionDescriptor;
class PassiveIntersectionObserver {
  observe(): void {}
  disconnect(): void {}
}
class FlowResizeObserver implements ResizeObserver {
  constructor(private readonly callback: ResizeObserverCallback) {}
  observe(target: Element): void {
    this.callback(
      [
        {
          target,
          contentRect: { width: 100, height: 50 },
        } as ResizeObserverEntry,
      ],
      this,
    );
  }
  disconnect(): void {}
  unobserve(): void {}
}
beforeEach(() => {
  vi.stubGlobal("IntersectionObserver", PassiveIntersectionObserver);
  vi.stubGlobal("ResizeObserver", FlowResizeObserver);
  vi.stubGlobal(
    "DOMMatrixReadOnly",
    class {
      readonly m22 = 1;
    },
  );
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(100);
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(50);
  mocks.listDefinitions.mockResolvedValue({ data: [GRAPH_DEFINITION] });
  mocks.loadRun.mockImplementation(async (_runId, hydrate) => {
    hydrate({
      dashboardPage: { events: [], nextBeforeEventId: null, streamCursor: INITIAL_EVENT_CURSOR },
      run: RUN,
      events: [],
      nextBeforeEventId: null,
    });
    return () => {};
  });
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
describe("run detail page", () => {
  it("maps snapshot values into the builder field order without graph JSON or editable settings", async () => {
    const markets = ["historical-market-one", "historical-market-two"];
    mocks.loadRun.mockImplementation(async (_runId, hydrate) => {
      hydrate({
        dashboardPage: { events: [], nextBeforeEventId: null, streamCursor: INITIAL_EVENT_CURSOR },
        run: {
          ...RUN,
          config: {
            ...RUN.config,
            max_order_size: "1.2300",
            stream_rules: [
              {
                relation: runtimeContract.streamRelation.INDEPENDENT,
                market_slugs: markets,
              },
            ],
          },
        },
        events: [],
        nextBeforeEventId: null,
      });
      return () => {};
    });
    render(Page);
    await fireEvent.click(await screen.findByRole("button", { name: RUN_DETAIL_COPY.SHOW_EVENTS }));
    await fireEvent.click(await screen.findByRole("tab", { name: BOT_BUILDER_COPY.CONFIGURATION }));
    const configuration = await screen.findByRole("region", { name: BOT_BUILDER_COPY.CONFIGURATION });
    expect([...configuration.querySelectorAll("dt")].map((field) => field.textContent)).toEqual(
      launchFields(GRAPH_DEFINITION).map(([name, field]) => fieldLabel(name, field)),
    );
    expect(configuration.textContent).toContain("1.2300");
    for (const market of markets) expect(configuration.textContent).toContain(market);
    expect(configuration.querySelectorAll("input, select, textarea, pre")).toHaveLength(0);
    expect(configuration.textContent).not.toContain(JSON.stringify(TEST_GRAPH));
    const graphSection = screen.getByRole("heading", { name: RUN_DETAIL_COPY.EXECUTED_GRAPH }).closest("section")!;
    expect(graphSection.compareDocumentPosition(configuration) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await fireEvent.click(screen.getByRole("tab", { name: RUN_DETAIL_COPY.LIVE_DATA }));
    expect(screen.getByRole("region", { name: "Timing" })).toBeTruthy();
  });

  it("shows stream reconnection until transport is connected again", async () => {
    let connectionState: (state: StreamConnectionState) => void = () => {};
    mocks.loadRun.mockImplementation(async (_runId, hydrate, _durable, _live, _open, onConnectionState) => {
      connectionState = onConnectionState;
      hydrate({
        dashboardPage: { events: [], nextBeforeEventId: null, streamCursor: INITIAL_EVENT_CURSOR },
        run: GRAPHLESS_RUN,
        events: [],
        nextBeforeEventId: null,
      });
      return () => {};
    });
    render(Page);
    await fireEvent.click(await screen.findByRole("button", { name: RUN_DETAIL_COPY.SHOW_EVENTS }));
    await screen.findByRole("heading", { name: GRAPHLESS_RUN.config.name });
    connectionState(STREAM_CONNECTION_STATE.RECONNECTING);
    expect(await screen.findByText(RUN_DETAIL_COPY.STREAM_RECONNECTING)).toBeTruthy();
    connectionState(STREAM_CONNECTION_STATE.CONNECTED);
    await waitFor(() => expect(screen.queryByText(RUN_DETAIL_COPY.STREAM_RECONNECTING)).toBeNull());
  });
  it("renders the saved-bot link and immutable historical graph snapshot", async () => {
    render(Page);
    await fireEvent.click(await screen.findByRole("tab", { name: BOT_BUILDER_COPY.CONFIGURATION }));
    const botLink = await screen.findByRole("link", {
      name: RUN_DETAIL_COPY.BOT_CONFIGURATION,
    });
    expect(botLink.getAttribute("href")).toBe(botPath(RUN.bot_id));
    expect(
      screen.getByRole("heading", {
        name: RUN_DETAIL_COPY.EXECUTED_GRAPH,
      }),
    ).toBeTruthy();
    const graphSection = screen
      .getByRole("heading", {
        name: RUN_DETAIL_COPY.EXECUTED_GRAPH,
      })
      .closest("section");
    expect(graphSection).not.toBeNull();
    const graphCanvas = await screen.findByRole("group", {
      name: RUN_DETAIL_COPY.EXECUTED_GRAPH,
    });
    expect(graphCanvas.hasAttribute("aria-disabled")).toBe(false);
    expect(screen.getByLabelText("on_book trigger node")).toBeTruthy();
    expect(graphSection?.querySelector("pre")).toBeNull();
    expect(screen.queryByRole("button", { name: ADD_NODE_LABEL })).toBeNull();
  });
  it("omits historical graph details for an ordinary run", async () => {
    mocks.loadRun.mockImplementation(async (_runId, hydrate) => {
      hydrate({
        dashboardPage: { events: [], nextBeforeEventId: null, streamCursor: INITIAL_EVENT_CURSOR },
        run: GRAPHLESS_RUN,
        events: [],
        nextBeforeEventId: null,
      });
      return () => {};
    });
    render(Page);
    await fireEvent.click(await screen.findByRole("tab", { name: BOT_BUILDER_COPY.CONFIGURATION }));
    await screen.findByRole("heading", { name: GRAPHLESS_RUN.config.name });
    expect(
      screen.queryByRole("heading", {
        name: new RegExp(RUN_DETAIL_COPY.EXECUTED_GRAPH),
      }),
    ).toBeNull();
    expect(mocks.listDefinitions).toHaveBeenCalledOnce();
  });
  it("reports when the executed graph catalog cannot be loaded", async () => {
    mocks.listDefinitions.mockRejectedValue(new Error("catalog unavailable"));
    render(Page);
    await fireEvent.click(await screen.findByRole("tab", { name: BOT_BUILDER_COPY.CONFIGURATION }));
    expect((await screen.findByRole("alert")).textContent).toContain(RUN_DETAIL_COPY.GRAPH_LOAD_ERROR);
    expect(screen.getByRole("region", { name: RUN_DETAIL_COPY.EXECUTED_GRAPH }).querySelector("pre")).toBeNull();
    await fireEvent.click(await screen.findByRole("tab", { name: BOT_BUILDER_COPY.CONFIGURATION }));
    const configuration = screen.getByRole("region", { name: BOT_BUILDER_COPY.CONFIGURATION });
    expect(configuration.textContent).toContain(RUN.config.max_order_size);
    expect(configuration.textContent).not.toContain(JSON.stringify(TEST_GRAPH));
    expect(screen.getByText(RUN_DETAIL_COPY.CONFIGURATION_LAYOUT_ERROR)).toBeTruthy();
  });
  it("attaches recorded failure detail to the failed lifecycle row", async () => {
    const failureDetail = "RuntimeError: run launch failed";
    const failedLifecycle: PersistedDurableEvent = {
      id: 1,
      kind: EVENT_KIND.runLifecycle,
      run_id: RUN.id,
      occurred_at: "2026-08-30T00:00:01Z",
      payload: { status: RUN_STATUS.FAILED },
    };
    mocks.loadRun.mockImplementation(async (_runId, hydrate) => {
      hydrate({
        dashboardPage: { events: [], nextBeforeEventId: null, streamCursor: INITIAL_EVENT_CURSOR },
        run: {
          ...GRAPHLESS_RUN,
          status: RUN_STATUS.FAILED,
          failure_detail: failureDetail,
        },
        events: [failedLifecycle],
        nextBeforeEventId: null,
      });
      return () => {};
    });
    render(Page);
    await fireEvent.click(await screen.findByRole("button", { name: RUN_DETAIL_COPY.SHOW_EVENTS }));
    const row = (await screen.findByText(eventSummary(failedLifecycle))).closest("tr");
    expect(row?.getAttribute("tabindex")).toBe("0");
    expect(row?.getAttribute("aria-describedby")).toBe(`event-failure-detail-${failedLifecycle.id}`);
    expect(row?.querySelector('[role="tooltip"]')?.textContent).toContain(failureDetail);
  });
});
const ACTIVE_RUN = { ...GRAPHLESS_RUN, status: RUN_STATUS.RUNNING };
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((success, failure) => {
    resolve = success;
    reject = failure;
  });
  return { promise, resolve, reject };
}
function lifecycleEvent(id: number, status: RunRead["status"]): PersistedDurableEvent {
  return {
    id,
    run_id: RUN.id,
    occurred_at: new Date(Date.parse(RUN.created_at) + id * 1000).toISOString(),
    kind: EVENT_KIND.runLifecycle,
    payload: { status },
  };
}
function chartSampleEvent(id: number): PersistedDurableEvent {
  return {
    id,
    run_id: RUN.id,
    occurred_at: RUN.created_at,
    kind: EVENT_KIND.chartSample,
    payload: {
      sampled_at_ms: id * 1000,
      markets: [],
      equity: { value: "1000", status: VALUATION_STATUS.fresh },
    },
  };
}
function hydrateActive(events: PersistedDurableEvent[] = [], cursor: number | null = null) {
  mocks.loadRun.mockImplementation(async (_id, hydrate) => {
    hydrate({
      dashboardPage: { events: [], nextBeforeEventId: null, streamCursor: INITIAL_EVENT_CURSOR },
      run: ACTIVE_RUN,
      events,
      nextBeforeEventId: cursor,
    });
    return vi.fn();
  });
}
const EVENT_PAGE_SIZE = runtimeContract.eventPagination.defaultLimit;
function progressPage(firstId: number, count = EVENT_PAGE_SIZE): PersistedDurableEvent[] {
  return Array.from({ length: count }, (_, index) => lifecycleEvent(firstId + index, RUN_STATUS.RUNNING));
}
function expectProgressWindow(firstId: number, count: number): void {
  const rows = [...document.querySelectorAll(".event-table tbody tr")];
  expect(rows).toHaveLength(count);
  expect(rows.map((row) => row.querySelector("td")?.textContent)).toEqual(
    progressPage(firstId, count).map((event) => formatTime(event.occurred_at)),
  );
}
describe("run detail interactions", () => {
  it("requests diagnostics from the backend and keeps the old feed if switching fails", async () => {
    hydrateActive([lifecycleEvent(1, RUN_STATUS.RUNNING)]);
    const oldClose = vi.fn();
    mocks.loadRun.mockImplementationOnce(async (_id, hydrate) => {
      hydrate({
        run: ACTIVE_RUN,
        events: [lifecycleEvent(1, RUN_STATUS.RUNNING)],
        nextBeforeEventId: null,
        dashboardPage: { events: [], nextBeforeEventId: null, streamCursor: INITIAL_EVENT_CURSOR },
      });
      return oldClose;
    });
    render(Page);
    await fireEvent.click(await screen.findByRole("button", { name: RUN_DETAIL_COPY.SHOW_EVENTS }));
    const diagnostics = screen.getByRole("checkbox", { name: RUN_DETAIL_COPY.SHOW_DIAGNOSTICS });
    mocks.loadRun.mockRejectedValueOnce(new Error("Unavailable"));
    await fireEvent.click(diagnostics);
    await screen.findByText(RUN_DETAIL_COPY.RUN_LOAD_ERROR);
    expect(oldClose).not.toHaveBeenCalled();
    expect(screen.getByText(loadedEventsLabel(1))).toBeTruthy();
    const activity = {
      ...lifecycleEvent(2, RUN_STATUS.RUNNING),
      kind: EVENT_KIND.botActivity,
      payload: { message: "[buy] Skipped: disabled", severity: runtimeContract.activitySeverity.INFO },
    };
    mocks.loadRun.mockImplementationOnce(async (_id, hydrate) => {
      hydrate({
        run: ACTIVE_RUN,
        events: [activity],
        nextBeforeEventId: null,
        dashboardPage: { events: [], nextBeforeEventId: null, streamCursor: INITIAL_EVENT_CURSOR },
      });
      return vi.fn();
    });
    await fireEvent.click(diagnostics);
    expect(await screen.findByText(activity.payload.message)).toBeTruthy();
    expect(mocks.loadRun.mock.calls.at(-1)?.[6]).toBe(EVENT_VIEW.DIAGNOSTICS);
    expect(oldClose).toHaveBeenCalledOnce();
    const oldDurable = mocks.loadRun.mock.calls[0][2];
    oldDurable(lifecycleEvent(3, RUN_STATUS.STOPPED));
    expect(screen.queryByText(eventSummary(lifecycleEvent(3, RUN_STATUS.STOPPED)))).toBeNull();
  });

  it("keeps dashboard replay outside the activity window and reloads evicted activity", async () => {
    hydrateActive(progressPage(1));
    render(Page);
    await fireEvent.click(await screen.findByRole("button", { name: RUN_DETAIL_COPY.SHOW_EVENTS }));
    await screen.findByText(loadedEventsLabel(EVENT_PAGE_SIZE));
    const durable = mocks.loadRun.mock.calls[0][2];
    const dashboardEvent = mocks.loadRun.mock.calls[0][7];
    dashboardEvent(chartSampleEvent(EVENT_PAGE_SIZE + 1));
    await waitFor(() => expectProgressWindow(1, EVENT_PAGE_SIZE));
    durable(lifecycleEvent(EVENT_PAGE_SIZE + 2, RUN_STATUS.RUNNING));
    await waitFor(() => expect(document.querySelectorAll(".event-table tbody tr")).toHaveLength(EVENT_PAGE_SIZE));
    mocks.loadOlderEvents.mockResolvedValue({
      events: progressPage(1, 1),
      nextBeforeEventId: null,
    });
    await fireEvent.click(screen.getByRole("button", { name: RUN_DETAIL_COPY.LOAD_EARLIER }));
    expect(mocks.loadOlderEvents).toHaveBeenCalledWith(RUN.id, EVENT_VIEW.ACTIVITY, 2);
    await waitFor(() => expect(document.querySelectorAll(".event-table tbody tr")).toHaveLength(EVENT_PAGE_SIZE + 1));
    expect(screen.queryByRole("button", { name: RUN_DETAIL_COPY.LOAD_EARLIER })).toBeNull();
  });
  it("lets an initially empty window fill before evicting events", async () => {
    hydrateActive();
    render(Page);
    await fireEvent.click(await screen.findByRole("button", { name: RUN_DETAIL_COPY.SHOW_EVENTS }));
    await screen.findByText(RUN_DETAIL_COPY.NO_PROGRESS_EVENTS);
    const durable = mocks.loadRun.mock.calls[0][2];
    progressPage(1).forEach(durable);
    await waitFor(() => expectProgressWindow(1, EVENT_PAGE_SIZE));
    expect(screen.queryByRole("button", { name: RUN_DETAIL_COPY.LOAD_EARLIER })).toBeNull();
    durable(lifecycleEvent(EVENT_PAGE_SIZE + 1, RUN_STATUS.RUNNING));
    await waitFor(() => expectProgressWindow(2, EVENT_PAGE_SIZE));
    expect(screen.getByRole("button", { name: RUN_DETAIL_COPY.LOAD_EARLIER })).toBeTruthy();
  });
  it.each([1, EVENT_PAGE_SIZE * 3])(
    "keeps two contiguous pages when %i events stream during an older-page request",
    async (streamedCount) => {
      const firstId = EVENT_PAGE_SIZE + 1;
      hydrateActive(progressPage(firstId), firstId);
      const request = deferred<{
        events: PersistedDurableEvent[];
        nextBeforeEventId: null;
      }>();
      mocks.loadOlderEvents.mockReturnValue(request.promise);
      render(Page);
      await fireEvent.click(await screen.findByRole("button", { name: RUN_DETAIL_COPY.SHOW_EVENTS }));
      const button = await screen.findByRole("button", { name: RUN_DETAIL_COPY.LOAD_EARLIER });
      const durable = mocks.loadRun.mock.calls[0][2];
      await fireEvent.click(button);
      progressPage(EVENT_PAGE_SIZE * 2 + 1, streamedCount).forEach(durable);
      request.resolve({ events: progressPage(1), nextBeforeEventId: null });
      await screen.findByRole("button", { name: RUN_DETAIL_COPY.LOAD_EARLIER });
      await waitFor(() => expectProgressWindow(streamedCount + 1, EVENT_PAGE_SIZE * 2));
      mocks.loadOlderEvents.mockResolvedValue({ events: [], nextBeforeEventId: null });
      await fireEvent.click(screen.getByRole("button", { name: RUN_DETAIL_COPY.LOAD_EARLIER }));
      expect(mocks.loadOlderEvents).toHaveBeenLastCalledWith(RUN.id, EVENT_VIEW.ACTIVITY, streamedCount + 1);
    },
  );
  it("releases reserved page capacity and preserves the advanced cursor after a failed fetch", async () => {
    const firstId = EVENT_PAGE_SIZE + 1;
    hydrateActive(progressPage(firstId), firstId);
    const request = deferred<never>();
    mocks.loadOlderEvents.mockReturnValue(request.promise);
    render(Page);
    await fireEvent.click(await screen.findByRole("button", { name: RUN_DETAIL_COPY.SHOW_EVENTS }));
    const button = await screen.findByRole("button", { name: RUN_DETAIL_COPY.LOAD_EARLIER });
    const durable = mocks.loadRun.mock.calls[0][2];
    await fireEvent.click(button);
    progressPage(EVENT_PAGE_SIZE * 2 + 1).forEach(durable);
    request.reject(new Error("unavailable"));
    await screen.findByText(RUN_DETAIL_COPY.LOAD_ERROR);
    expectProgressWindow(EVENT_PAGE_SIZE * 2 + 1, EVENT_PAGE_SIZE);
    durable(lifecycleEvent(EVENT_PAGE_SIZE * 3 + 1, RUN_STATUS.RUNNING));
    await waitFor(() => expectProgressWindow(EVENT_PAGE_SIZE * 2 + 2, EVENT_PAGE_SIZE));
    mocks.loadOlderEvents.mockResolvedValue({ events: [], nextBeforeEventId: null });
    await fireEvent.click(button);
    expect(mocks.loadOlderEvents).toHaveBeenLastCalledWith(RUN.id, EVENT_VIEW.ACTIVITY, EVENT_PAGE_SIZE * 2 + 2);
  });
  it("shows an empty progress state for a page containing only chart samples", async () => {
    hydrateActive([], 2);
    render(Page);
    await fireEvent.click(await screen.findByRole("button", { name: RUN_DETAIL_COPY.SHOW_EVENTS }));
    expect(await screen.findByText(RUN_DETAIL_COPY.NO_PROGRESS_EVENTS)).toBeTruthy();
    expect(screen.getByText(loadedEventsLabel(0))).toBeTruthy();
    expect(screen.queryByText(EVENT_KIND.chartSample)).toBeNull();
    expect(screen.getByRole("button", { name: RUN_DETAIL_COPY.LOAD_EARLIER })).toBeTruthy();
  });
  it("shows a pending stop request and applies the returned status", async () => {
    hydrateActive();
    const request = deferred<{
      data: RunRead;
    }>();
    mocks.stopRun.mockReturnValue(request.promise);
    render(Page);
    await fireEvent.click(await screen.findByRole("button", { name: RUN_DETAIL_COPY.SHOW_EVENTS }));
    const stop = await screen.findByRole("button", {
      name: RUN_STATUS_PRESENTATION[RUN_STATUS.RUNNING].stopLabel!,
    });
    await fireEvent.click(stop);
    expect(mocks.stopRun).toHaveBeenCalledWith({ path: { run_id: RUN.id }, throwOnError: true });
    expect(stop.hasAttribute("disabled")).toBe(true);
    expect(stop.getAttribute("aria-busy")).toBe("true");
    expect(stop.textContent).toContain(RUN_DETAIL_COPY.SENDING);
    request.resolve({ data: { ...ACTIVE_RUN, status: RUN_STATUS.STOP_REQUESTED } });
    expect(
      (
        await screen.findByRole("button", {
          name: RUN_STATUS_PRESENTATION[RUN_STATUS.STOP_REQUESTED].stopLabel!,
        })
      ).hasAttribute("disabled"),
    ).toBe(true);
  });
  it("clears busy state after a failed stop so the request can be retried", async () => {
    hydrateActive();
    mocks.stopRun.mockRejectedValue(new Error("unavailable"));
    render(Page);
    await fireEvent.click(await screen.findByRole("button", { name: RUN_DETAIL_COPY.SHOW_EVENTS }));
    const stop = await screen.findByRole("button", {
      name: RUN_STATUS_PRESENTATION[RUN_STATUS.RUNNING].stopLabel!,
    });
    await fireEvent.click(stop);
    expect(await screen.findByText(RUN_DETAIL_COPY.STOP_ERROR)).toBeTruthy();
    expect(stop.hasAttribute("disabled")).toBe(false);
    expect(stop.getAttribute("aria-busy")).not.toBe("true");
    expect(stop.textContent).toContain(RUN_STATUS_PRESENTATION[RUN_STATUS.RUNNING].stopLabel!);
  });
  it("applies durable and live stream callbacks and closes the stream on unmount", async () => {
    let durable!: (event: PersistedDurableEvent) => void;
    let live!: (event: LiveRunEvent) => void;
    const close = vi.fn();
    mocks.loadRun.mockImplementation(async (_id, hydrate, onDurable, onLive) => {
      durable = onDurable;
      live = onLive;
      hydrate({
        dashboardPage: { events: [], nextBeforeEventId: null, streamCursor: INITIAL_EVENT_CURSOR },
        run: ACTIVE_RUN,
        events: [],
        nextBeforeEventId: null,
      });
      return close;
    });
    // Frames run asynchronously so consecutive health events exercise browser ordering.
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      return window.setTimeout(() => callback(0), 0);
    });
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    const view = render(Page);
    await fireEvent.click(await screen.findByRole("button", { name: RUN_DETAIL_COPY.SHOW_EVENTS }));
    await screen.findByRole("button", {
      name: RUN_STATUS_PRESENTATION[RUN_STATUS.RUNNING].stopLabel!,
    });
    live({
      kind: LIVE_EVENT_KIND.streamHealth,
      run_id: RUN.id,
      occurred_at: RUN.created_at,
      payload: {
        queue_depth: 17,
        peak_queue_depth: 23,
        book_dispatch_lag_ms: 8,
        book_stale: true,
        book_received_count: 41,
        book_coalesced_count: 5,
      },
    });
    expect(await screen.findByText(RUN_GUIDE_COPY.BOOK_UNAVAILABLE)).toBeTruthy();
    expect(screen.queryByText("17")).toBeNull();

    live({
      kind: LIVE_EVENT_KIND.streamHealth,
      run_id: RUN.id,
      occurred_at: RUN.created_at,
      payload: {
        queue_depth: 0,
        peak_queue_depth: 23,
        book_dispatch_lag_ms: 8,
        book_stale: false,
        book_received_count: 42,
        book_coalesced_count: 5,
      },
    });
    expect(await screen.findByText(RUN_GUIDE_COPY.BOOK_REPORTED)).toBeTruthy();
    mocks.loadRun.mock.calls[0][7](chartSampleEvent(2));
    durable(lifecycleEvent(1, RUN_STATUS.STOPPED));
    expect(await screen.findByText(eventSummary(lifecycleEvent(1, RUN_STATUS.STOPPED)))).toBeTruthy();
    expect(screen.queryByText(EVENT_KIND.chartSample)).toBeNull();
    expect(screen.getByText(loadedEventsLabel(1))).toBeTruthy();
    expect(
      screen.queryByRole("button", {
        name: RUN_STATUS_PRESENTATION[RUN_STATUS.RUNNING].stopLabel!,
      }),
    ).toBeNull();
    view.unmount();
    expect(close).toHaveBeenCalledOnce();
  });
  it("keeps the older-event cursor for retries and merges a successful page", async () => {
    hydrateActive([lifecycleEvent(2, RUN_STATUS.RUNNING)], 7);
    mocks.loadOlderEvents.mockRejectedValueOnce(new Error("unavailable"));
    render(Page);
    await fireEvent.click(await screen.findByRole("button", { name: RUN_DETAIL_COPY.SHOW_EVENTS }));
    const button = await screen.findByRole("button", { name: RUN_DETAIL_COPY.LOAD_EARLIER });
    await fireEvent.click(button);
    expect(await screen.findByText(RUN_DETAIL_COPY.LOAD_ERROR)).toBeTruthy();
    expect(button.hasAttribute("disabled")).toBe(false);
    const request = deferred<{
      events: PersistedDurableEvent[];
      nextBeforeEventId: number | null;
    }>();
    mocks.loadOlderEvents.mockReturnValue(request.promise);
    await fireEvent.click(button);
    expect(mocks.loadOlderEvents).toHaveBeenLastCalledWith(RUN.id, EVENT_VIEW.ACTIVITY, 7);
    expect(button.hasAttribute("disabled")).toBe(true);
    expect(button.getAttribute("aria-busy")).toBe("true");
    expect(button.textContent).toContain(RUN_DETAIL_COPY.LOADING);
    await fireEvent.click(button);
    expect(mocks.loadOlderEvents).toHaveBeenCalledTimes(2);
    request.resolve({
      events: [lifecycleEvent(1, RUN_STATUS.QUEUED)],
      nextBeforeEventId: null,
    });
    await waitFor(() => expect(screen.queryByRole("button", { name: RUN_DETAIL_COPY.LOAD_EARLIER })).toBeNull());
    expect(await screen.findByText(loadedEventsLabel(2))).toBeTruthy();
    const rows = [...document.querySelectorAll(".event-table tbody tr")];
    expect(rows).toHaveLength(2);
    expect(screen.queryByText(EVENT_KIND.chartSample)).toBeNull();
    expect(rows[0].textContent).toContain(eventSummary(lifecycleEvent(1, RUN_STATUS.QUEUED)));
    expect(rows[1].textContent).toContain(eventSummary(lifecycleEvent(2, RUN_STATUS.RUNNING)));
  });
});
it("keeps the historical graph visible after its bot is deleted and removes the configuration link", async () => {
  mocks.loadRun.mockImplementation(async (_runId, hydrate) => {
    hydrate({
      dashboardPage: { events: [], nextBeforeEventId: null, streamCursor: INITIAL_EVENT_CURSOR },
      run: { ...RUN, bot_deleted: true },
      events: [],
      nextBeforeEventId: null,
    });
    return () => {};
  });
  render(Page);
  expect(await screen.findByRole("heading", { name: RUN.config.name })).toBeTruthy();
  expect(await screen.findByText(RUN_DETAIL_COPY.BOT_DELETED)).toBeTruthy();
  expect(screen.queryByRole("link", { name: RUN_DETAIL_COPY.BOT_CONFIGURATION })).toBeNull();
  await fireEvent.click(await screen.findByRole("tab", { name: BOT_BUILDER_COPY.CONFIGURATION }));
  expect(screen.getByText(RUN_DETAIL_COPY.EXECUTED_GRAPH)).toBeTruthy();
});

it("separates live data from configuration and preserves disclosures across tabs", async () => {
  render(Page);
  const liveTab = await screen.findByRole("tab", { name: RUN_DETAIL_COPY.LIVE_DATA });
  const setupTab = screen.getByRole("tab", { name: BOT_BUILDER_COPY.CONFIGURATION });
  expect(liveTab.getAttribute("aria-selected")).toBe("true");
  expect(screen.getAllByRole("tabpanel")).toHaveLength(1);
  expect(screen.queryByRole("region", { name: RUN_DETAIL_COPY.EXECUTED_GRAPH })).toBeNull();
  expect(screen.getAllByRole("heading", { level: 2 }).map((heading) => heading.textContent?.trim())).toEqual([
    DASHBOARD_COPY.EQUITY,
    DASHBOARD_COPY.MARKET_PRICES,
    "Timing",
  ]);
  const eventsToggle = screen.getByRole("button", { name: RUN_DETAIL_COPY.SHOW_EVENTS });
  expect(eventsToggle.getAttribute("aria-expanded")).toBe("false");
  await fireEvent.click(eventsToggle);
  await fireEvent.click(setupTab);
  expect(setupTab.getAttribute("aria-selected")).toBe("true");
  expect(screen.queryByRole("region", { name: DASHBOARD_COPY.ARIA_LABEL })).toBeNull();
  expect(screen.getAllByRole("heading", { level: 2 }).map((heading) => heading.textContent?.trim())).toEqual([
    RUN_DETAIL_COPY.EXECUTED_GRAPH,
    BOT_BUILDER_COPY.CONFIGURATION,
  ]);
  const configurationToggle = await screen.findByRole("button", { name: BOT_BUILDER_COPY.CONFIGURATION });
  expect(configurationToggle.getAttribute("aria-expanded")).toBe("true");
  expect(screen.getByRole("region", { name: BOT_BUILDER_COPY.CONFIGURATION }).querySelector("dt")).toBeTruthy();
  await fireEvent.click(configurationToggle);
  await fireEvent.click(liveTab);
  expect(screen.getByRole("button", { name: RUN_DETAIL_COPY.HIDE_EVENTS }).getAttribute("aria-expanded")).toBe("true");
  await fireEvent.click(setupTab);
  expect(configurationToggle.getAttribute("aria-expanded")).toBe("false");
  const graphToggle = screen.getByRole("button", { name: RUN_DETAIL_COPY.EXECUTED_GRAPH });
  await fireEvent.click(graphToggle);
  expect(screen.queryByRole("group", { name: RUN_DETAIL_COPY.EXECUTED_GRAPH })).toBeNull();
  await fireEvent.click(graphToggle);
  expect(await screen.findByRole("group", { name: RUN_DETAIL_COPY.EXECUTED_GRAPH })).toBeTruthy();
});

it("supports arrow, Home and End navigation with one tab stop", async () => {
  render(Page);
  const liveTab = await screen.findByRole("tab", { name: RUN_DETAIL_COPY.LIVE_DATA });
  const setupTab = screen.getByRole("tab", { name: BOT_BUILDER_COPY.CONFIGURATION });
  for (const [origin, key, target] of [
    [liveTab, "ArrowRight", setupTab],
    [setupTab, "ArrowRight", liveTab],
    [liveTab, "ArrowLeft", setupTab],
    [setupTab, "Home", liveTab],
    [liveTab, "End", setupTab],
  ] as const) {
    await fireEvent.keyDown(origin, { key });
    expect(document.activeElement).toBe(target);
    expect(target.getAttribute("aria-selected")).toBe("true");
    expect(screen.getAllByRole("tab").filter((tab) => tab.tabIndex === 0)).toEqual([target]);
    expect(screen.getByRole("tabpanel").getAttribute("aria-labelledby")).toBe(target.id);
  }
});

it("continues ingesting run events while viewing configuration", async () => {
  hydrateActive();
  render(Page);
  await fireEvent.click(await screen.findByRole("tab", { name: BOT_BUILDER_COPY.CONFIGURATION }));
  const durable = mocks.loadRun.mock.calls[0][2];
  durable(lifecycleEvent(1, RUN_STATUS.STOPPED));
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: RUN_STATUS_PRESENTATION[RUN_STATUS.RUNNING].stopLabel! })).toBeNull(),
  );
  await fireEvent.click(screen.getByRole("tab", { name: RUN_DETAIL_COPY.LIVE_DATA }));
  await fireEvent.click(screen.getByRole("button", { name: RUN_DETAIL_COPY.SHOW_EVENTS }));
  expect(screen.getByText(eventSummary(lifecycleEvent(1, RUN_STATUS.STOPPED)))).toBeTruthy();
  expect(mocks.loadRun).toHaveBeenCalledOnce();
});

it.each([false, true])("loads earlier chart data and allows retry after failure=%s", async (failFirst) => {
  mocks.loadRun.mockImplementation(async (_id, hydrate) => {
    hydrate({
      run: RUN,
      events: [],
      nextBeforeEventId: null,
      dashboardPage: { events: [], nextBeforeEventId: 10, streamCursor: 10 },
    });
    return () => {};
  });
  if (failFirst) mocks.loadOlderEvents.mockRejectedValueOnce(new Error("offline"));
  mocks.loadOlderEvents.mockResolvedValueOnce({ events: [], nextBeforeEventId: 5, streamCursor: 10 });
  mocks.loadOlderEvents.mockResolvedValueOnce({ events: [], nextBeforeEventId: null, streamCursor: 10 });
  render(Page);
  await fireEvent.click(await screen.findByRole("button", { name: RUN_DETAIL_COPY.LOAD_EARLIER_DASHBOARD }));
  if (failFirst) {
    expect(await screen.findByText(RUN_DETAIL_COPY.LOAD_ERROR)).toBeTruthy();
    await fireEvent.click(await screen.findByRole("button", { name: RUN_DETAIL_COPY.LOAD_EARLIER_DASHBOARD }));
  }
  await waitFor(() => expect(mocks.loadOlderEvents).toHaveBeenCalledWith(RUN.id, EVENT_VIEW.DASHBOARD, 10));
  await fireEvent.click(await screen.findByRole("button", { name: RUN_DETAIL_COPY.LOAD_EARLIER_DASHBOARD }));
  await waitFor(() => expect(mocks.loadOlderEvents).toHaveBeenLastCalledWith(RUN.id, EVENT_VIEW.DASHBOARD, 5));
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: RUN_DETAIL_COPY.LOAD_EARLIER_DASHBOARD })).toBeNull(),
  );
});
