<script lang="ts">
  import { setContext, untrack } from 'svelte';
  import {
    Background,
    BackgroundVariant,
    Controls,
    SvelteFlow
  } from '@xyflow/svelte';
  import '@xyflow/svelte/dist/style.css';

  import type {
    GraphFieldPath,
    GraphNodeCatalog,
    GraphTriggerDescriptor,
    NodeGraph
  } from '$lib/api/generated';
  import TriggerNode from './TriggerNode.svelte';
  import {
    canvasEdges,
    canvasNodes,
    createTriggerNode,
    setOutputPathSelected,
    toPersistedNodeGraph,
    triggerAlreadyExists,
    type CanvasEdge,
    type CanvasNode
  } from './nodeGraph';
  import {
    TRIGGER_NODE_EDITOR_CONTEXT,
    type TriggerNodeEditorContext
  } from './triggerNodeContext';

  let {
    initialGraph,
    graphCatalog,
    onchange,
    labelledby,
    describedby
  }: {
    initialGraph: NodeGraph;
    graphCatalog: GraphNodeCatalog;
    onchange: (graph: NodeGraph) => void;
    labelledby: string;
    describedby?: string;
  } = $props();

  // Snapshot the keyed graph once; keep Flow-owned arrays out of Svelte's deep proxies.
  const initialGraphSnapshot = untrack(() => initialGraph);
  const catalogSnapshot = untrack(() => graphCatalog);
  const schemaVersion = initialGraphSnapshot.schema_version;
  const nodeTypes = { [catalogSnapshot.node_type]: TriggerNode };
  let nodes = $state.raw<CanvasNode[]>(canvasNodes(initialGraphSnapshot));
  let edges = $state.raw<CanvasEdge[]>(canvasEdges(initialGraphSnapshot));

  const editorContext: TriggerNodeEditorContext = {
    catalog: catalogSnapshot,
    setOutputSelected
  };
  setContext(TRIGGER_NODE_EDITOR_CONTEXT, editorContext);

  // Canvas state is owned here; keep the parent callback out of this effect's dependencies.
  $effect(() => {
    const graph = toPersistedNodeGraph(schemaVersion, nodes, edges);
    untrack(() => onchange(graph));
  });

  function addTrigger(trigger: GraphTriggerDescriptor): void {
    nodes = [...nodes, createTriggerNode(nodes, catalogSnapshot, trigger)];
  }

  function setOutputSelected(
    nodeId: string,
    path: GraphFieldPath,
    selected: boolean
  ): void {
    nodes = nodes.map((node) =>
      node.id === nodeId
        ? { ...node, data: setOutputPathSelected(node.data, path, selected) }
        : node
    );
  }
</script>

<div class="graph-editor">
  <div class="graph-toolbar" aria-label="Add graph trigger">
    {#each catalogSnapshot.triggers as trigger (trigger.hook_name)}
      <button
        type="button"
        disabled={triggerAlreadyExists(nodes, trigger)}
        onclick={() => addTrigger(trigger)}
      >
        Add {trigger.hook_name}
      </button>
    {/each}
  </div>
  <div
    class="graph-canvas"
    role="application"
    aria-labelledby={labelledby}
    aria-describedby={describedby}
  >
    <SvelteFlow
      bind:nodes
      bind:edges
      {nodeTypes}
      nodesConnectable={false}
      fitView
      minZoom={0.25}
      maxZoom={2}
    >
      <Controls
        class="node-graph-controls"
        position="bottom-right"
        orientation="horizontal"
      />
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
    height: 32rem;
    overflow: hidden;
    border: 1px solid var(--line-strong);
    border-radius: 0.75rem;
    background: var(--surface-raised);
  }

  :global(.svelte-flow__node) {
    font-family: inherit;
  }

  :global(.node-graph-controls.svelte-flow__controls) {
    gap: 0.2rem;
    overflow: hidden;
    border: 1px solid var(--line-strong);
    border-radius: 0.65rem;
    padding: 0.3rem;
    background: rgb(14 17 15 / 0.9);
    box-shadow: 0 0.75rem 2rem rgb(4 8 6 / 0.32);
    backdrop-filter: blur(14px) saturate(120%);
    -webkit-backdrop-filter: blur(14px) saturate(120%);
  }

  :global(.node-graph-controls .svelte-flow__controls-button) {
    width: 2rem;
    height: 2rem;
    border: 0;
    border-radius: 0.4rem;
    padding: 0.5rem;
    color: var(--text-muted);
    background: transparent;
    transition:
      color var(--transition),
      background var(--transition),
      transform var(--transition);
  }

  :global(
    .node-graph-controls.svelte-flow__controls.horizontal
      .svelte-flow__controls-button
  ) {
    border-right: 0;
  }

  :global(.node-graph-controls .svelte-flow__controls-button:hover) {
    color: var(--text);
    background: var(--line);
  }

  :global(.node-graph-controls .svelte-flow__controls-button:active) {
    transform: scale(0.94);
  }

  :global(.node-graph-controls .svelte-flow__controls-button:focus-visible) {
    position: relative;
    z-index: 1;
    outline: 2px solid var(--accent);
    outline-offset: -2px;
  }

  :global(.node-graph-controls .svelte-flow__controls-button:disabled) {
    color: var(--text-muted);
    opacity: 0.4;
  }

  :global(.node-graph-controls .svelte-flow__controls-button svg) {
    width: 0.8rem;
    max-width: none;
    height: 0.8rem;
    max-height: none;
    fill: currentColor;
  }
</style>
