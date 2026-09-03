import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type {
  BotDefinitionDescriptor,
  GraphTemplateRead
} from '$lib/api/generated';

import {
  TEST_GRAPH,
  TEST_GRAPH_CATALOG,
  THRESHOLD_BUY_GRAPH
} from '$lib/catalog/nodeGraphTestFixtures';
import { GRAPH_VALIDATION_COPY } from '$lib/catalog/graphValidation';
import { GRAPH_SCALAR_TYPE } from '$lib/catalog/graphContracts';
import {
  BOT_DEFINITION_LABEL,
  SELECTION_MODE
} from '$lib/catalog/schema';

const mocks = vi.hoisted(() => ({
  createTemplate: vi.fn(),
  listDefinitions: vi.fn(),
  listTemplates: vi.fn(),
  updateTemplate: vi.fn()
}));

vi.mock('$lib/api/generated', () => ({
  createGraphTemplateApiV1GraphTemplatesPost: mocks.createTemplate,
  listBotDefinitionsApiV1BotDefinitionsGet: mocks.listDefinitions,
  listGraphTemplatesApiV1GraphTemplatesGet: mocks.listTemplates,
  updateGraphTemplateApiV1GraphTemplatesTemplateIdPatch: mocks.updateTemplate
}));

import Page from './+page.svelte';
import { GRAPH_TEMPLATE_COPY } from './copy';
import { GRAPH_TEMPLATE_NAME_MAX_LENGTH } from './contracts';

const TEMPLATE = {
  id: 'aaaaaaaa-0000-0000-0000-000000000001',
  name: 'Original template',
  graph: TEST_GRAPH,
  created_at: '2026-08-30T00:00:00Z',
  updated_at: '2026-08-30T00:00:00Z'
} satisfies GraphTemplateRead;

