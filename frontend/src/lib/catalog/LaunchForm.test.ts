import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { BotDefinitionDescriptor } from '$lib/api/generated';
import LaunchForm from './LaunchForm.svelte';
import {
  SELECTION_MODE,
  WIDGET_KIND,
  WIDGET_SCHEMA_KEY
} from './schema';

const WALLET = '0x0000000000000000000000000000000000000001';

afterEach(cleanup);

function descriptor(
  overrides: Partial<BotDefinitionDescriptor> = {}
): BotDefinitionDescriptor {
  return {
    definition_id: 'schema-driven-test',
    version: 1,
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
