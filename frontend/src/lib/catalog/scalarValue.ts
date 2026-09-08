import { GRAPH_SCALAR_TYPE } from './graphContracts';
import { graphNumberIsValid } from './numberValue';

export function graphScalarValueIsValid(scalarType: string, value: unknown): boolean {
  switch (scalarType) {
    case GRAPH_SCALAR_TYPE.boolean: return typeof value === 'boolean';
    case GRAPH_SCALAR_TYPE.number: return graphNumberIsValid(value);
    case GRAPH_SCALAR_TYPE.string: return typeof value === 'string';
    default: return false;
  }
}
