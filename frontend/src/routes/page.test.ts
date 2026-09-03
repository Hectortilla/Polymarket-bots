import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type {
  BotDefinitionDescriptor,
  BotRead
} from '$lib/api/generated';
import { TEST_GRAPH } from '$lib/catalog/nodeGraphTestFixtures';
import {
  BOT_DEFINITION_LABEL,
  SELECTION_MODE
} from '$lib/catalog/schema';
import runtimeContract from '$lib/runtimeContract.fixture.json';

const mocks = vi.hoisted(() => ({
  listBots: vi.fn(),
  listDefinitions: vi.fn(),
  listRuns: vi.fn()
}));

vi.mock('$lib/api/generated', () => ({
  listBotDefinitionsApiV1BotDefinitionsGet: mocks.listDefinitions,
  listBotsApiV1BotsGet: mocks.listBots,
  listRunsApiV1RunsGet: mocks.listRuns
}));

import Page from './+page.svelte';
import { HOME_COPY, graphRevisionLabel } from './homeCopy';

const DEFINITION = {
  definition_id: 'plain-definition',
  display_name: 'Plain bot',
  description: 'A test bot.',
  label: BOT_DEFINITION_LABEL.STANDARD,
  market_selection: SELECTION_MODE.ABSENT,
  wallet_selection: SELECTION_MODE.ABSENT,
  input_schema: {}
} satisfies BotDefinitionDescriptor;

const BOT = {
  id: 'aaaaaaaa-0000-0000-0000-000000000001',
  definition_id: DEFINITION.definition_id,
  config: {
    name: 'Saved setup',
    stream_rules: [],
    data_trades_budget_per_10s: runtimeContract.config.maximumDataTradesBudget,
    max_order_size: '10',
    max_slippage_pct: '0.02',
    paper_latency_ms: 250,
    paper_latency_jitter_ms: 100,
    event_max_age_ms: 5000,
    paper_portfolio_usdc: '1000'
  },
  created_at: '2026-08-30T00:00:00Z',
  updated_at: '2026-08-30T00:00:00Z'
} satisfies BotRead;

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function loadHome({ bots = [] }: { bots?: BotRead[] } = {}): void {
  mocks.listDefinitions.mockResolvedValue({ data: [DEFINITION] });
  mocks.listBots.mockResolvedValue({ data: bots });
  mocks.listRuns.mockResolvedValue({ data: [] });
}

describe('operations home', () => {
  it('shows an explicit empty saved-bot state', async () => {
    loadHome();
    render(Page);

    expect(
      await screen.findByText(HOME_COPY.NO_SAVED_BOTS)
    ).toBeTruthy();
  });

  it('links each saved bot to its detail page', async () => {
    loadHome({ bots: [BOT] });
    render(Page);

    const link = await screen.findByRole('link', { name: BOT.config.name });
    expect(link.getAttribute('href')).toBe(`/bots/${BOT.id}`);
  });

  it('shows the latest immutable graph revision for a saved bot', async () => {
    const graphBot = {
      ...BOT,
      latest_graph_revision: {
        id: 'cccccccc-0000-0000-0000-000000000001',
        bot_id: BOT.id,
        revision: 4,
        graph: TEST_GRAPH,
        created_at: BOT.created_at
      }
    } satisfies BotRead;
    loadHome({ bots: [graphBot] });

    render(Page);

    expect(await screen.findByText(graphRevisionLabel(4))).toBeTruthy();
  });

  it('reports a failed home load without rendering partial data', async () => {
    mocks.listDefinitions.mockRejectedValue(new Error('catalog unavailable'));
    mocks.listBots.mockResolvedValue({ data: [BOT] });
    mocks.listRuns.mockResolvedValue({ data: [] });
    render(Page);

    expect((await screen.findByRole('alert')).textContent).toContain(
      HOME_COPY.LOAD_ERROR
    );
    expect(screen.queryByRole('link', { name: BOT.config.name })).toBeNull();
  });
});
