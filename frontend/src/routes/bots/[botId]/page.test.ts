import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type {
  BotDefinitionDescriptor,
  BotRead
} from '$lib/api/generated';
import runtimeContract from '$lib/runtimeContract.fixture.json';

import {
  TEST_GRAPH,
  TEST_GRAPH_CATALOG
} from '$lib/catalog/nodeGraphTestFixtures';
import { GRAPH_VALIDATION_COPY } from '$lib/catalog/graphValidation';
import { ADD_NODE_LABEL } from '$lib/catalog/NodePalette.svelte';
import {
  BOT_DEFINITION_LABEL,
  SELECTION_MODE
} from '$lib/catalog/schema';

const mocks = vi.hoisted(() => ({
  createRevision: vi.fn(),
  goto: vi.fn(),
  launchRun: vi.fn(),
  listDefinitions: vi.fn(),
  readBot: vi.fn(),
  updateBot: vi.fn()
}));

vi.mock('$app/navigation', () => ({ goto: mocks.goto }));
vi.mock('$app/state', () => ({
  page: { params: { botId: 'aaaaaaaa-0000-0000-0000-000000000001' } }
}));
vi.mock('$lib/api/generated', () => ({
  createBotGraphRevisionApiV1BotsBotIdGraphRevisionsPost:
    mocks.createRevision,
  launchBotRunApiV1BotsBotIdRunsPost: mocks.launchRun,
  listBotDefinitionsApiV1BotDefinitionsGet: mocks.listDefinitions,
  readBotApiV1BotsBotIdGet: mocks.readBot,
  updateBotApiV1BotsBotIdPatch: mocks.updateBot
}));

import Page from './+page.svelte';
import { BOT_DETAIL_COPY, botGraphRevisionLabel } from './copy';

