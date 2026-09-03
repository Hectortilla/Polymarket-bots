import { describe, expect, it } from 'vitest';

import type { BotDefinitionDescriptor, PaperRunConfig } from '$lib/api/generated';
import runtimeContract from '$lib/runtimeContract.fixture.json';
import {
  BOT_DEFINITION_LABEL,
  launchInputsFromConfig,
  launchValidator,
  SELECTION_MODE,
  WIDGET_KIND,
  WIDGET_SCHEMA_KEY
} from './schema';

type StreamRelation = PaperRunConfig['stream_rules'][number]['relation'];

describe('launch schema validation', () => {
  it('validates OpenAPI discriminated unions through their oneOf contract', () => {
    const descriptor: BotDefinitionDescriptor = {
      definition_id: 'discriminator-test',
      display_name: 'Discriminator test',
      description: 'Test definition',
      label: BOT_DEFINITION_LABEL.EXAMPLE,
      market_selection: SELECTION_MODE.ABSENT,
      wallet_selection: SELECTION_MODE.ABSENT,
      input_schema: {
        type: 'object',
        additionalProperties: false,
        required: ['value'],
        properties: {
          value: {
            discriminator: {
              propertyName: 'type',
              mapping: { constant: '#/$defs/ConstantValue' }
            },
            oneOf: [{ $ref: '#/$defs/ConstantValue' }]
          }
        },
        $defs: {
          ConstantValue: {
            type: 'object',
            additionalProperties: false,
            required: ['type'],
            properties: { type: { type: 'string', const: 'constant' } }
          }
        }
      }
    };

    const validator = launchValidator(descriptor);

    expect(validator({ value: { type: 'constant' } })).toBe(true);
    expect(validator({ value: { type: 'other' } })).toBe(false);
  });

  it('restores editable selector inputs from a saved resolved bot config', () => {
    const descriptor: BotDefinitionDescriptor = {
      definition_id: 'saved-bot',
      display_name: 'Saved bot',
      description: 'Test definition',
      label: BOT_DEFINITION_LABEL.STANDARD,
      market_selection: SELECTION_MODE.USER_CONFIGURED,
      wallet_selection: SELECTION_MODE.USER_CONFIGURED,
      input_schema: {
        type: 'object',
        properties: {
          name: { type: 'string' },
          market_slugs: {
            type: 'array',
            [WIDGET_SCHEMA_KEY]: WIDGET_KIND.MARKET_SLUGS
          },
          wallet_addresses: {
            type: 'array',
            [WIDGET_SCHEMA_KEY]: WIDGET_KIND.WALLET_ADDRESSES
          },
          max_order_size: {
            type: 'string',
            [WIDGET_SCHEMA_KEY]: WIDGET_KIND.DECIMAL
          }
        }
      }
    };
    const config: PaperRunConfig = {
      name: 'Reusable bot',
      stream_rules: [{
        relation: runtimeContract.streamRelation.INDEPENDENT as StreamRelation,
        market_slugs: ['market-a'],
        wallet_addresses: ['0x0000000000000000000000000000000000000001']
      }],
      data_trades_budget_per_10s: 100,
      max_order_size: '2.500',
      max_slippage_pct: '0.01',
      paper_latency_ms: 0,
      paper_latency_jitter_ms: 0,
      event_max_age_ms: 1000,
      paper_portfolio_usdc: '1000'
    };

    expect(launchInputsFromConfig(descriptor, config)).toEqual({
      name: 'Reusable bot',
      market_slugs: ['market-a'],
      wallet_addresses: ['0x0000000000000000000000000000000000000001'],
      max_order_size: '2.500'
    });
  });
});
