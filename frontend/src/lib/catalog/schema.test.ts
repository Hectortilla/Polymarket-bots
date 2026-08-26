import { describe, expect, it } from 'vitest';

import type { BotDefinitionDescriptor } from '$lib/api/generated';
import { launchValidator, SELECTION_MODE } from './schema';

describe('launch schema validation', () => {
  it('validates OpenAPI discriminated unions through their oneOf contract', () => {
    const descriptor: BotDefinitionDescriptor = {
      definition_id: 'discriminator-test',
      display_name: 'Discriminator test',
      description: 'Test definition',
      label: 'example',
      market_selection: SELECTION_MODE.absent,
      wallet_selection: SELECTION_MODE.absent,
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
});
