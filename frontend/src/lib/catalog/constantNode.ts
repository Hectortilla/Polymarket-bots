import type {
  GraphConstantDescriptor,
  GraphConstantNodeData
} from '$lib/api/generated';
import { GRAPH_SCALAR_TYPE } from './graphContracts';

type ConstantSpec = {
  input: { type: 'checkbox' | 'number' | 'text'; step?: string };
  fromDefault: (value: unknown) => GraphConstantNodeData | null;
  fromInput: (input: HTMLInputElement) => GraphConstantNodeData | null;
};

const CONSTANT_SPECS = {
  [GRAPH_SCALAR_TYPE.boolean]: {
    input: { type: 'checkbox' },
    fromDefault: (value) =>
      typeof value === 'boolean'
        ? { scalar_type: GRAPH_SCALAR_TYPE.boolean, value }
        : null,
    fromInput: (input) => ({ scalar_type: GRAPH_SCALAR_TYPE.boolean, value: input.checked })
  },
  [GRAPH_SCALAR_TYPE.integer]: {
    input: { type: 'number', step: '1' },
    fromDefault: (value) =>
      typeof value === 'number' && Number.isInteger(value)
        ? { scalar_type: GRAPH_SCALAR_TYPE.integer, value }
        : null,
    fromInput: (input) =>
      Number.isInteger(input.valueAsNumber)
        ? { scalar_type: GRAPH_SCALAR_TYPE.integer, value: input.valueAsNumber }
        : null
  },
  [GRAPH_SCALAR_TYPE.decimal]: {
    input: { type: 'text' },
    fromDefault: (value) =>
      typeof value === 'string'
        ? { scalar_type: GRAPH_SCALAR_TYPE.decimal, value }
        : null,
    fromInput: (input) => ({ scalar_type: GRAPH_SCALAR_TYPE.decimal, value: input.value })
  },
  [GRAPH_SCALAR_TYPE.string]: {
    input: { type: 'text' },
    fromDefault: (value) =>
      typeof value === 'string'
        ? { scalar_type: GRAPH_SCALAR_TYPE.string, value }
        : null,
    fromInput: (input) => ({ scalar_type: GRAPH_SCALAR_TYPE.string, value: input.value })
  }
} as const satisfies Record<
  GraphConstantNodeData['scalar_type'],
  ConstantSpec
>;

export function constantInput(
  scalarType: GraphConstantNodeData['scalar_type']
): ConstantSpec['input'] {
  return CONSTANT_SPECS[scalarType].input;
}

export function constantDataFromDescriptor(
  descriptor: GraphConstantDescriptor
): GraphConstantNodeData {
  const data = CONSTANT_SPECS[descriptor.scalar_type].fromDefault(
    descriptor.default_value
  );
  if (data !== null) return data;
  throw new Error(`Invalid ${descriptor.scalar_type} constant default`);
}

export function constantDataFromInput(
  scalarType: GraphConstantNodeData['scalar_type'],
  input: HTMLInputElement
): GraphConstantNodeData | null {
  return CONSTANT_SPECS[scalarType].fromInput(input);
}
