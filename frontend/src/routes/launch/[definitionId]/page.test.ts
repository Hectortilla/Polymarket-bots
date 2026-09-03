import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type {
  BotDefinitionDescriptor,
  GraphTemplateRead
} from '$lib/api/generated';
import {
  TEST_GRAPH,
  TEST_GRAPH_CATALOG
} from '$lib/catalog/nodeGraphTestFixtures';
import {
  BOT_DEFINITION_LABEL,
  SELECTION_MODE
} from '$lib/catalog/schema';
import { NAVIGATION_PATH } from '$lib/navigation';

const mocks = vi.hoisted(() => ({
  createBot: vi.fn(),
  goto: vi.fn(),
  listDefinitions: vi.fn(),
  listTemplates: vi.fn()
}));

vi.mock('$app/navigation', () => ({ goto: mocks.goto }));
vi.mock('$app/state', () => ({
  page: { params: { definitionId: 'plain-definition' } }
}));
vi.mock('$lib/api/generated', () => ({
  createBotApiV1BotsPost: mocks.createBot,
  listBotDefinitionsApiV1BotDefinitionsGet: mocks.listDefinitions,
  listGraphTemplatesApiV1GraphTemplatesGet: mocks.listTemplates
}));

import Page from './+page.svelte';
import { BOT_CREATION_COPY } from './copy';
import { LAUNCH_FORM_COPY } from '$lib/catalog/copy';

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

const GRAPH_CAPABLE_DEFINITION = {
  ...DEFINITION,
  graph_catalog: TEST_GRAPH_CATALOG,
  starter_graph: TEST_GRAPH
} satisfies BotDefinitionDescriptor;

const TEMPLATE = {
  id: 'cccccccc-0000-0000-0000-000000000001',
  name: 'Reusable graph',
  graph: TEST_GRAPH,
  created_at: '2026-08-30T00:00:00Z',
  updated_at: '2026-08-30T00:00:00Z'
} satisfies GraphTemplateRead;

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('saved-bot creation page', () => {
  it('saves a configured bot without launching it and opens bot detail', async () => {
    mocks.listDefinitions.mockResolvedValue({ data: [DEFINITION] });
    mocks.listTemplates.mockResolvedValue({ data: [] });
    mocks.createBot.mockResolvedValue({
      data: { id: 'aaaaaaaa-0000-0000-0000-000000000001' }
    });
    render(Page);

    await fireEvent.input(await screen.findByLabelText('Name'), {
      target: { value: 'Reusable setup' }
    });
    await fireEvent.click(
      screen.getByRole('button', { name: LAUNCH_FORM_COPY.SAVE_BOT })
    );

    await waitFor(() => {
      expect(mocks.createBot).toHaveBeenCalledWith({
        body: {
          definition_id: DEFINITION.definition_id,
          inputs: { name: 'Reusable setup' }
        },
        throwOnError: true
      });
    });
    expect(mocks.goto).toHaveBeenCalledWith(
      '/bots/aaaaaaaa-0000-0000-0000-000000000001'
    );
  });

  it('copies the selected graph template into a new saved bot', async () => {
    const secondTemplate = {
      ...TEMPLATE,
      id: 'dddddddd-0000-0000-0000-000000000001',
      name: 'Second graph'
    } satisfies GraphTemplateRead;
    mocks.listDefinitions.mockResolvedValue({ data: [GRAPH_CAPABLE_DEFINITION] });
    mocks.listTemplates.mockResolvedValue({ data: [TEMPLATE, secondTemplate] });
    mocks.createBot.mockResolvedValue({
      data: { id: 'aaaaaaaa-0000-0000-0000-000000000002' }
    });
    render(Page);

    await fireEvent.change(await screen.findByRole('combobox'), {
      target: { value: secondTemplate.id }
    });
    await fireEvent.input(screen.getByLabelText('Name'), {
      target: { value: 'Graph setup' }
    });
    await fireEvent.click(
      screen.getByRole('button', { name: LAUNCH_FORM_COPY.SAVE_BOT })
    );

    await waitFor(() => {
      expect(mocks.createBot).toHaveBeenCalledWith({
        body: {
          definition_id: GRAPH_CAPABLE_DEFINITION.definition_id,
          inputs: { name: 'Graph setup' },
          graph_template_id: secondTemplate.id
        },
        throwOnError: true
      });
    });
  });

  it('requires a template before saving a graph-capable bot', async () => {
    mocks.listDefinitions.mockResolvedValue({ data: [GRAPH_CAPABLE_DEFINITION] });
    mocks.listTemplates.mockResolvedValue({ data: [] });
    render(Page);

    expect(
      (await screen.findByText((_, element) =>
        Boolean(
          element?.classList.contains('notice') &&
          element.textContent?.includes(BOT_CREATION_COPY.TEMPLATE_REQUIRED)
        )
      )).textContent
    ).toContain(BOT_CREATION_COPY.TEMPLATE_REQUIRED);
    expect(
      screen.getByRole<HTMLButtonElement>('button', {
        name: LAUNCH_FORM_COPY.SAVE_BOT
      }).disabled
    ).toBe(true);
    expect(
      screen.getByRole('link', {
        name: BOT_CREATION_COPY.OPEN_GRAPH_TEMPLATES
      }).getAttribute('href')
    ).toBe(NAVIGATION_PATH.GRAPH_TEMPLATES);
  });

  it('reports catalog and save failures', async () => {
    mocks.listDefinitions.mockRejectedValueOnce(new Error('offline'));
    mocks.listTemplates.mockResolvedValue({ data: [] });
    const failedLoad = render(Page);

    expect((await screen.findByRole('alert')).textContent).toContain(
      BOT_CREATION_COPY.CATALOG_LOAD_ERROR
    );
    failedLoad.unmount();

    mocks.listDefinitions.mockResolvedValue({ data: [DEFINITION] });
    mocks.listTemplates.mockResolvedValue({ data: [] });
    mocks.createBot.mockRejectedValue(new Error('write failed'));
    render(Page);
    await fireEvent.input(await screen.findByLabelText('Name'), {
      target: { value: 'Rejected setup' }
    });
    await fireEvent.click(
      screen.getByRole('button', { name: LAUNCH_FORM_COPY.SAVE_BOT })
    );

    expect((await screen.findByRole('alert')).textContent).toContain(
      BOT_CREATION_COPY.SAVE_ERROR
    );
  });

  it('reports a missing requested definition without rendering the form', async () => {
    mocks.listDefinitions.mockResolvedValue({ data: [] });
    mocks.listTemplates.mockResolvedValue({ data: [] });
    render(Page);

    expect((await screen.findByRole('alert')).textContent).toContain(
      BOT_CREATION_COPY.DEFINITION_NOT_FOUND
    );
    expect(
      screen.queryByRole('button', { name: LAUNCH_FORM_COPY.SAVE_BOT })
    ).toBeNull();
  });
});
