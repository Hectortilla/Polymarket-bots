import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { BotDefinitionDescriptor, BotRead } from '$lib/api/generated';
import {
  TEST_GRAPH,
  TEST_GRAPH_CATALOG
} from '$lib/catalog/nodeGraphTestFixtures';
import {
  BOT_DEFINITION_LABEL,
  SELECTION_MODE
} from '$lib/catalog/schema';
import runtimeContract from '$lib/runtimeContract.fixture.json';

const mocks = vi.hoisted(() => ({
  createBot: vi.fn(),
  createTemplate: vi.fn(),
  goto: vi.fn(),
  listBots: vi.fn(),
  listDefinitions: vi.fn()
}));

vi.mock('$app/navigation', () => ({ goto: mocks.goto }));
vi.mock('$lib/api/generated', () => ({
  createBotApiV1BotsPost: mocks.createBot,
  createGraphTemplateApiV1GraphTemplatesPost: mocks.createTemplate,
  listBotDefinitionsApiV1BotDefinitionsGet: mocks.listDefinitions,
  listBotsApiV1BotsGet: mocks.listBots
}));

import Page from './+page.svelte';

const DEFINITION = {
  definition_id: 'node-based-bot',
  display_name: 'Node-Based Bot',
  description: 'Visually compose and run a paper-trading event graph.',
  label: BOT_DEFINITION_LABEL.STANDARD,
  market_selection: SELECTION_MODE.USER_CONFIGURED,
  wallet_selection: SELECTION_MODE.ABSENT,
  graph_catalog: TEST_GRAPH_CATALOG,
  starter_graph: TEST_GRAPH,
  input_schema: {
    type: 'object',
    additionalProperties: false,
    required: ['name'],
    properties: { name: { type: 'string', minLength: 1 } }
  }
} satisfies BotDefinitionDescriptor;

const SOURCE_BOT = {
  id: 'aaaaaaaa-0000-0000-0000-000000000001',
  definition_id: DEFINITION.definition_id,
  config: {
    name: 'Source bot',
    stream_rules: [],
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
    revision: 2,
    graph: TEST_GRAPH,
    created_at: '2026-08-30T00:00:00Z'
  },
  created_at: '2026-08-30T00:00:00Z',
  updated_at: '2026-08-30T00:00:00Z'
} satisfies BotRead;

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function loadBuilder(bots: BotRead[] = []): void {
  mocks.listDefinitions.mockResolvedValue({ data: [DEFINITION] });
  mocks.listBots.mockResolvedValue({ data: bots });
  mocks.createTemplate.mockResolvedValue({
    data: { id: 'dddddddd-0000-0000-0000-000000000001' }
  });
  mocks.createBot.mockResolvedValue({
    data: { id: 'eeeeeeee-0000-0000-0000-000000000001' }
  });
}

describe('unified bot creation page', () => {
  it('creates the graph copy and configured bot from one form', async () => {
    loadBuilder();
    render(Page);

    await fireEvent.input(await screen.findByLabelText('Name'), {
      target: { value: 'Threshold buyer' }
    });
    await fireEvent.click(screen.getByRole('button', { name: 'Create bot' }));

    await waitFor(() => {
      expect(mocks.createTemplate).toHaveBeenCalledWith({
        body: {
          name: expect.stringMatching(/^bot-draft-/),
          graph: TEST_GRAPH
        },
        throwOnError: true
      });
      expect(mocks.createBot).toHaveBeenCalledWith({
        body: {
          definition_id: DEFINITION.definition_id,
          inputs: { name: 'Threshold buyer' },
          graph_template_id: 'dddddddd-0000-0000-0000-000000000001'
        },
        throwOnError: true
      });
    });
    expect(mocks.goto).toHaveBeenCalledWith(
      '/bots/eeeeeeee-0000-0000-0000-000000000001'
    );
  });

  it('offers existing bots as graph starting points without exposing templates', async () => {
    loadBuilder([SOURCE_BOT]);
    render(Page);

    const source = await screen.findByLabelText('Starting point');
    await fireEvent.change(source, { target: { value: SOURCE_BOT.id } });
    await fireEvent.click(screen.getByRole('button', { name: 'Copy graph' }));

    expect(screen.getByText(/Current source: Source bot/)).toBeTruthy();
    expect(screen.queryByText('Graph template')).toBeNull();
  });

  it('reports a missing graph-capable definition instead of offering bot types', async () => {
    mocks.listDefinitions.mockResolvedValue({ data: [] });
    mocks.listBots.mockResolvedValue({ data: [] });
    render(Page);

    expect((await screen.findByRole('alert')).textContent).toContain(
      'The node-based bot definition is unavailable.'
    );
    expect(screen.queryByLabelText('Name')).toBeNull();
  });

  it('preserves the entered configuration when creation fails', async () => {
    loadBuilder();
    mocks.createBot.mockRejectedValue(new Error('write failed'));
    render(Page);

    const name = await screen.findByLabelText('Name');
    await fireEvent.input(name, { target: { value: 'Keep my draft' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Create bot' }));

    expect((await screen.findByRole('alert')).textContent).toContain(
      'The bot could not be saved.'
    );
    expect((name as HTMLInputElement).value).toBe('Keep my draft');
  });
});
