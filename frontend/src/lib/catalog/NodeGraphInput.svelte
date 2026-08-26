<script lang="ts">
  import { setContext, untrack } from 'svelte';
  import {
    Background,
    BackgroundVariant,
    type Connection,
    Controls,
    SvelteFlow
  } from '@xyflow/svelte';
  import '@xyflow/svelte/dist/style.css';

  import type {
    GraphComparisonNodeData,
    GraphConstantNodeData,
    GraphNodeCatalog,
    GraphTriggerDescriptor,
    NodeGraph
  } from '$lib/api/generated';
  import BrokerActionNode from './BrokerActionNode.svelte';
  import ComparisonNode from './ComparisonNode.svelte';
  import ConstantNode from './ConstantNode.svelte';
  import NodePalette from './NodePalette.svelte';
  import TriggerNode from './TriggerNode.svelte';
  import {
    addConnection,
    canvasEdges,
    canvasNodes,
    connectionIsValid,
    createBrokerActionNode,
    createComparisonNode,
    createConstantNode,
    createTriggerNode,
    GRAPH_NODE_TYPE,
    toPersistedNodeGraph,
    type CanvasEdge,
    type CanvasNode
  } from './nodeGraph';
  import {
    NODE_GRAPH_EDITOR_CONTEXT,
    type NodeGraphEditorContext
  } from './nodeGraphContext';

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
  const nodeTypes = {
    [GRAPH_NODE_TYPE.trigger]: TriggerNode,
    [GRAPH_NODE_TYPE.constant]: ConstantNode,
    [GRAPH_NODE_TYPE.comparison]: ComparisonNode,
    [GRAPH_NODE_TYPE.brokerAction]: BrokerActionNode
  };
  let nodes = $state.raw<CanvasNode[]>(canvasNodes(initialGraphSnapshot));
  let edges = $state.raw<CanvasEdge[]>(canvasEdges(initialGraphSnapshot));

  const editorContext: NodeGraphEditorContext = {
    catalog: catalogSnapshot,
    setComparisonData,
    setConstantData
  };
  setContext(NODE_GRAPH_EDITOR_CONTEXT, editorContext);

  // Canvas state is owned here; keep the parent callback out of this effect's dependencies.
  $effect(() => {
    const graph = toPersistedNodeGraph(nodes, edges);
    untrack(() => onchange(graph));
  });

  function addTrigger(trigger: GraphTriggerDescriptor): void {
    nodes = [...nodes, createTriggerNode(nodes, trigger)];
  }

  function setConstantData(nodeId: string, data: GraphConstantNodeData): void {
    nodes = nodes.map((node) =>
      node.id === nodeId && node.type === GRAPH_NODE_TYPE.constant
        ? { ...node, data }
        : node
    );
  }

  function setComparisonData(
    nodeId: string,
    data: GraphComparisonNodeData
  ): void {
    const updatedNodes = nodes.map((node) =>
      node.id === nodeId && node.type === GRAPH_NODE_TYPE.comparison
        ? { ...node, data }
        : node
    );
    nodes = updatedNodes;
    edges = edges.filter(
      (edge) =>
        edge.target !== nodeId ||
        connectionIsValid(edge, updatedNodes, [], catalogSnapshot)
    );
  }

  function connect(connection: Connection): void {
    edges = addConnection(connection, edges);
  }
</script>

<div class="graph-editor">
  <div class="graph-toolbar">
    <div class="graph-summary" aria-live="polite">
      <span><strong>{nodes.length}</strong> {nodes.length === 1 ? 'node' : 'nodes'}</span>
      <span><strong>{edges.length}</strong> {edges.length === 1 ? 'connection' : 'connections'}</span>
    </div>
    <NodePalette
      catalog={catalogSnapshot}
      {nodes}
      onaddtrigger={addTrigger}
      onaddconstant={(constant) => (nodes = [...nodes, createConstantNode(nodes, constant)])}
      onaddcomparison={(comparison) => (nodes = [...nodes, createComparisonNode(nodes, comparison)])}
      onaddaction={(action) => (nodes = [...nodes, createBrokerActionNode(nodes, action)])}
    />
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
      isValidConnection={(connection) =>
        connectionIsValid(connection, nodes, edges, catalogSnapshot)}
      onconnect={connect}
      nodesConnectable={true}
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
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
  }

  .graph-summary {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem 1rem;
    color: var(--text-muted);
    font-family: 'Geist Mono Variable', ui-monospace, monospace;
    font-size: 0.68rem;
  }

  .graph-summary strong {
    color: var(--text-soft);
    font-weight: 620;
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

  @media (max-width: 560px) {
    .graph-toolbar {
      align-items: flex-start;
    }

    .graph-summary {
      display: grid;
      gap: 0.25rem;
    }

    .graph-canvas {
      height: 28rem;
    }
  }
</style>