const BOT = {
  id: 'aaaaaaaa-0000-0000-0000-000000000001',
  definition_id: 'plain-definition',
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
const DEFINITION = {
  definition_id: 'plain-definition',
  display_name: 'Plain bot',
  description: 'A saved bot test definition.',
  label: BOT_DEFINITION_LABEL.STANDARD,
  market_selection: SELECTION_MODE.ABSENT,
  wallet_selection: SELECTION_MODE.ABSENT,
  input_schema: {
    type: 'object',
    additionalProperties: false,
    required: ['name'],
    properties: { name: { type: 'string', minLength: 1 } }
  }
} satisfies BotDefinitionDescriptor;

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('saved-bot detail page', () => {
  it('blocks runs while dirty, saves settings, then reruns the saved bot', async () => {
    mocks.readBot.mockResolvedValue({ data: BOT });
    mocks.listDefinitions.mockResolvedValue({ data: [DEFINITION] });
    mocks.updateBot.mockImplementation(async ({ body }) => ({
      data: { ...BOT, config: { ...BOT.config, name: body.inputs.name } }
    }));
    mocks.launchRun.mockResolvedValue({
      data: { id: 'bbbbbbbb-0000-0000-0000-000000000001' }
    });
    render(Page);

    const name = await screen.findByLabelText('Name');
    const runButton = await screen.findByRole<HTMLButtonElement>('button', {
      name: BOT_DETAIL_COPY.RUN
    });
    expect(runButton.disabled).toBe(false);

    await fireEvent.input(name, { target: { value: 'Edited setup' } });
    expect(runButton.disabled).toBe(true);
    expect(screen.getByText(BOT_DETAIL_COPY.UNSAVED_RUN_BLOCK)).toBeTruthy();

    await fireEvent.click(
      screen.getByRole('button', { name: BOT_DETAIL_COPY.SAVE_CONFIGURATION })
    );
    await waitFor(() => expect(runButton.disabled).toBe(false));
    await fireEvent.click(runButton);

    expect(mocks.updateBot).toHaveBeenCalledWith({
      path: { bot_id: BOT.id },
      body: { inputs: { name: 'Edited setup' } },
      throwOnError: true
    });
    expect(mocks.launchRun).toHaveBeenCalledWith({
      path: { bot_id: BOT.id },
      throwOnError: true
    });
    expect(mocks.goto).toHaveBeenCalledWith(
      '/runs/bbbbbbbb-0000-0000-0000-000000000001'
    );
  });

  it('appends an explicit graph revision before allowing the newest graph to run', async () => {
    const graphBot = {
      ...BOT,
      latest_graph_revision: {
        id: 'cccccccc-0000-0000-0000-000000000001',
        bot_id: BOT.id,
        revision: 1,
        graph: TEST_GRAPH,
        created_at: BOT.created_at
      }
    };
    const graphCapableDefinition = {
      ...DEFINITION,
      graph_catalog: TEST_GRAPH_CATALOG,
      starter_graph: TEST_GRAPH
    };
    mocks.readBot.mockResolvedValue({ data: graphBot });
    mocks.listDefinitions.mockResolvedValue({ data: [graphCapableDefinition] });
    mocks.createRevision.mockImplementation(async ({ body }) => ({
      data: {
        ...graphBot,
        updated_at: '2026-08-30T00:01:00Z',
        latest_graph_revision: {
          id: 'dddddddd-0000-0000-0000-000000000001',
          bot_id: BOT.id,
          revision: 2,
          graph: body.graph,
          created_at: '2026-08-30T00:01:00Z'
        }
      }
    }));
    render(Page);

    const runButton = await screen.findByRole<HTMLButtonElement>('button', {
      name: BOT_DETAIL_COPY.RUN
    });
    const saveGraphButton = screen.getByRole<HTMLButtonElement>('button', {
      name: BOT_DETAIL_COPY.SAVE_GRAPH_REVISION
    });
    await waitFor(() => expect(runButton.disabled).toBe(false));
    expect(saveGraphButton.disabled).toBe(true);
    expect(screen.queryByText(BOT_DETAIL_COPY.UNSAVED_RUN_BLOCK)).toBeNull();

    await fireEvent.click(await screen.findByRole('button', { name: ADD_NODE_LABEL }));
    await fireEvent.click(screen.getByRole('button', { name: 'Add on_start' }));
    expect(runButton.disabled).toBe(true);
    expect(saveGraphButton.disabled).toBe(false);

    await fireEvent.click(saveGraphButton);

    await waitFor(() => {
      expect(mocks.createRevision).toHaveBeenCalledWith({
        path: { bot_id: BOT.id },
        body: {
          graph: expect.objectContaining({
            nodes: expect.arrayContaining([
              expect.objectContaining({ data: { hook_name: 'on_start' } })
            ])
          })
        },
        throwOnError: true
      });
      expect(runButton.disabled).toBe(false);
    });
    expect(
      screen.getByRole('heading', { name: botGraphRevisionLabel(2) })
    ).toBeTruthy();
  });

  it('keeps a failed graph revision dirty and blocks running', async () => {
    const graphBot = {
      ...BOT,
      latest_graph_revision: {
        id: 'cccccccc-0000-0000-0000-000000000001',
        bot_id: BOT.id,
        revision: 1,
        graph: TEST_GRAPH,
        created_at: BOT.created_at
      }
    } satisfies BotRead;
    mocks.readBot.mockResolvedValue({ data: graphBot });
    mocks.listDefinitions.mockResolvedValue({
      data: [
        {
          ...DEFINITION,
          graph_catalog: TEST_GRAPH_CATALOG,
          starter_graph: TEST_GRAPH
        }
      ]
    });
    mocks.createRevision.mockRejectedValue(new Error('write failed'));
    render(Page);

    await fireEvent.click(await screen.findByRole('button', { name: ADD_NODE_LABEL }));
    await fireEvent.click(screen.getByRole('button', { name: 'Add on_start' }));
    const saveGraphButton = screen.getByRole<HTMLButtonElement>('button', {
      name: BOT_DETAIL_COPY.SAVE_GRAPH_REVISION
    });
    const runButton = screen.getByRole<HTMLButtonElement>('button', {
      name: BOT_DETAIL_COPY.RUN
    });
    await fireEvent.click(saveGraphButton);

    expect((await screen.findByRole('alert')).textContent).toContain(
      BOT_DETAIL_COPY.GRAPH_SAVE_ERROR
    );
    expect(saveGraphButton.disabled).toBe(false);
    expect(runButton.disabled).toBe(true);
  });

  it('shows authoritative graph validation details beside the editor', async () => {
    const graphBot = {
      ...BOT,
      latest_graph_revision: {
        id: 'cccccccc-0000-0000-0000-000000000001',
        bot_id: BOT.id,
        revision: 1,
        graph: TEST_GRAPH,
        created_at: BOT.created_at
      }
    } satisfies BotRead;
    mocks.readBot.mockResolvedValue({ data: graphBot });
    mocks.listDefinitions.mockResolvedValue({
      data: [
        {
          ...DEFINITION,
          graph_catalog: TEST_GRAPH_CATALOG,
          starter_graph: TEST_GRAPH
        }
      ]
    });
    mocks.createRevision.mockRejectedValue({
      detail: [
        {
          loc: ['body', 'graph'],
          msg: 'Value error, graph input cardinality is invalid',
          type: 'value_error'
        }
      ]
    });
    render(Page);

    await fireEvent.click(await screen.findByRole('button', { name: ADD_NODE_LABEL }));
    await fireEvent.click(screen.getByRole('button', { name: 'Add on_start' }));
    await fireEvent.click(
      screen.getByRole('button', { name: BOT_DETAIL_COPY.SAVE_GRAPH_REVISION })
    );

    const summary = await screen.findByRole('alert');
    expect(
      screen.getByRole('heading', { name: GRAPH_VALIDATION_COPY.TITLE })
    ).toBeTruthy();
    expect(summary.textContent).toContain(GRAPH_VALIDATION_COPY.STRUCTURE);
    expect(summary.textContent).toContain('Graph input cardinality is invalid.');
    expect(document.activeElement).toBe(summary);
    expect(screen.queryByText(BOT_DETAIL_COPY.GRAPH_SAVE_ERROR)).toBeNull();
  });

  it('reports a saved-bot load failure', async () => {
    mocks.readBot.mockRejectedValue(new Error('missing'));
    mocks.listDefinitions.mockResolvedValue({ data: [DEFINITION] });
    render(Page);

    expect((await screen.findByRole('alert')).textContent).toContain(
      BOT_DETAIL_COPY.LOAD_ERROR
    );
  });

  it('rejects a saved bot whose definition is absent from the catalog', async () => {
    mocks.readBot.mockResolvedValue({ data: BOT });
    mocks.listDefinitions.mockResolvedValue({ data: [] });
    render(Page);

    expect((await screen.findByRole('alert')).textContent).toContain(
      BOT_DETAIL_COPY.LOAD_ERROR
    );
    expect(
      screen.queryByRole('button', { name: BOT_DETAIL_COPY.RUN })
    ).toBeNull();
    expect(screen.queryByLabelText('Name')).toBeNull();
  });

  it('keeps unsaved configuration after a failed save', async () => {
    mocks.readBot.mockResolvedValue({ data: BOT });
    mocks.listDefinitions.mockResolvedValue({ data: [DEFINITION] });
    mocks.updateBot.mockRejectedValue(new Error('write failed'));
    render(Page);

    const name = await screen.findByLabelText('Name');
    await fireEvent.input(name, { target: { value: 'Unsaved setup' } });
    await fireEvent.click(
      screen.getByRole('button', { name: BOT_DETAIL_COPY.SAVE_CONFIGURATION })
    );

    expect((await screen.findByRole('alert')).textContent).toContain(
      BOT_DETAIL_COPY.CONFIG_SAVE_ERROR
    );
    expect((name as HTMLInputElement).value).toBe('Unsaved setup');
    expect(
      screen.getByRole<HTMLButtonElement>('button', {
        name: BOT_DETAIL_COPY.RUN
      }).disabled
    ).toBe(true);
  });

  it('shows backend configuration validation under its field', async () => {
    mocks.readBot.mockResolvedValue({ data: BOT });
    mocks.listDefinitions.mockResolvedValue({ data: [DEFINITION] });
    mocks.updateBot.mockRejectedValue({
      detail: [
        {
          loc: ['body', 'inputs', 'name'],
          msg: 'Value error, this bot name is reserved',
          type: 'value_error'
        }
      ]
    });
    render(Page);

    const name = await screen.findByLabelText('Name');
    await fireEvent.input(name, { target: { value: 'Reserved name' } });
    await fireEvent.click(
      screen.getByRole('button', { name: BOT_DETAIL_COPY.SAVE_CONFIGURATION })
    );

    expect(await screen.findByText('This bot name is reserved.')).toBeTruthy();
    expect(name.getAttribute('aria-invalid')).toBe('true');
    expect(screen.queryByText(BOT_DETAIL_COPY.CONFIG_SAVE_ERROR)).toBeNull();
  });

  it('reports a failed run launch', async () => {
    mocks.readBot.mockResolvedValue({ data: BOT });
    mocks.listDefinitions.mockResolvedValue({ data: [DEFINITION] });
    mocks.launchRun.mockRejectedValue(new Error('delivery failed'));
    render(Page);

    await fireEvent.click(
      await screen.findByRole('button', { name: BOT_DETAIL_COPY.RUN })
    );

    expect((await screen.findByRole('alert')).textContent).toContain(
      BOT_DETAIL_COPY.RUN_ERROR
    );
    expect(mocks.goto).not.toHaveBeenCalled();
  });
});
