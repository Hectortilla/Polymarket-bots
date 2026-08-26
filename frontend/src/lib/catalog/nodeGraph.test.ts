import { describe, expect, it } from 'vitest';

import {
  canvasEdges,
  canvasNodes,
  createTriggerNode,
  outputPathIsSelected,
  setOutputPathSelected,
  toPersistedNodeGraph,
  triggerAlreadyExists,
  type CanvasEdge,
  type CanvasNode
} from './nodeGraph';
import {
  ON_BOOK_TRIGGER,
  ON_START_TRIGGER,
  TEST_GRAPH,
  TEST_GRAPH_CATALOG
} from './nodeGraphTestFixtures';

describe('node graph canvas adapter', () => {
  it('round-trips trigger data while stripping XYFlow-only state', () => {
    const nodes = canvasNodes(TEST_GRAPH);
    const edges = canvasEdges(TEST_GRAPH);
    const transientNodes = nodes.map((node) => ({
      ...node,
      selected: true,
      measured: { width: 320, height: 180 }
    })) as CanvasNode[];
    const transientEdges = edges.map((edge) => ({
      ...edge,
      selected: true,
      animated: true
    })) as CanvasEdge[];

    expect(
      toPersistedNodeGraph(
        TEST_GRAPH.schema_version,
        transientNodes,
        transientEdges
      )
    ).toEqual(TEST_GRAPH);
  });

  it('creates one catalog-derived trigger node and detects existing hooks', () => {
    const nodes = canvasNodes(TEST_GRAPH);
    const added = createTriggerNode(
      nodes,
      TEST_GRAPH_CATALOG,
      ON_START_TRIGGER
    );

    expect(added).toMatchObject({
      id: 'trigger-on-start',
      type: TEST_GRAPH_CATALOG.node_type,
      data: { hook_name: ON_START_TRIGGER.hook_name, selected_output_paths: [] }
    });
    expect(triggerAlreadyExists(nodes, ON_BOOK_TRIGGER)).toBe(true);
    expect(triggerAlreadyExists(nodes, ON_START_TRIGGER)).toBe(false);
  });

  it('adds and removes structured selected output paths', () => {
    const data = TEST_GRAPH.nodes[0].data;
    const asks = ON_BOOK_TRIGGER.payload!.fields[1].path;
    const withAsks = setOutputPathSelected(data, asks, true);

    expect(outputPathIsSelected(withAsks, asks)).toBe(true);
    expect(withAsks.selected_output_paths).toEqual([
      { segments: ['bids'] },
      { segments: ['asks'] }
    ]);
    expect(setOutputPathSelected(withAsks, asks, false)).toEqual(data);
  });
});
