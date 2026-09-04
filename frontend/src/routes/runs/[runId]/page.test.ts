import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { BotDefinitionDescriptor, RunRead } from '$lib/api/generated';
import {
  TEST_GRAPH,
  TEST_GRAPH_CATALOG
} from '$lib/catalog/nodeGraphTestFixtures';
import { BOT_DEFINITION_LABEL, SELECTION_MODE } from '$lib/catalog/schema';
import { botPath } from '$lib/navigation';
import runtimeContract from '$lib/runtimeContract.fixture.json';
import { EVENT_KIND, type PersistedDurableEvent } from '$lib/runs/durableEvents';
import { RUN_STATUS } from '$lib/runs/status';

const mocks = vi.hoisted(() => ({
  listDefinitions: vi.fn(),
  loadRun: vi.fn(),
  loadOlderEvents: vi.fn(),
  stopRun: vi.fn()
}));

vi.mock('$app/state', () => ({
  page: { params: { runId: 'aaaaaaaa-0000-0000-0000-000000000001' } }
}));
vi.mock('$lib/runs/hydrate', () => ({
  loadAndContinueRunDetail: mocks.loadRun,
  loadOlderRunEvents: mocks.loadOlderEvents
}));
vi.mock('$lib/api/generated', () => ({
  listBotDefinitionsApiV1BotDefinitionsGet: mocks.listDefinitions,
  stopRunApiV1RunsRunIdStopPost: mocks.stopRun
}));

import Page from './+page.svelte';
import {
  RUN_DETAIL_COPY,
  executedRunGraphRevisionLabel
} from './copy';

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
    paper_portfolio_usdc: '1000'
  },
  status: RUN_STATUS.STOPPED,
  created_at: '2026-08-30T00:00:00Z'
} satisfies RunRead;

const GRAPHLESS_RUN = {
  ...RUN,
  bot_graph_revision_id: null,
  graph_revision: null,
  graph: null
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
  starter_graph: TEST_GRAPH
} satisfies BotDefinitionDescriptor;

class PassiveIntersectionObserver {
  observe(): void {}
  disconnect(): void {}
}

class FlowResizeObserver implements ResizeObserver {
  constructor(private readonly callback: ResizeObserverCallback) {}

  observe(target: Element): void {
    this.callback([{
      target,
      contentRect: { width: 100, height: 50 }
    } as ResizeObserverEntry], this);
  }

  disconnect(): void {}
  unobserve(): void {}
}

beforeEach(() => {
  vi.stubGlobal('IntersectionObserver', PassiveIntersectionObserver);
  vi.stubGlobal('ResizeObserver', FlowResizeObserver);
  vi.stubGlobal('DOMMatrixReadOnly', class {
    readonly m22 = 1;
  });
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
      name: 'Bot configuration'
    });
    expect(botLink.getAttribute('href')).toBe(botPath(RUN.bot_id));
    expect(
      screen.getByRole('heading', {
        name: executedRunGraphRevisionLabel(RUN.graph_revision)
      })
    ).toBeTruthy();

    const graphSection = screen
      .getByRole('heading', {
        name: executedRunGraphRevisionLabel(RUN.graph_revision)
      })
      .closest('section');
    expect(graphSection).not.toBeNull();
    const graphCanvas = await screen.findByRole('group', {
      name: executedRunGraphRevisionLabel(RUN.graph_revision)
    });
    expect(graphCanvas.getAttribute('aria-disabled')).toBe('true');
    expect(screen.getByLabelText('on_book trigger node')).toBeTruthy();
    expect(graphSection?.querySelector('pre')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Add node' })).toBeNull();
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
        name: new RegExp(RUN_DETAIL_COPY.EXECUTED_GRAPH_REVISION)
      })
    ).toBeNull();
    expect(
      screen.queryByText(new RegExp(RUN_DETAIL_COPY.GRAPH_REVISION))
    ).toBeNull();
    expect(mocks.listDefinitions).not.toHaveBeenCalled();
  });

  it('reports when the executed graph catalog cannot be loaded', async () => {
    mocks.listDefinitions.mockRejectedValue(new Error('catalog unavailable'));

    render(Page);

    expect((await screen.findByRole('alert')).textContent).toContain(
      RUN_DETAIL_COPY.GRAPH_LOAD_ERROR
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
      payload: { status: RUN_STATUS.FAILED }
    };
    mocks.loadRun.mockImplementation(async (_runId, hydrate) => {
      hydrate({
        run: {
          ...GRAPHLESS_RUN,
          status: RUN_STATUS.FAILED,
          failure_detail: failureDetail
        },
        events: [failedLifecycle],
        nextBeforeEventId: null
      });
      return () => {};
    });

    render(Page);

    const row = (await screen.findByText('Run Failed')).closest('tr');
    expect(row?.getAttribute('tabindex')).toBe('0');
    expect(row?.getAttribute('aria-describedby')).toBe(
      `event-failure-detail-${failedLifecycle.id}`
    );
    expect(row?.querySelector('[role="tooltip"]')?.textContent).toContain(
      failureDetail
    );
  });
});
