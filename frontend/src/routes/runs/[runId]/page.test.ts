import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { RunRead } from '$lib/api/generated';
import { TEST_GRAPH } from '$lib/catalog/nodeGraphTestFixtures';
import { botPath } from '$lib/navigation';
import runtimeContract from '$lib/runtimeContract.fixture.json';
import { RUN_STATUS } from '$lib/runs/status';

const mocks = vi.hoisted(() => ({
  loadRun: vi.fn(),
  loadOlderEvents: vi.fn()
}));

vi.mock('$app/state', () => ({
  page: { params: { runId: 'aaaaaaaa-0000-0000-0000-000000000001' } }
}));
vi.mock('$lib/runs/hydrate', () => ({
  loadAndContinueRunDetail: mocks.loadRun,
  loadOlderRunEvents: mocks.loadOlderEvents
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

class PassiveIntersectionObserver {
  observe(): void {}
  disconnect(): void {}
}

beforeEach(() => {
  vi.stubGlobal('IntersectionObserver', PassiveIntersectionObserver);
  mocks.loadRun.mockImplementation(async (_runId, hydrate) => {
    hydrate({ run: RUN, events: [], nextBeforeEventId: null });
    return () => {};
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe('run detail page', () => {
  it('renders the saved-bot link and immutable historical graph snapshot', async () => {
    render(Page);

    const botLink = await screen.findByRole('link', {
      name: RUN.definition_id
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
    expect(graphSection?.querySelector('pre')?.textContent).toBe(
      JSON.stringify(TEST_GRAPH, null, 2)
    );
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
  });
});
