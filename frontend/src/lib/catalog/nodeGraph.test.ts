import { describe, expect, it } from 'vitest';

import type { NodeGraph } from '$lib/api/generated';
import {
  GRAPH_NODE_TYPE,
  canvasEdges,
  canvasNodes,
  createCanvasNode,
  toPersistedNodeGraph,
  type CanvasEdge,
  type CanvasNode
} from './nodeGraph';

const GRAPH: NodeGraph = {
  schema_version: 1,
  nodes: [
    {
      id: 'input-1',
      type: GRAPH_NODE_TYPE.input,
      position: { x: 0, y: 10 },
      data: { label: 'Market input' }
    },
    {
      id: 'output-1',
      type: GRAPH_NODE_TYPE.output,
      position: { x: 200, y: 10 },
      data: { label: 'Output' }
    }
  ],
  edges: [{ id: 'input-output', source: 'input-1', target: 'output-1' }]
};

describe('node graph canvas adapter', () => {
  it('round-trips only the persisted graph contract', () => {
    const nodes = canvasNodes(GRAPH);
    const edges = canvasEdges(GRAPH);
    const transientNodes = nodes.map((node) => ({
      ...node,
      selected: true,
      measured: { width: 120, height: 40 }
    })) as CanvasNode[];
    const transientEdges = edges.map((edge) => ({
      ...edge,
      selected: true,
      animated: true
    })) as CanvasEdge[];

    expect(
      toPersistedNodeGraph(GRAPH.schema_version, transientNodes, transientEdges)
    ).toEqual(GRAPH);
  });

  it('adds typed nodes with the first available stable ID', () => {
    const nodes = canvasNodes(GRAPH);

    expect(createCanvasNode(nodes, GRAPH_NODE_TYPE.input)).toMatchObject({
      id: 'input-2',
      type: GRAPH_NODE_TYPE.input,
      data: { label: expect.any(String) }
    });
  });
});
