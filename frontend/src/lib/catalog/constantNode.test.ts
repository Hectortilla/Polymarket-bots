import { describe, expect, it } from 'vitest';

import type { GraphConstantDescriptor } from '$lib/api/generated';
import {
  constantDataFromDescriptor,
  constantDataFromInput,
  constantInput
} from './constantNode';
import { DECIMAL_CONSTANT } from './nodeGraphTestFixtures';

describe('constant node inputs', () => {
  it('preserves boolean, integer, decimal, and string values', () => {
    const input = document.createElement('input');

    input.checked = true;
    expect(constantDataFromInput('boolean', input)).toEqual({
      scalar_type: 'boolean',
      value: true
    });

    input.type = 'number';
    input.value = '12';
    expect(constantDataFromInput('integer', input)).toEqual({
      scalar_type: 'integer',
      value: 12
    });
    input.value = '1.5';
    expect(constantDataFromInput('integer', input)).toBeNull();

    input.type = 'text';
    input.value = '000.5400';
    expect(constantDataFromInput('decimal', input)).toEqual({
      scalar_type: 'decimal',
      value: '000.5400'
    });
    expect(constantDataFromInput('string', input)).toEqual({
      scalar_type: 'string',
      value: '000.5400'
    });
  });

  it('owns the scalar editor controls in one exhaustive map', () => {
    expect(constantInput('boolean')).toEqual({ type: 'checkbox' });
    expect(constantInput('integer')).toEqual({ type: 'number', step: '1' });
    expect(constantInput('decimal')).toEqual({ type: 'text' });
    expect(constantInput('string')).toEqual({ type: 'text' });
  });

  it.each([
    ['boolean', true],
    ['integer', 12],
    ['decimal', '000.5400'],
    ['string', 'hello']
  ] as const)('normalizes the %s catalog default', (scalarType, value) => {
    expect(
      constantDataFromDescriptor(descriptor(scalarType, value))
    ).toEqual({ scalar_type: scalarType, value });
  });

  it('rejects a catalog default that disagrees with its scalar type', () => {
    expect(() =>
      constantDataFromDescriptor(descriptor('boolean', 'true'))
    ).toThrow('Invalid boolean constant default');
  });
});

function descriptor(
  scalarType: GraphConstantDescriptor['scalar_type'],
  defaultValue: GraphConstantDescriptor['default_value']
): GraphConstantDescriptor {
  return {
    ...DECIMAL_CONSTANT,
    scalar_type: scalarType,
    default_value: defaultValue,
    output: { ...DECIMAL_CONSTANT.output, scalar_type: scalarType }
  };
}
