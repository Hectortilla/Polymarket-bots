import { ADD_NODE_LABEL } from '$lib/catalog/NodePalette.svelte';
import { eventSummary } from '$lib/runs/eventSummary';
import { RUN_STATUS_PRESENTATION } from '$lib/runs/status';
import { LIVE_EVENT_KIND, type LiveRunEvent } from '$lib/runs/events';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { BotDefinitionDescriptor, RunRead } from '$lib/api/generated';
import { TEST_GRAPH, TEST_GRAPH_CATALOG } from '$lib/catalog/nodeGraphTestFixtures';
import { BOT_DEFINITION_LABEL, SELECTION_MODE } from '$lib/catalog/schema';
import { botPath } from '$lib/navigation';
import runtimeContract from '$lib/runtimeContract.fixture.json';
import { EVENT_KIND, type PersistedDurableEvent } from '$lib/runs/durableEvents';
import { RUN_STATUS } from '$lib/runs/status';

const mocks = vi.hoisted(() => ({
  listDefinitions: vi.fn(),
  loadRun: vi.fn(),
  loadOlderEvents: vi.fn(),
  stopRun: vi.fn(),
}));

vi.mock('$app/state', () => ({
  page: { params: { runId: 'aaaaaaaa-0000-0000-0000-000000000001' } },
}));
vi.mock('$lib/runs/hydrate', () => ({
  loadAndContinueRunDetail: mocks.loadRun,
  loadOlderRunEvents: mocks.loadOlderEvents,
}));
vi.mock('$lib/api/generated', () => ({
  listBotDefinitionsApiV1BotDefinitionsGet: mocks.listDefinitions,
  stopRunApiV1RunsRunIdStopPost: mocks.stopRun,
}));

import Page from './+page.svelte';
import { loadedEventsLabel, RUN_DETAIL_COPY, executedRunGraphRevisionLabel } from './copy';

const RUN = {
  id: 'aaaaaaaa-0000-0000-0000-000000000001',
  bot_id: 'bbbbbbbb-0000-0000-0000-000000000001',
  definition_id: 'node-based-bot',
  bot_graph_revision_id: 'cccccccc-0000-0000-0000-000000000001',
  graph_revision: 3,
  graph: TEST_GRAPH,
  config: {
    name: 'Historical graph run',
    stream_rules: [],
    data_trades_budget_per_10s: runtimeContract.config.maximumDataTradesBudget,
    max_order_size: '10',
    max_slippage_pct: '0.02',
    paper_latency_ms: 250,
    paper_latency_jitter_ms: 100,
    event_max_age_ms: 5000,
    paper_portfolio_usdc: '1000',
  },
  status: RUN_STATUS.STOPPED,
  created_at: '2026-08-30T00:00:00Z',
} satisfies RunRead;

const GRAPHLESS_RUN = {
  ...RUN,
  bot_graph_revision_id: null,
  graph_revision: null,
  graph: null,
} satisfies RunRead;

