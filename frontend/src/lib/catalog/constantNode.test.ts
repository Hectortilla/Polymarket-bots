import { describe, expect, it } from 'vitest';

import type { GraphConstantDescriptor } from '$lib/api/generated';
import {
  constantDataFromDescriptor,
  constantDataFromInput,
  constantInput
} from './constantNode';
import { DECIMAL_CONSTANT } from './nodeGraphTestFixtures';
import { GRAPH_SCALAR_TYPE } from './graphContracts';

describe('constant node inputs', () => {
  it('preserves boolean, integer, decimal, and string values', () => {
    const input = document.createElement('input');

    input.checked = true;
    expect(constantDataFromInput(GRAPH_SCALAR_TYPE.boolean, input)).toEqual({
      scalar_type: GRAPH_SCALAR_TYPE.boolean,
      value: true
    });

    input.type = 'number';
    input.value = '12';
    expect(constantDataFromInput(GRAPH_SCALAR_TYPE.integer, input)).toEqual({
      scalar_type: GRAPH_SCALAR_TYPE.integer,
      value: 12
    });
    input.value = '1.5';
    expect(constantDataFromInput(GRAPH_SCALAR_TYPE.integer, input)).toBeNull();

    input.type = 'text';
    input.value = '000.5400';
    expect(constantDataFromInput(GRAPH_SCALAR_TYPE.decimal, input)).toEqual({
      scalar_type: GRAPH_SCALAR_TYPE.decimal,
      value: '000.5400'
    });
    expect(constantDataFromInput(GRAPH_SCALAR_TYPE.string, input)).toEqual({
      scalar_type: GRAPH_SCALAR_TYPE.string,
      value: '000.5400'
    });
  });

  it('owns the scalar editor controls in one exhaustive map', () => {
    expect(constantInput(GRAPH_SCALAR_TYPE.boolean)).toEqual({ type: 'checkbox' });
    expect(constantInput(GRAPH_SCALAR_TYPE.integer)).toEqual({ type: 'number', step: '1' });
    expect(constantInput(GRAPH_SCALAR_TYPE.decimal)).toEqual({ type: 'text' });
    expect(constantInput(GRAPH_SCALAR_TYPE.string)).toEqual({ type: 'text' });
  });

  it.each([
    [GRAPH_SCALAR_TYPE.boolean, true],
    [GRAPH_SCALAR_TYPE.integer, 12],
    [GRAPH_SCALAR_TYPE.decimal, '000.5400'],
    [GRAPH_SCALAR_TYPE.string, 'hello']
  ] as const)('normalizes the %s catalog default', (scalarType, value) => {
    expect(
      constantDataFromDescriptor(descriptor(scalarType, value))
    ).toEqual({ scalar_type: scalarType, value });
  });

  it('rejects a catalog default that disagrees with its scalar type', () => {
    expect(() =>
      constantDataFromDescriptor(descriptor(GRAPH_SCALAR_TYPE.boolean, 'true'))
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
