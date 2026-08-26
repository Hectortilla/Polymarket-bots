import { describe, expect, it } from 'vitest';

import {
  addConnection,
  canvasEdges,
  canvasNodes,
  connectionIsValid,
  createBrokerActionNode,
  createComparisonNode,
  createConstantNode,
  createTriggerNode,
  toPersistedNodeGraph,
  triggerAlreadyExists,
  type CanvasEdge,
  type CanvasNode
} from './nodeGraph';
import {
  BUY_ACTION,
  DECIMAL_CONSTANT,
  LESS_THAN_OR_EQUAL,
  ON_BOOK_TRIGGER,
  ON_START_TRIGGER,
  TEST_GRAPH,
  TEST_GRAPH_CATALOG,
  THRESHOLD_BUY_GRAPH
} from './nodeGraphTestFixtures';

describe('node graph canvas adapter', () => {
  it('round-trips all node data and handles while stripping Flow-only state', () => {
    const transientNodes = canvasNodes(THRESHOLD_BUY_GRAPH).map((node) => ({
      ...node,
      selected: true,
      measured: { width: 320, height: 180 }
    })) as CanvasNode[];
    const transientEdges = canvasEdges(THRESHOLD_BUY_GRAPH).map((edge) => ({
      ...edge,
      selected: true,
      animated: true
    })) as CanvasEdge[];

    expect(toPersistedNodeGraph(transientNodes, transientEdges)).toEqual(
      THRESHOLD_BUY_GRAPH
    );
  });

  it('creates each catalog-described node kind', () => {
    const nodes = canvasNodes(TEST_GRAPH);

    expect(createTriggerNode(nodes, ON_START_TRIGGER)).toMatchObject({
      id: 'trigger-on-start',
      type: ON_START_TRIGGER.node_type,
      data: { hook_name: ON_START_TRIGGER.hook_name }
    });
    expect(createConstantNode(nodes, DECIMAL_CONSTANT)).toMatchObject({
      type: DECIMAL_CONSTANT.node_type,
      data: {
        scalar_type: DECIMAL_CONSTANT.scalar_type,
        value: DECIMAL_CONSTANT.default_value
      }
    });
    expect(createComparisonNode(nodes, LESS_THAN_OR_EQUAL)).toMatchObject({
      type: LESS_THAN_OR_EQUAL.node_type,
      data: { operator: LESS_THAN_OR_EQUAL.operator }
    });
    expect(createBrokerActionNode(nodes, BUY_ACTION)).toMatchObject({
      type: BUY_ACTION.node_type,
      data: { action: BUY_ACTION.action }
    });
    expect(triggerAlreadyExists(nodes, ON_BOOK_TRIGGER)).toBe(true);
    expect(triggerAlreadyExists(nodes, ON_START_TRIGGER)).toBe(false);
  });

  it('keeps generated node IDs unique', () => {
    const first = createConstantNode(canvasNodes(TEST_GRAPH), DECIMAL_CONSTANT);
    const second = createConstantNode(
      [...canvasNodes(TEST_GRAPH), first],
      DECIMAL_CONSTANT
    );

    expect(first.id).toBe('constant-decimal');
    expect(second.id).toBe('constant-decimal-2');
  });

  it('adds complete handled connections and rejects handle-less persistence', () => {
    const connection = {
      source: 'constant-threshold',
      sourceHandle: DECIMAL_CONSTANT.output.handle_id,
      target: 'comparison-threshold',
      targetHandle: LESS_THAN_OR_EQUAL.inputs[1].handle_id
    };

    expect(addConnection(connection, [])).toEqual([
      expect.objectContaining(connection)
    ]);
    expect(() =>
      toPersistedNodeGraph(canvasNodes(TEST_GRAPH), [
        { id: 'missing-handle', source: 'a', target: 'b' }
      ])
    ).toThrow('require source and target handles');
  });

  it('accepts the metadata-compatible threshold BUY connections', () => {
    const nodes = canvasNodes(THRESHOLD_BUY_GRAPH);
    const accepted: CanvasEdge[] = [];

    for (const edge of canvasEdges(THRESHOLD_BUY_GRAPH)) {
      expect(connectionIsValid(edge, nodes, accepted, TEST_GRAPH_CATALOG)).toBe(true);
      accepted.push(edge);
    }

    expect(
      connectionIsValid(
        {
          id: 'wrong-type',
          source: 'on-book-trigger',
          sourceHandle: 'field:token_id',
          target: 'comparison-threshold',
          targetHandle: 'left'
        },
        nodes,
        [],
        TEST_GRAPH_CATALOG
      )
    ).toBe(false);

    expect(
      connectionIsValid(
        {
          source: 'on-book-trigger',
          sourceHandle: 'field:bids',
          target: 'comparison-threshold',
          targetHandle: LESS_THAN_OR_EQUAL.inputs[0].handle_id
        },
        [
          ...canvasNodes(TEST_GRAPH),
          createComparisonNode(canvasNodes(TEST_GRAPH), LESS_THAN_OR_EQUAL)
        ],
        [],
        TEST_GRAPH_CATALOG
      )
    ).toBe(false);

    const validEdge = canvasEdges(THRESHOLD_BUY_GRAPH)[0];
    const invalidConnections = [
      { ...validEdge, sourceHandle: null },
      { ...validEdge, source: 'missing-node' },
      {
        ...validEdge,
        source: validEdge.target,
        sourceHandle: validEdge.targetHandle
      }
    ];
    for (const connection of invalidConnections) {
      expect(
        connectionIsValid(connection, nodes, [], TEST_GRAPH_CATALOG)
      ).toBe(false);
    }
    expect(
      connectionIsValid(
        canvasEdges(THRESHOLD_BUY_GRAPH)[1],
        nodes,
        [canvasEdges(THRESHOLD_BUY_GRAPH)[1]],
        TEST_GRAPH_CATALOG
      )
    ).toBe(false);
  });
});