const GRAPH_DEFINITION = {
  definition_id: RUN.definition_id,
  display_name: 'Node-based bot',
  description: 'A graph-capable test definition.',
  label: BOT_DEFINITION_LABEL.STANDARD,
  market_selection: SELECTION_MODE.USER_CONFIGURED,
  wallet_selection: SELECTION_MODE.ABSENT,
  input_schema: {},
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
  vi.stubGlobal('IntersectionObserver', PassiveIntersectionObserver);
  vi.stubGlobal('ResizeObserver', FlowResizeObserver);
  vi.stubGlobal(
    'DOMMatrixReadOnly',
    class {
      readonly m22 = 1;
    },
  );
  vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(100);
  vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(50);
  mocks.listDefinitions.mockResolvedValue({ data: [GRAPH_DEFINITION] });
  mocks.loadRun.mockImplementation(async (_runId, hydrate) => {
    hydrate({ run: RUN, events: [], nextBeforeEventId: null });
    return () => {};
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('run detail page', () => {
  it('renders the saved-bot link and immutable historical graph snapshot', async () => {
    render(Page);

    const botLink = await screen.findByRole('link', {
      name: RUN_DETAIL_COPY.BOT_CONFIGURATION,
    });
    expect(botLink.getAttribute('href')).toBe(botPath(RUN.bot_id));
    expect(
      screen.getByRole('heading', {
        name: executedRunGraphRevisionLabel(RUN.graph_revision),
      }),
    ).toBeTruthy();

    const graphSection = screen
      .getByRole('heading', {
        name: executedRunGraphRevisionLabel(RUN.graph_revision),
      })
      .closest('section');
    expect(graphSection).not.toBeNull();
    const graphCanvas = await screen.findByRole('group', {
      name: executedRunGraphRevisionLabel(RUN.graph_revision),
    });
    expect(graphCanvas.getAttribute('aria-disabled')).toBe('true');
    expect(screen.getByLabelText('on_book trigger node')).toBeTruthy();
    expect(graphSection?.querySelector('pre')).toBeNull();
    expect(screen.queryByRole('button', { name: ADD_NODE_LABEL })).toBeNull();
  });

  it('omits historical graph details for an ordinary run', async () => {
    mocks.loadRun.mockImplementation(async (_runId, hydrate) => {
      hydrate({ run: GRAPHLESS_RUN, events: [], nextBeforeEventId: null });
      return () => {};
    });

    render(Page);

    await screen.findByRole('heading', { name: GRAPHLESS_RUN.config.name });
    expect(
      screen.queryByRole('heading', {
        name: new RegExp(RUN_DETAIL_COPY.EXECUTED_GRAPH_REVISION),
      }),
    ).toBeNull();
    expect(screen.queryByText(new RegExp(RUN_DETAIL_COPY.GRAPH_REVISION))).toBeNull();
    expect(mocks.listDefinitions).not.toHaveBeenCalled();
  });

  it('reports when the executed graph catalog cannot be loaded', async () => {
    mocks.listDefinitions.mockRejectedValue(new Error('catalog unavailable'));

    render(Page);

    expect((await screen.findByRole('alert')).textContent).toContain(
      RUN_DETAIL_COPY.GRAPH_LOAD_ERROR,
    );
    expect(document.querySelector('.historical-graph pre')).toBeNull();
  });

  it('attaches recorded failure detail to the failed lifecycle row', async () => {
    const failureDetail = 'RuntimeError: run launch failed';
    const failedLifecycle: PersistedDurableEvent = {
      id: 1,
      kind: EVENT_KIND.runLifecycle,
      run_id: RUN.id,
      occurred_at: '2026-08-30T00:00:01Z',
      payload: { status: RUN_STATUS.FAILED },
    };
    mocks.loadRun.mockImplementation(async (_runId, hydrate) => {
      hydrate({
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

    const row = (await screen.findByText(eventSummary(failedLifecycle))).closest('tr');
    expect(row?.getAttribute('tabindex')).toBe('0');
    expect(row?.getAttribute('aria-describedby')).toBe(
      `event-failure-detail-${failedLifecycle.id}`,
    );
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

function lifecycleEvent(id: number, status: RunRead['status']): PersistedDurableEvent {
  return {
    id,
    run_id: RUN.id,
    occurred_at: `2026-08-30T00:00:0${id}Z`,
    kind: EVENT_KIND.runLifecycle,
    payload: { status },
  };
}

function hydrateActive(events: PersistedDurableEvent[] = [], cursor: number | null = null) {
  mocks.loadRun.mockImplementation(async (_id, hydrate) => {
    hydrate({ run: ACTIVE_RUN, events, nextBeforeEventId: cursor });
    return vi.fn();
  });
}

describe('run detail interactions', () => {
  it('shows a pending stop request and applies the returned status', async () => {
    hydrateActive();
    const request = deferred<{ data: RunRead }>();
    mocks.stopRun.mockReturnValue(request.promise);
    render(Page);
    const stop = await screen.findByRole('button', {
      name: RUN_STATUS_PRESENTATION[RUN_STATUS.RUNNING].stopLabel!,
    });
    await fireEvent.click(stop);
    expect(mocks.stopRun).toHaveBeenCalledWith({ path: { run_id: RUN.id }, throwOnError: true });
    expect(stop.hasAttribute('disabled')).toBe(true);
    expect(stop.getAttribute('aria-busy')).toBe('true');
    expect(stop.textContent).toContain(RUN_DETAIL_COPY.SENDING);
    request.resolve({ data: { ...ACTIVE_RUN, status: RUN_STATUS.STOP_REQUESTED } });
    expect(
      (
        await screen.findByRole('button', {
          name: RUN_STATUS_PRESENTATION[RUN_STATUS.STOP_REQUESTED].stopLabel!,
        })
      ).hasAttribute('disabled'),
    ).toBe(true);
  });

  it('clears busy state after a failed stop so the request can be retried', async () => {
    hydrateActive();
    mocks.stopRun.mockRejectedValue(new Error('unavailable'));
    render(Page);
    const stop = await screen.findByRole('button', {
      name: RUN_STATUS_PRESENTATION[RUN_STATUS.RUNNING].stopLabel!,
    });
    await fireEvent.click(stop);
    expect(await screen.findByText(RUN_DETAIL_COPY.STOP_ERROR)).toBeTruthy();
    expect(stop.hasAttribute('disabled')).toBe(false);
    expect(stop.getAttribute('aria-busy')).not.toBe('true');
    expect(stop.textContent).toContain(RUN_STATUS_PRESENTATION[RUN_STATUS.RUNNING].stopLabel!);
  });

  it('applies durable and live stream callbacks and closes the stream on unmount', async () => {
    let durable!: (event: PersistedDurableEvent) => void;
    let live!: (event: LiveRunEvent) => void;
    const close = vi.fn();
    mocks.loadRun.mockImplementation(async (_id, hydrate, onDurable, onLive) => {
      durable = onDurable;
      live = onLive;
      hydrate({ run: ACTIVE_RUN, events: [], nextBeforeEventId: null });
      return close;
    });
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      callback(0);
      return 1;
    });
    vi.stubGlobal('cancelAnimationFrame', vi.fn());
    const view = render(Page);
    await screen.findByRole('button', {
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
    expect(await screen.findByText(RUN_DETAIL_COPY.STALE_BOOK_INPUT)).toBeTruthy();
    expect(screen.getByText('17')).toBeTruthy();
    durable(lifecycleEvent(1, RUN_STATUS.STOPPED));
    expect(
      await screen.findByText(eventSummary(lifecycleEvent(1, RUN_STATUS.STOPPED))),
    ).toBeTruthy();
    expect(
      screen.queryByRole('button', {
        name: RUN_STATUS_PRESENTATION[RUN_STATUS.RUNNING].stopLabel!,
      }),
    ).toBeNull();
    view.unmount();
    expect(close).toHaveBeenCalledOnce();
  });

  it('keeps the older-event cursor for retries and merges a successful page', async () => {
    hydrateActive([lifecycleEvent(2, RUN_STATUS.RUNNING)], 7);
    mocks.loadOlderEvents.mockRejectedValueOnce(new Error('unavailable'));
    render(Page);
    const button = await screen.findByRole('button', { name: RUN_DETAIL_COPY.LOAD_EARLIER });
    await fireEvent.click(button);
    expect(await screen.findByText(RUN_DETAIL_COPY.LOAD_ERROR)).toBeTruthy();
    expect(button.hasAttribute('disabled')).toBe(false);
    const request = deferred<{
      events: PersistedDurableEvent[];
      nextBeforeEventId: number | null;
    }>();
    mocks.loadOlderEvents.mockReturnValue(request.promise);
    await fireEvent.click(button);
    expect(mocks.loadOlderEvents).toHaveBeenLastCalledWith(RUN.id, 7);
    expect(button.hasAttribute('disabled')).toBe(true);
    expect(button.getAttribute('aria-busy')).toBe('true');
    expect(button.textContent).toContain(RUN_DETAIL_COPY.LOADING);
    await fireEvent.click(button);
    expect(mocks.loadOlderEvents).toHaveBeenCalledTimes(2);
    request.resolve({ events: [lifecycleEvent(1, RUN_STATUS.QUEUED)], nextBeforeEventId: null });
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: RUN_DETAIL_COPY.LOAD_EARLIER })).toBeNull(),
    );
    expect(await screen.findByText(loadedEventsLabel(2))).toBeTruthy();
    const rows = [...document.querySelectorAll('.event-table tbody tr')];
    expect(rows[0].textContent).toContain(eventSummary(lifecycleEvent(1, RUN_STATUS.QUEUED)));
    expect(rows[1].textContent).toContain(eventSummary(lifecycleEvent(2, RUN_STATUS.RUNNING)));
  });
});
