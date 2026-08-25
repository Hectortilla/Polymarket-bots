<script lang="ts">
  import { untrack } from 'svelte';
  import {
    Background,
    BackgroundVariant,
    Controls,
    SvelteFlow
  } from '@xyflow/svelte';
  import '@xyflow/svelte/dist/style.css';

  import type { GraphNodeType, NodeGraph } from '$lib/api/generated';
  import {
    GRAPH_NODE_TYPE,
    canvasEdges,
    canvasNodes,
    createCanvasNode,
    toPersistedNodeGraph,
    type CanvasEdge,
    type CanvasNode
  } from './nodeGraph';

  let {
    initialGraph,
    onchange,
    labelledby,
    describedby
  }: {
    initialGraph: NodeGraph;
    onchange: (graph: NodeGraph) => void;
    labelledby: string;
    describedby?: string;
  } = $props();

  // Snapshot the keyed graph once; keep Flow-owned arrays out of Svelte's deep proxies.
  const initialValue = untrack(() => initialGraph);
  const schemaVersion = initialValue.schema_version;
  let nodes = $state.raw<CanvasNode[]>(canvasNodes(initialValue));
  let edges = $state.raw<CanvasEdge[]>(canvasEdges(initialValue));

  // Canvas state is owned here; keep the parent callback out of this effect's dependencies.
  $effect(() => {
    const graph = toPersistedNodeGraph(schemaVersion, nodes, edges);
    untrack(() => onchange(graph));
  });

  function addNode(type: GraphNodeType): void {
    nodes = [...nodes, createCanvasNode(nodes, type)];
  }
</script>

<div class="graph-editor">
  <div class="graph-toolbar" aria-label="Add graph node">
    <button type="button" onclick={() => addNode(GRAPH_NODE_TYPE.input)}>Add input</button>
    <button type="button" onclick={() => addNode(GRAPH_NODE_TYPE.default)}>Add condition</button>
    <button type="button" onclick={() => addNode(GRAPH_NODE_TYPE.output)}>Add output</button>
  </div>
  <div
    class="graph-canvas"
    role="application"
    aria-labelledby={labelledby}
    aria-describedby={describedby}
  >
    <SvelteFlow bind:nodes bind:edges fitView minZoom={0.25} maxZoom={2}>
      <Controls />
      <Background variant={BackgroundVariant.Dots} gap={18} size={1} />
    </SvelteFlow>
  </div>
</div>

<style>
  .graph-editor {
    display: grid;
    gap: 0.65rem;
  }

  .graph-toolbar {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
  }

  .graph-toolbar button {
    width: auto;
    min-height: 2.25rem;
    padding: 0.45rem 0.75rem;
  }

  .graph-canvas {
    height: 24rem;
    overflow: hidden;
    border: 1px solid var(--line-strong);
    border-radius: 0.75rem;
    background: var(--surface-raised);
  }

  :global(.svelte-flow__node) {
    font-family: inherit;
  }
</style>
