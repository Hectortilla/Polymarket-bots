import { describe, expect, it } from 'vitest';
import type { NodeGraph } from '$lib/api/generated';

import {
  addConnection,
  canvasEdges,
  canvasNodes,
  connectionIsValid,
  createBrokerActionNode,
  createComparisonNode,
  createConstantNode,
  createTriggerNode,
  nodeGraphsEqual,
  toPersistedNodeGraph,
  triggerAlreadyExists,
  type CanvasEdge,
  type CanvasNode
} from './nodeGraph';
import { GRAPH_NODE_TYPE } from './graphContracts';
import {
  BUY_ACTION,
  DECIMAL_CONSTANT,
  EQUAL_COMPARISON,
  LESS_THAN_OR_EQUAL,
  ON_BOOK_TRIGGER,
  ON_START_TRIGGER,
  SELL_ACTION,
  TEST_GRAPH,
  TEST_GRAPH_CATALOG,
  THRESHOLD_BUY_GRAPH,
  graphFieldHandle
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

  it('compares persisted graphs by meaning instead of JSON property or array order', () => {
    const equivalentGraph = {
      edges: [...(THRESHOLD_BUY_GRAPH.edges ?? [])].reverse(),
      nodes: [...THRESHOLD_BUY_GRAPH.nodes].reverse()
    };
    const movedGraph = {
      ...equivalentGraph,
      nodes: equivalentGraph.nodes.map((node) =>
        node.id === 'on-book-trigger'
          ? { ...node, position: { ...node.position, x: node.position.x + 1 } }
          : node
      )
    };
    const changedNodeData = {
      ...equivalentGraph,
      nodes: equivalentGraph.nodes.map((node) =>
        node.type === GRAPH_NODE_TYPE.constant
          ? { ...node, data: { ...node.data, value: '0.75' } }
          : node
      )
    } as NodeGraph;
    const changedEdge = {
      ...equivalentGraph,
      edges: (equivalentGraph.edges ?? []).map((edge, index) =>
        index === 0
          ? { ...edge, target_handle: `${edge.target_handle}-changed` }
          : edge
      )
    };

    expect(nodeGraphsEqual(THRESHOLD_BUY_GRAPH, equivalentGraph)).toBe(true);
    expect(nodeGraphsEqual(THRESHOLD_BUY_GRAPH, movedGraph)).toBe(false);
    expect(nodeGraphsEqual(THRESHOLD_BUY_GRAPH, changedNodeData)).toBe(false);
    expect(nodeGraphsEqual(THRESHOLD_BUY_GRAPH, changedEdge)).toBe(false);
    expect(nodeGraphsEqual(undefined, undefined)).toBe(true);
    expect(nodeGraphsEqual(THRESHOLD_BUY_GRAPH, undefined)).toBe(false);
  });

  it('detects every persisted node discriminator and edge endpoint change', () => {
    const changedNodeGraphs = [
      changeNodeData(GRAPH_NODE_TYPE.trigger, {
        hook_name: ON_START_TRIGGER.hook_name
      }),
      changeNodeData(GRAPH_NODE_TYPE.comparison, {
        operator: EQUAL_COMPARISON.operator
      }),
      changeNodeData(GRAPH_NODE_TYPE.brokerAction, {
        action: SELL_ACTION.action
      })
    ];
    const firstEdge = THRESHOLD_BUY_GRAPH.edges?.[0];
    if (!firstEdge) throw new Error('threshold graph fixture requires an edge');
    const changedEdgeGraphs = [
      { ...firstEdge, source: `${firstEdge.source}-changed` },
      { ...firstEdge, source_handle: `${firstEdge.source_handle}-changed` },
      { ...firstEdge, target: `${firstEdge.target}-changed` },
      { ...firstEdge, target_handle: `${firstEdge.target_handle}-changed` }
    ].map((changedEdge) => ({
      ...THRESHOLD_BUY_GRAPH,
      edges: [
        changedEdge,
        ...(THRESHOLD_BUY_GRAPH.edges?.slice(1) ?? [])
      ]
    }));

    for (const changedGraph of [...changedNodeGraphs, ...changedEdgeGraphs]) {
      expect(nodeGraphsEqual(THRESHOLD_BUY_GRAPH, changedGraph)).toBe(false);
    }
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
          sourceHandle: graphFieldHandle(ON_BOOK_TRIGGER, 'token_id'),
          target: 'comparison-threshold',
          targetHandle: LESS_THAN_OR_EQUAL.inputs[0].handle_id
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
          sourceHandle: graphFieldHandle(ON_BOOK_TRIGGER, 'bids'),
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

function changeNodeData(
  nodeType: (typeof GRAPH_NODE_TYPE)[keyof typeof GRAPH_NODE_TYPE],
  data: Record<string, string>
): NodeGraph {
  return {
    ...THRESHOLD_BUY_GRAPH,
    nodes: THRESHOLD_BUY_GRAPH.nodes.map((node) =>
      node.type === nodeType ? { ...node, data } : node
    )
  } as NodeGraph;
}
