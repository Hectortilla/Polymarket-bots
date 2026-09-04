import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { BotRead, RunRead, StreamRelation } from '$lib/api/generated';
import { TEST_GRAPH } from '$lib/catalog/nodeGraphTestFixtures';
import runtimeContract from '$lib/runtimeContract.fixture.json';

const mocks = vi.hoisted(() => ({
  listBots: vi.fn(),
  listRuns: vi.fn()
}));

vi.mock('$lib/api/generated', () => ({
  listBotsApiV1BotsGet: mocks.listBots,
  listRunsApiV1RunsGet: mocks.listRuns
}));

import Page from './+page.svelte';
import { HOME_COPY, graphRevisionLabel } from './homeCopy';

const BOT = {
  id: 'aaaaaaaa-0000-0000-0000-000000000001',
  definition_id: 'node-based-bot',
  config: {
    name: 'BTC threshold buyer',
    stream_rules: [
      {
        relation: runtimeContract.streamRelation.INDEPENDENT as StreamRelation,
        market_slugs: ['btc-updown-5m-test']
      }
    ],
    data_trades_budget_per_10s: runtimeContract.config.maximumDataTradesBudget,
    max_order_size: '10',
    max_slippage_pct: '0.02',
    paper_latency_ms: 250,
    paper_latency_jitter_ms: 100,
    event_max_age_ms: 5000,
    paper_portfolio_usdc: '1000'
  },
  latest_graph_revision: {
    id: 'cccccccc-0000-0000-0000-000000000001',
    bot_id: 'aaaaaaaa-0000-0000-0000-000000000001',
    revision: 4,
    graph: TEST_GRAPH,
    created_at: '2026-08-30T00:00:00Z'
  },
  created_at: '2026-08-30T00:00:00Z',
  updated_at: '2026-08-30T00:00:00Z'
} satisfies BotRead;

const RUN = {
  id: 'bbbbbbbb-0000-0000-0000-000000000001',
  bot_id: BOT.id,
  definition_id: BOT.definition_id,
  config: BOT.config,
  status: 'running',
  created_at: BOT.created_at,
  started_at: BOT.created_at,
  ended_at: null,
  heartbeat_at: BOT.created_at,
  failure_detail: null,
  bot_graph_revision_id: BOT.latest_graph_revision.id,
  graph_revision: BOT.latest_graph_revision.revision,
  graph: TEST_GRAPH,
  latest_equity: '1004.25',
  equity_status: 'fresh'
} satisfies RunRead;

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function loadHome({ bots = [], runs = [] }: { bots?: BotRead[]; runs?: RunRead[] } = {}): void {
  mocks.listBots.mockResolvedValue({ data: bots });
  mocks.listRuns.mockResolvedValue({ data: runs });
}

describe('bots home', () => {
  it('shows one direct creation action and no bot catalog', async () => {
    loadHome();
    render(Page);

    expect(await screen.findByRole('heading', { name: 'Create your first bot' })).toBeTruthy();
    expect(screen.getAllByRole('link', { name: 'New bot' })[0]?.getAttribute('href'))
      .toBe('/bots/new');
    expect(screen.queryByText('Bot catalog')).toBeNull();
  });

  it('shows configured bots as scannable rows with their operational context', async () => {
    loadHome({ bots: [BOT], runs: [RUN] });
    render(Page);

    const link = await screen.findByRole('link', { name: `Open ${BOT.config.name}` });
    expect(link.getAttribute('href')).toBe(`/bots/${BOT.id}`);
    expect(screen.getByText('btc-updown-5m-test')).toBeTruthy();
    expect(screen.getByText(graphRevisionLabel(4))).toBeTruthy();
    expect(screen.getAllByText('Running').length).toBeGreaterThan(0);
  });

  it('does not expose non-graph catalog bots in the operator workspace', async () => {
    const legacyBot = { ...BOT, id: 'legacy', latest_graph_revision: null } satisfies BotRead;
    loadHome({ bots: [legacyBot] });
    render(Page);

    expect(await screen.findByRole('heading', { name: 'Create your first bot' })).toBeTruthy();
    expect(screen.queryByText(legacyBot.config.name)).toBeNull();
  });

  it('reports a failed home load without rendering partial data', async () => {
    mocks.listBots.mockRejectedValue(new Error('offline'));
    mocks.listRuns.mockResolvedValue({ data: [RUN] });
    render(Page);

    expect((await screen.findByRole('alert')).textContent).toContain(
      HOME_COPY.LOAD_ERROR
    );
    expect(screen.queryByText(RUN.config.name)).toBeNull();
  });
});
