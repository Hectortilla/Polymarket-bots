import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { BotDefinitionDescriptor, NodeGraph } from '$lib/api/generated';
import LaunchForm from './LaunchForm.svelte';
import {
  SELECTION_MODE,
  WIDGET_KIND,
  WIDGET_SCHEMA_KEY
} from './schema';
import { canvasNodes, createConstantNode, createTriggerNode } from './nodeGraph';
import {
  BOOLEAN_CONSTANT,
  BUY_ACTION,
  DECIMAL_CONSTANT,
  LESS_THAN_OR_EQUAL,
  ON_START_TRIGGER,
  ON_WALLET_TRADE_TRIGGER,
  TEST_GRAPH,
  TEST_GRAPH_CATALOG,
  THRESHOLD_BUY_GRAPH,
  graphDescriptor
} from './nodeGraphTestFixtures';

const WALLET = '0x0000000000000000000000000000000000000001';

afterEach(cleanup);

function descriptor(
  overrides: Partial<BotDefinitionDescriptor> = {}
): BotDefinitionDescriptor {
  return {
    definition_id: 'schema-driven-test',
    display_name: 'Schema driven test',
    description: 'Test definition',
    label: 'example',
    market_selection: SELECTION_MODE.botManaged,
    wallet_selection: SELECTION_MODE.userConfigured,
    input_schema: {
      type: 'object',
      additionalProperties: false,
      required: ['name', 'max_order_size', 'market_slugs', 'wallet_addresses'],
      properties: {
        name: { type: 'string', minLength: 1 },
        max_order_size: {
          anyOf: [{ type: 'number' }, { type: 'string' }],
          [WIDGET_SCHEMA_KEY]: WIDGET_KIND.decimal
        },
        market_slugs: {
          type: 'array',
          items: { type: 'string' },
          [WIDGET_SCHEMA_KEY]: WIDGET_KIND.marketSlugs
        },
        wallet_addresses: {
          type: 'array',
          minItems: 1,
          items: { type: 'string' },
          [WIDGET_SCHEMA_KEY]: WIDGET_KIND.walletAddresses
        }
      }
    },
    ...overrides
  };
}

