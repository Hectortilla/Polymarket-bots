import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { BotDefinitionDescriptor } from '$lib/api/generated';
import runtimeContract from '$lib/runtimeContract.fixture.json';
import LaunchForm from './LaunchForm.svelte';
import { LAUNCH_FORM_COPY } from './copy';
import {
  BOT_DEFINITION_LABEL,
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
    display_name: 'Schema driven test',
    description: 'Test definition',
    label: BOT_DEFINITION_LABEL.EXAMPLE,
    market_selection: SELECTION_MODE.BOT_MANAGED,
    wallet_selection: SELECTION_MODE.USER_CONFIGURED,
    input_schema: {
      type: 'object',
      additionalProperties: false,
      required: ['name', 'max_order_size', 'market_slugs', 'wallet_addresses'],
      properties: {
        name: { type: 'string', minLength: 1 },
        max_order_size: {
          anyOf: [{ type: 'number' }, { type: 'string' }],
          [WIDGET_SCHEMA_KEY]: WIDGET_KIND.DECIMAL
        },
        market_slugs: {
          type: 'array',
          items: { type: 'string' },
          [WIDGET_SCHEMA_KEY]: WIDGET_KIND.MARKET_SLUGS
        },
        wallet_addresses: {
          type: 'array',
          minItems: 1,
          items: { type: 'string', pattern: runtimeContract.walletAddressPattern },
          [WIDGET_SCHEMA_KEY]: WIDGET_KIND.WALLET_ADDRESSES
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

    await fireEvent.click(
      screen.getByRole('button', { name: LAUNCH_FORM_COPY.SAVE_BOT })
    );

    expect(submit).toHaveBeenCalledWith({
      name: 'Exact decimal run',
      max_order_size: '0001.2300',
      wallet_addresses: [WALLET]
    });
  });

  it('rejects wallet addresses that violate the generated selector contract', async () => {
    const submit = vi.fn();
    render(LaunchForm, { descriptor: descriptor(), onsubmit: submit });

    await fireEvent.input(screen.getByLabelText('Name'), {
      target: { value: 'Invalid wallet run' }
    });
    await fireEvent.input(screen.getByLabelText('Max order size'), {
      target: { value: '1' }
    });
    await fireEvent.input(screen.getByLabelText('Wallet addresses'), {
      target: { value: 'not-a-wallet' }
    });
    await fireEvent.click(
      screen.getByRole('button', { name: LAUNCH_FORM_COPY.SAVE_BOT })
    );

    expect(submit).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Wallet addresses').getAttribute('aria-invalid'))
      .toBe('true');
  });

  it('renders another supported catalog schema without definition-specific code', async () => {
    const submit = vi.fn();
    const extraDefinition = descriptor({
      definition_id: 'new-supported-definition',
      market_selection: SELECTION_MODE.USER_CONFIGURED,
      input_schema: {
        type: 'object',
        additionalProperties: false,
        required: ['name', 'market_slugs', 'wallet_addresses', 'stream_rules'],
        properties: {
          name: { type: 'string' },
          market_slugs: {
            type: 'array',
            items: { type: 'string' },
            [WIDGET_SCHEMA_KEY]: WIDGET_KIND.MARKET_SLUGS
          },
          wallet_addresses: {
            type: 'array',
            items: { type: 'string' },
            [WIDGET_SCHEMA_KEY]: WIDGET_KIND.WALLET_ADDRESSES
          },
          stream_rules: {
            type: 'array',
            items: { type: 'object' },
            [WIDGET_SCHEMA_KEY]: WIDGET_KIND.STREAM_RULES
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
      target: {
        value: JSON.stringify([{
          relation: runtimeContract.streamRelation.INDEPENDENT
        }])
      }
    });
    await fireEvent.click(
      screen.getByRole('button', { name: LAUNCH_FORM_COPY.SAVE_BOT })
    );

    expect(submit).toHaveBeenCalledWith({
      name: 'New definition run',
      market_slugs: ['btc-updown-5m-test'],
      wallet_addresses: [WALLET],
      stream_rules: [{ relation: runtimeContract.streamRelation.INDEPENDENT }]
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
    await fireEvent.click(
      screen.getByRole('button', { name: LAUNCH_FORM_COPY.SAVE_BOT })
    );

    expect(submit).toHaveBeenCalledWith({ name: 'Referenced run', attempts: 3 });
  });

  it('shows schema feedback and does not submit malformed JSON', async () => {
    const submit = vi.fn();
    const streamDefinition = descriptor({
      market_selection: SELECTION_MODE.USER_CONFIGURED,
      input_schema: {
        type: 'object',
        additionalProperties: false,
        required: ['stream_rules'],
        properties: {
          stream_rules: {
            type: 'array',
            items: { type: 'object' },
            [WIDGET_SCHEMA_KEY]: WIDGET_KIND.STREAM_RULES
          }
        }
      }
    });
    render(LaunchForm, { descriptor: streamDefinition, onsubmit: submit });

    await fireEvent.input(screen.getByLabelText('Stream rules'), {
      target: { value: '{broken' }
    });
    await fireEvent.click(
      screen.getByRole('button', { name: LAUNCH_FORM_COPY.SAVE_BOT })
    );

    const streamRules = screen.getByLabelText('Stream rules');
    expect(screen.getByText('Enter a valid list.')).toBeTruthy();
    expect(streamRules.getAttribute('aria-invalid')).toBe('true');
    expect(streamRules.getAttribute('aria-describedby')).toBe(
      'field-stream_rules-error'
    );
    expect(document.activeElement).toBe(streamRules);
    expect(submit).not.toHaveBeenCalled();
  });

  it('places authoritative server feedback under its field', () => {
    render(LaunchForm, {
      descriptor: descriptor({ wallet_selection: SELECTION_MODE.ABSENT }),
      initialInputs: { name: 'Reserved', max_order_size: '1.0' },
      onsubmit: vi.fn(),
      serverIssues: [{ field: 'name', message: 'This name is already in use.' }]
    });

    const name = screen.getByLabelText('Name');
    expect(screen.getByText('This name is already in use.')).toBeTruthy();
    expect(name.getAttribute('aria-invalid')).toBe('true');
    expect(name.getAttribute('aria-describedby')).toBe('field-name-error');
  });

  it('explains and omits absent selectors', async () => {
    const submit = vi.fn();
    const absentSelectors = descriptor({
      market_selection: SELECTION_MODE.ABSENT,
      wallet_selection: SELECTION_MODE.ABSENT
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
    await fireEvent.click(
      screen.getByRole('button', { name: LAUNCH_FORM_COPY.SAVE_BOT })
    );

    expect(submit).toHaveBeenCalledWith({
      name: 'No selectors',
      max_order_size: '1.25'
    });
  });

  it('hydrates saved inputs, reports edits, and can block running while dirty', async () => {
    const submit = vi.fn();
    const change = vi.fn();
    render(LaunchForm, {
      descriptor: descriptor({ wallet_selection: SELECTION_MODE.ABSENT }),
      initialInputs: { name: 'Saved bot', max_order_size: '2.500' },
      onsubmit: submit,
      onchange: change,
      submitLabel: 'Run bot',
      disabled: true
    });

    expect((screen.getByLabelText('Name') as HTMLInputElement).value).toBe(
      'Saved bot'
    );
    expect(
      (screen.getByLabelText('Max order size') as HTMLInputElement).value
    ).toBe('2.500');
    expect(
      screen.getByRole<HTMLButtonElement>('button', { name: 'Run bot' }).disabled
    ).toBe(true);

    await fireEvent.input(screen.getByLabelText('Name'), {
      target: { value: 'Edited bot' }
    });

    expect(change).toHaveBeenLastCalledWith({
      name: 'Edited bot',
      max_order_size: '2.500'
    });
    expect(submit).not.toHaveBeenCalled();
  });
});
