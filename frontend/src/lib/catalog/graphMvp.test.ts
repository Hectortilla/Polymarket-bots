import { describe, expect, it } from 'vitest';
import type { GraphParameter } from '$lib/api/generated';
import { TEST_GRAPH_CATALOG } from './nodeGraphTestFixtures';
import { canvasNodes, createOperationNode, createParameterNode, inputsForNode, outputsForNode, toPersistedNodeGraph } from './nodeGraph';
import { nodeGraphsEqual } from './nodeGraphEquality';

describe('MVP graph representation', () => {
  for (const operation of TEST_GRAPH_CATALOG.operations ?? []) {
    it(`round-trips ${operation.operation} from backend metadata`, () => {
      const node = createOperationNode([], operation);
      const graph = toPersistedNodeGraph([node], []);
      expect(canvasNodes(graph)).toEqual([node]);
      expect(inputsForNode(node, TEST_GRAPH_CATALOG).map(port => port.handle_id)).toEqual(operation.inputs.map(port => port.handle_id));
      expect(outputsForNode(node, TEST_GRAPH_CATALOG)).toEqual(operation.outputs);
    });
  }
  it('keeps expandable handle identity after removing an input', () => {
    const descriptor = TEST_GRAPH_CATALOG.operations!.find(item => item.expandable)!;
    const node = createOperationNode([], descriptor);
    if (node.type !== 'operation') throw new Error('Expected operation');
    node.data.input_ids = ['input_1', 'input_3'];
    expect(inputsForNode(node, TEST_GRAPH_CATALOG).map(port => port.handle_id)).toEqual(['input_1', 'input_3']);
  });
  it('stores parameter values once and detects parameter-only edits', () => {
    const parameter: GraphParameter = { id: 'budget', name: 'Budget', data: { scalar_type: 'number', value: '9007199254740993.01' } };
    const node = createParameterNode([], parameter);
    const graph = toPersistedNodeGraph([node], [], [parameter]);
    expect(outputsForNode(node, TEST_GRAPH_CATALOG, [parameter])[0].scalar_type).toBe(parameter.data.scalar_type);
    expect(nodeGraphsEqual(graph, { ...graph, parameters: [{ ...parameter, name: 'New budget' }] })).toBe(false);
  });
});