describe('LaunchForm', () => {
  it('submits schema fields while preserving decimals and omitting bot-managed selectors', async () => {
    const submit = vi.fn();
    render(LaunchForm, { descriptor: descriptor(), onsubmit: submit });

    await fireEvent.input(screen.getByLabelText('Name'), {
      target: { value: 'Exact decimal run' }
    });
    await fireEvent.input(screen.getByLabelText('Max order size'), {
      target: { value: '0001.2300' }
    });
    await fireEvent.input(screen.getByLabelText('Wallet addresses'), {
      target: { value: WALLET }
    });
    expect(screen.queryByLabelText('Market slugs')).toBeNull();

    await fireEvent.click(screen.getByRole('button', { name: 'Start paper run' }));

    expect(submit).toHaveBeenCalledWith({
      name: 'Exact decimal run',
      max_order_size: '0001.2300',
      wallet_addresses: [WALLET]
    });
  });

  it('renders another supported catalog schema without definition-specific code', async () => {
    const submit = vi.fn();
    const extraDefinition = descriptor({
      definition_id: 'new-supported-definition',
      market_selection: SELECTION_MODE.userConfigured,
      input_schema: {
        type: 'object',
        additionalProperties: false,
        required: ['name', 'market_slugs', 'wallet_addresses', 'stream_rules'],
        properties: {
          name: { type: 'string' },
          market_slugs: {
            type: 'array',
            items: { type: 'string' },
            [WIDGET_SCHEMA_KEY]: WIDGET_KIND.marketSlugs
          },
          wallet_addresses: {
            type: 'array',
            items: { type: 'string' },
            [WIDGET_SCHEMA_KEY]: WIDGET_KIND.walletAddresses
          },
          stream_rules: {
            type: 'array',
            items: { type: 'object' },
            [WIDGET_SCHEMA_KEY]: WIDGET_KIND.streamRules
          }
        }
      }
    });
    render(LaunchForm, { descriptor: extraDefinition, onsubmit: submit });

    await fireEvent.input(screen.getByLabelText('Name'), {
      target: { value: 'New definition run' }
    });
    await fireEvent.input(screen.getByLabelText('Market slugs'), {
      target: { value: 'btc-updown-5m-test' }
    });
    await fireEvent.input(screen.getByLabelText('Wallet addresses'), {
      target: { value: WALLET }
    });
    await fireEvent.input(screen.getByLabelText('Stream rules'), {
      target: { value: '[{"relation":"independent"}]' }
    });
    await fireEvent.click(screen.getByRole('button', { name: 'Start paper run' }));

    expect(submit).toHaveBeenCalledWith({
      name: 'New definition run',
      market_slugs: ['btc-updown-5m-test'],
      wallet_addresses: [WALLET],
      stream_rules: [{ relation: 'independent' }]
    });
  });

  it('binds a metadata-driven node graph into the submitted inputs', async () => {
    const submit = vi.fn();
    const nodeDefinition = graphDescriptor(TEST_GRAPH);
    render(LaunchForm, { descriptor: nodeDefinition, onsubmit: submit });

    await fireEvent.input(screen.getByLabelText('Name'), {
      target: { value: 'Visual observer' }
    });
    await fireEvent.input(screen.getByLabelText('Market slugs'), {
      target: { value: 'example-market' }
    });
    await fireEvent.click(screen.getByRole('button', { name: 'Add node' }));
    expect(screen.getByRole('dialog', { name: 'Add graph node' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Triggers' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Values' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Logic' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Actions' })).toBeTruthy();
    const nodeSearch = screen.getByLabelText('Find a node');
    await fireEvent.input(nodeSearch, { target: { value: 'decimal' } });
    expect(
      screen.getByRole('button', { name: `Add ${DECIMAL_CONSTANT.display_name}` })
    ).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Add on_book' })).toBeNull();
    await fireEvent.input(nodeSearch, { target: { value: '' } });
    expect(
      screen.getByRole('button', { name: 'Add on_book' }).hasAttribute('disabled')
    ).toBe(true);
    const contextHandle = document.querySelector('[data-handleid="context"]');
    expect(contextHandle).not.toBeNull();
    expect(contextHandle?.classList.contains('connectable')).toBe(false);
    const bidsHandle = document.querySelector('[data-handleid="field:bids"]');
    expect(bidsHandle?.classList.contains('connectable')).toBe(false);
    expect(document.querySelector('[data-handleid="field:asks"]')).not.toBeNull();
    const askPriceHandle = document.querySelector(
      '[data-handleid="field:best_ask.price"]'
    );
    expect(askPriceHandle?.classList.contains('connectable')).toBe(true);
    expect(document.querySelector('.outputs.nowheel')).not.toBeNull();
    expect(
      document.querySelector('.node-graph-controls.horizontal')
    ).not.toBeNull();
    await fireEvent.click(
      screen.getByRole('button', { name: 'Add on_wallet_trade' })
    );
    expect(screen.queryByRole('dialog', { name: 'Add graph node' })).toBeNull();
    expect(screen.getByLabelText('on_wallet_trade trigger node')).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: 'Start paper run' }));

    expect(submit).toHaveBeenCalledWith({
      name: 'Visual observer',
      market_slugs: ['example-market'],
      graph: {
        ...TEST_GRAPH,
        nodes: [
          TEST_GRAPH.nodes[0],
          createTriggerNode(
            canvasNodes(TEST_GRAPH),
            ON_WALLET_TRADE_TRIGGER
          )
        ]
      }
    });
  });

  it('resets canvas-owned graph state when the definition changes', async () => {
    const submit = vi.fn();
    const nextGraph: NodeGraph = {
      ...TEST_GRAPH,
      nodes: [createTriggerNode([], ON_START_TRIGGER) as NodeGraph['nodes'][number]]
    };
    const view = render(LaunchForm, {
      descriptor: graphDescriptor(TEST_GRAPH),
      onsubmit: submit
    });

    await fireEvent.click(screen.getByRole('button', { name: 'Add node' }));
    await fireEvent.click(
      screen.getByRole('button', { name: 'Add on_wallet_trade' })
    );
    await view.rerender({
      descriptor: graphDescriptor(nextGraph, 'next-node-based-test'),
      onsubmit: submit
    });
    await fireEvent.input(screen.getByLabelText('Name'), {
      target: { value: 'Next observer' }
    });
    await fireEvent.input(screen.getByLabelText('Market slugs'), {
      target: { value: 'next-market' }
    });
    await fireEvent.click(screen.getByRole('button', { name: 'Start paper run' }));

    expect(submit).toHaveBeenCalledWith({
      name: 'Next observer',
      market_slugs: ['next-market'],
      graph: nextGraph
    });
  });

  it('reloads and submits the complete metadata-built threshold BUY graph', async () => {
    const submit = vi.fn();
    render(LaunchForm, {
      descriptor: graphDescriptor(THRESHOLD_BUY_GRAPH),
      onsubmit: submit
    });

    expect(
      screen.getAllByLabelText(`${DECIMAL_CONSTANT.display_name} node`)
    ).toHaveLength(2);
    expect(
      screen.getByLabelText(
        `${LESS_THAN_OR_EQUAL.display_name} comparison node`
      )
    ).toBeTruthy();
    expect(
      screen.getByLabelText(`${BUY_ACTION.display_name} broker action node`)
    ).toBeTruthy();
    expect(
      document.querySelector(
        `[data-handleid="${BUY_ACTION.inputs[0].handle_id}"]`
      )
    ).not.toBeNull();
    await fireEvent.change(
      screen.getAllByLabelText(DECIMAL_CONSTANT.output.display_name)[0],
      {
        target: { value: '000.5400' }
      }
    );
    await fireEvent.input(screen.getByLabelText('Name'), {
      target: { value: 'Threshold BUY' }
    });
    await fireEvent.input(screen.getByLabelText('Market slugs'), {
      target: { value: 'example-market' }
    });
    await fireEvent.click(screen.getByRole('button', { name: 'Start paper run' }));

    expect(submit).toHaveBeenCalledWith({
      name: 'Threshold BUY',
      market_slugs: ['example-market'],
      graph: {
        ...THRESHOLD_BUY_GRAPH,
        nodes: THRESHOLD_BUY_GRAPH.nodes.map((node) =>
          node.id === 'constant-threshold'
            ? { ...node, data: { scalar_type: 'decimal', value: '000.5400' } }
            : node
        )
      }
    });
  });

  it('renders and edits the catalog-described boolean constant control', async () => {
    const submit = vi.fn();
    const constantNode = createConstantNode(
      canvasNodes(TEST_GRAPH),
      BOOLEAN_CONSTANT
    );
    const graph: NodeGraph = {
      ...TEST_GRAPH,
      nodes: [
        ...TEST_GRAPH.nodes,
        constantNode as NodeGraph['nodes'][number]
      ]
    };
    render(LaunchForm, { descriptor: graphDescriptor(graph), onsubmit: submit });

    const input = screen.getByLabelText(
      BOOLEAN_CONSTANT.output.display_name
    ) as HTMLInputElement;
    expect(input.type).toBe('checkbox');
    expect(input.checked).toBe(false);
    await fireEvent.click(input);
    await fireEvent.input(screen.getByLabelText('Name'), {
      target: { value: 'Boolean constant' }
    });
    await fireEvent.input(screen.getByLabelText('Market slugs'), {
      target: { value: 'example-market' }
    });
    await fireEvent.click(screen.getByRole('button', { name: 'Start paper run' }));

    expect(submit).toHaveBeenCalledWith({
      name: 'Boolean constant',
      market_slugs: ['example-market'],
      graph: {
        ...graph,
        nodes: graph.nodes.map((node) =>
          node.id === constantNode.id
            ? {
                ...node,
                data: { scalar_type: BOOLEAN_CONSTANT.scalar_type, value: true }
              }
            : node
        )
      }
    });
  });

  it('resolves referenced field schemas and defaults', async () => {
    const submit = vi.fn();
    const referencedDefinition = descriptor({
      input_schema: {
        type: 'object',
        additionalProperties: false,
        required: ['name', 'attempts'],
        $defs: {
          RunName: { type: 'string', title: 'Run name', minLength: 1 },
          Attempts: { type: 'integer', title: 'Attempts', default: 2 }
        },
        properties: {
          name: { $ref: '#/$defs/RunName' },
          attempts: { $ref: '#/$defs/Attempts', default: 3 }
        }
      }
    });
    render(LaunchForm, { descriptor: referencedDefinition, onsubmit: submit });

    await fireEvent.input(screen.getByLabelText('Run name'), {
      target: { value: 'Referenced run' }
    });
    expect((screen.getByLabelText('Attempts') as HTMLInputElement).value).toBe(
      '3'
    );
    await fireEvent.click(screen.getByRole('button', { name: 'Start paper run' }));

    expect(submit).toHaveBeenCalledWith({ name: 'Referenced run', attempts: 3 });
  });

  it('shows schema feedback and does not submit malformed JSON', async () => {
    const submit = vi.fn();
    const streamDefinition = descriptor({
      market_selection: SELECTION_MODE.userConfigured,
      input_schema: {
        type: 'object',
        additionalProperties: false,
        required: ['stream_rules'],
        properties: {
          stream_rules: {
            type: 'array',
            items: { type: 'object' },
            [WIDGET_SCHEMA_KEY]: WIDGET_KIND.streamRules
          }
        }
      }
    });
    render(LaunchForm, { descriptor: streamDefinition, onsubmit: submit });

    await fireEvent.input(screen.getByLabelText('Stream rules'), {
      target: { value: '{broken' }
    });
    await fireEvent.click(screen.getByRole('button', { name: 'Start paper run' }));

    expect(screen.getByRole('alert').textContent).toContain('must be array');
    expect(submit).not.toHaveBeenCalled();
  });

  it('explains and omits absent selectors', async () => {
    const submit = vi.fn();
    const absentSelectors = descriptor({
      market_selection: SELECTION_MODE.absent,
      wallet_selection: SELECTION_MODE.absent
    });
    render(LaunchForm, { descriptor: absentSelectors, onsubmit: submit });

    expect(screen.getByText('Market selection is not used by this bot.')).toBeTruthy();
    expect(screen.getByText('Wallet selection is not used by this bot.')).toBeTruthy();
    expect(screen.queryByLabelText('Market slugs')).toBeNull();
    expect(screen.queryByLabelText('Wallet addresses')).toBeNull();

    await fireEvent.input(screen.getByLabelText('Name'), {
      target: { value: 'No selectors' }
    });
    await fireEvent.input(screen.getByLabelText('Max order size'), {
      target: { value: '1.25' }
    });
    await fireEvent.click(screen.getByRole('button', { name: 'Start paper run' }));

    expect(submit).toHaveBeenCalledWith({
      name: 'No selectors',
      max_order_size: '1.25'
    });
  });
});