const GRAPH_CAPABLE_DEFINITION = {
  definition_id: 'graph-definition',
  display_name: 'Graph bot',
  description: 'Graph test definition.',
  label: BOT_DEFINITION_LABEL.STANDARD,
  market_selection: SELECTION_MODE.USER_CONFIGURED,
  wallet_selection: SELECTION_MODE.ABSENT,
  input_schema: {},
  graph_catalog: TEST_GRAPH_CATALOG,
  starter_graph: TEST_GRAPH
} satisfies BotDefinitionDescriptor;

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('graph-template page', () => {
  it('creates, edits, reloads, and resets a connected threshold-buy graph', async () => {
    const connectedDefinition = {
      ...GRAPH_CAPABLE_DEFINITION,
      starter_graph: THRESHOLD_BUY_GRAPH
    } satisfies BotDefinitionDescriptor;
    mocks.listDefinitions.mockResolvedValue({ data: [connectedDefinition] });
    mocks.listTemplates.mockResolvedValue({ data: [] });
    mocks.createTemplate.mockImplementation(async ({ body }) => ({
      data: {
        ...TEMPLATE,
        name: body.name,
        graph: body.graph
      }
    }));
    render(Page);

    expect(
      await screen.findByText(
        (_content, element) => element?.textContent === '5 nodes'
      )
    ).toBeTruthy();
    expect(
      screen.getByText(
        (_content, element) => element?.textContent === '6 connections'
      )
    ).toBeTruthy();
    const threshold = screen.getByDisplayValue('0.5500');
    await fireEvent.change(threshold, { target: { value: '0.6000' } });
    await fireEvent.input(screen.getByLabelText(GRAPH_TEMPLATE_COPY.NAME), {
      target: { value: 'Threshold buyer' }
    });
    await fireEvent.click(
      screen.getByRole('button', { name: GRAPH_TEMPLATE_COPY.CREATE })
    );

    await waitFor(() => {
      const request = mocks.createTemplate.mock.calls[0][0];
      expect(request.body.graph.edges).toEqual(THRESHOLD_BUY_GRAPH.edges);
      expect(request.body.graph.nodes).toContainEqual(
        expect.objectContaining({
          id: 'constant-threshold',
          data: {
            scalar_type: GRAPH_SCALAR_TYPE.decimal,
            value: '0.6000'
          }
        })
      );
    });

    await fireEvent.change(screen.getByDisplayValue('0.6000'), {
      target: { value: '0.7000' }
    });
    await fireEvent.click(
      screen.getByRole('button', { name: GRAPH_TEMPLATE_COPY.NEW })
    );
    expect(screen.getByDisplayValue('0.5500')).toBeTruthy();

    await fireEvent.click(
      screen.getByRole('button', { name: 'Threshold buyer' })
    );
    expect(screen.getByDisplayValue('0.6000')).toBeTruthy();
    expect(
      screen.getByText(
        (_content, element) => element?.textContent === '6 connections'
      )
    ).toBeTruthy();
  });

  it('edits and saves the selected reusable template', async () => {
    mocks.listDefinitions.mockResolvedValue({
      data: [GRAPH_CAPABLE_DEFINITION]
    });
    mocks.listTemplates.mockResolvedValue({ data: [TEMPLATE] });
    mocks.updateTemplate.mockResolvedValue({
      data: { ...TEMPLATE, name: 'Edited template' }
    });
    render(Page);

    const name = await screen.findByLabelText(GRAPH_TEMPLATE_COPY.NAME);
    await fireEvent.input(name, { target: { value: 'Edited template' } });
    await fireEvent.click(
      screen.getByRole('button', { name: GRAPH_TEMPLATE_COPY.SAVE })
    );

    await waitFor(() => {
      expect(mocks.updateTemplate).toHaveBeenCalledWith({
        path: { template_id: TEMPLATE.id },
        body: { name: 'Edited template', graph: TEST_GRAPH },
        throwOnError: true
      });
    });
  });

  it('creates a new reusable graph template', async () => {
    mocks.listDefinitions.mockResolvedValue({ data: [GRAPH_CAPABLE_DEFINITION] });
    mocks.listTemplates.mockResolvedValue({ data: [] });
    mocks.createTemplate.mockResolvedValue({ data: TEMPLATE });
    render(Page);

    await fireEvent.input(await screen.findByLabelText(GRAPH_TEMPLATE_COPY.NAME), {
      target: { value: TEMPLATE.name }
    });
    await fireEvent.click(
      screen.getByRole('button', { name: GRAPH_TEMPLATE_COPY.CREATE })
    );

    await waitFor(() => {
      expect(mocks.createTemplate).toHaveBeenCalledWith({
        body: { name: TEMPLATE.name, graph: TEST_GRAPH },
        throwOnError: true
      });
    });
  });

  it('explains a missing template name under the field', async () => {
    mocks.listDefinitions.mockResolvedValue({ data: [GRAPH_CAPABLE_DEFINITION] });
    mocks.listTemplates.mockResolvedValue({ data: [] });
    render(Page);

    await fireEvent.click(
      await screen.findByRole('button', { name: GRAPH_TEMPLATE_COPY.CREATE })
    );

    const name = screen.getByLabelText(GRAPH_TEMPLATE_COPY.NAME);
    expect(screen.getByText(GRAPH_TEMPLATE_COPY.NAME_REQUIRED)).toBeTruthy();
    expect(name.getAttribute('aria-invalid')).toBe('true');
    expect(document.activeElement).toBe(name);
    expect(mocks.createTemplate).not.toHaveBeenCalled();
  });

  it('enforces the generated template-name limit before saving', async () => {
    mocks.listDefinitions.mockResolvedValue({ data: [GRAPH_CAPABLE_DEFINITION] });
    mocks.listTemplates.mockResolvedValue({ data: [] });
    render(Page);

    const name = await screen.findByLabelText(GRAPH_TEMPLATE_COPY.NAME);
    expect(name.getAttribute('maxlength')).toBe(String(GRAPH_TEMPLATE_NAME_MAX_LENGTH));
    await fireEvent.input(name, {
      target: { value: 'x'.repeat(GRAPH_TEMPLATE_NAME_MAX_LENGTH + 1) }
    });
    await fireEvent.click(
      screen.getByRole('button', { name: GRAPH_TEMPLATE_COPY.CREATE })
    );

    expect(
      screen.getByText(GRAPH_TEMPLATE_COPY.NAME_TOO_LONG(GRAPH_TEMPLATE_NAME_MAX_LENGTH))
    ).toBeTruthy();
    expect(mocks.createTemplate).not.toHaveBeenCalled();
  });

  it('resets an existing selection before creating a new template', async () => {
    mocks.listDefinitions.mockResolvedValue({ data: [GRAPH_CAPABLE_DEFINITION] });
    mocks.listTemplates.mockResolvedValue({ data: [TEMPLATE] });
    mocks.createTemplate.mockResolvedValue({
      data: {
        ...TEMPLATE,
        id: 'bbbbbbbb-0000-0000-0000-000000000001',
        name: 'Fresh template'
      }
    });
    render(Page);

    await screen.findByDisplayValue(TEMPLATE.name);
    await fireEvent.click(
      screen.getByRole('button', { name: GRAPH_TEMPLATE_COPY.NEW })
    );
    const name = screen.getByLabelText(
      GRAPH_TEMPLATE_COPY.NAME
    ) as HTMLInputElement;
    expect(name.value).toBe('');
    await fireEvent.input(name, { target: { value: 'Fresh template' } });
    await fireEvent.click(
      screen.getByRole('button', { name: GRAPH_TEMPLATE_COPY.CREATE })
    );

    await waitFor(() => {
      expect(mocks.createTemplate).toHaveBeenCalledWith({
        body: { name: 'Fresh template', graph: TEST_GRAPH },
        throwOnError: true
      });
    });
    expect(mocks.updateTemplate).not.toHaveBeenCalled();
  });

  it('reports missing graph capability and load failures', async () => {
    mocks.listDefinitions.mockResolvedValueOnce({
      data: [{ ...GRAPH_CAPABLE_DEFINITION, graph_catalog: undefined, starter_graph: undefined }]
    });
    mocks.listTemplates.mockResolvedValueOnce({ data: [] });
    const missingCapability = render(Page);

    expect(
      await screen.findByText(GRAPH_TEMPLATE_COPY.MISSING_CAPABILITY)
    ).toBeTruthy();
    missingCapability.unmount();

    mocks.listDefinitions.mockRejectedValueOnce(new Error('offline'));
    mocks.listTemplates.mockResolvedValueOnce({ data: [] });
    render(Page);
    expect((await screen.findByRole('alert')).textContent).toContain(
      GRAPH_TEMPLATE_COPY.LOAD_ERROR
    );
  });

  it('keeps the editor visible when a template save fails', async () => {
    mocks.listDefinitions.mockResolvedValue({ data: [GRAPH_CAPABLE_DEFINITION] });
    mocks.listTemplates.mockResolvedValue({ data: [TEMPLATE] });
    mocks.updateTemplate.mockRejectedValue({
      detail: 'graph template name already exists'
    });
    render(Page);

    await fireEvent.click(
      await screen.findByRole('button', { name: GRAPH_TEMPLATE_COPY.SAVE })
    );

    const name = screen.getByLabelText(
      GRAPH_TEMPLATE_COPY.NAME
    ) as HTMLInputElement;
    expect(await screen.findByText('Graph template name already exists.')).toBeTruthy();
    expect(name.value).toBe(TEMPLATE.name);
    expect(name.getAttribute('aria-invalid')).toBe('true');
    expect(document.activeElement).toBe(name);
  });

  it('shows graph validation details next to the canvas', async () => {
    mocks.listDefinitions.mockResolvedValue({ data: [GRAPH_CAPABLE_DEFINITION] });
    mocks.listTemplates.mockResolvedValue({ data: [TEMPLATE] });
    mocks.updateTemplate.mockRejectedValue({
      detail: [
        {
          loc: ['body', 'graph'],
          msg: 'Value error, graph input cardinality is invalid',
          type: 'value_error'
        }
      ]
    });
    render(Page);

    await fireEvent.click(
      await screen.findByRole('button', { name: GRAPH_TEMPLATE_COPY.SAVE })
    );

    const summary = await screen.findByRole('alert');
    expect(
      screen.getByRole('heading', { name: GRAPH_VALIDATION_COPY.TITLE })
    ).toBeTruthy();
    expect(summary.textContent).toContain(GRAPH_VALIDATION_COPY.STRUCTURE);
    expect(summary.textContent).toContain('Graph input cardinality is invalid.');
    expect(document.activeElement).toBe(summary);
    expect(screen.queryByText(GRAPH_TEMPLATE_COPY.SAVE_ERROR)).toBeNull();
  });

  it('keeps create mode visible when a new template save fails', async () => {
    mocks.listDefinitions.mockResolvedValue({ data: [GRAPH_CAPABLE_DEFINITION] });
    mocks.listTemplates.mockResolvedValue({ data: [] });
    mocks.createTemplate.mockRejectedValue(new Error('write failed'));
    render(Page);

    const name = await screen.findByLabelText(GRAPH_TEMPLATE_COPY.NAME);
    await fireEvent.input(name, { target: { value: 'Unsaved template' } });
    await fireEvent.click(
      screen.getByRole('button', { name: GRAPH_TEMPLATE_COPY.CREATE })
    );

    expect((await screen.findByRole('alert')).textContent).toContain(
      GRAPH_TEMPLATE_COPY.SAVE_ERROR
    );
    expect((name as HTMLInputElement).value).toBe('Unsaved template');
    expect(
      screen.getByRole('button', { name: GRAPH_TEMPLATE_COPY.CREATE })
    ).toBeTruthy();
  });
});
