<script lang="ts">
  import { setContext, untrack } from 'svelte';
  import {
    Background,
    BackgroundVariant,
    type Connection,
    type CoordinateExtent,
    Controls,
    SvelteFlow
  } from '@xyflow/svelte';
  import '@xyflow/svelte/dist/style.css';
  import catalogContract from './catalogContract.fixture.json';

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
  import {
    GRAPH_VALIDATION_COPY,
    type GraphValidationIssue
  } from './graphValidation';

  let {
    initialGraph,
    graphCatalog,
    onchange,
    labelledby,
    describedby,
    readOnly = false,
    validationIssues = [],
    validationSummaryId = 'graph-validation-summary'
  }: {
    initialGraph: NodeGraph;
    graphCatalog: GraphNodeCatalog;
    onchange?: (graph: NodeGraph) => void;
    labelledby: string;
    describedby?: string;
    readOnly?: boolean;
    validationIssues?: GraphValidationIssue[];
    validationSummaryId?: string;
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
  const readOnlyFlowOptions = { hideAttribution: true };
  let nodes = $state.raw<CanvasNode[]>(canvasNodes(initialGraphSnapshot));
  let edges = $state.raw<CanvasEdge[]>(canvasEdges(initialGraphSnapshot));
  let graphChangeReportingReady = false;
  const coordinateLimit = catalogContract.nodeGraph.coordinateLimit;
  const nodeExtent: CoordinateExtent = [
    [-coordinateLimit, -coordinateLimit],
    [coordinateLimit, coordinateLimit]
  ];
  const canvasDescription = $derived(
    [describedby, validationIssues.length > 0 ? validationSummaryId : undefined]
      .filter(Boolean)
      .join(' ') || undefined
  );

  const editorContext: NodeGraphEditorContext = {
    catalog: catalogSnapshot,
    get readOnly() {
      return readOnly;
    },
    setComparisonData,
    setConstantData
  };
  setContext(NODE_GRAPH_EDITOR_CONTEXT, editorContext);

  // The parent already owns the initial graph; report only subsequent canvas edits.
  // Rebuilding the initial graph can reorder object keys and falsely mark it dirty.
  $effect(() => {
    if (readOnly) return;
    const graph = toPersistedNodeGraph(nodes, edges);
    if (graphChangeReportingReady) {
      untrack(() => onchange?.(graph));
    } else {
      graphChangeReportingReady = true;
    }
  });

  function addTrigger(trigger: GraphTriggerDescriptor): void {
    addNode(createTriggerNode(nodes, trigger));
  }

  function addNode(node: CanvasNode): void {
    if (readOnly) return;
    if (nodes.length < catalogContract.nodeGraph.maximumNodes) {
      nodes = [...nodes, node];
    }
  }

  function setConstantData(nodeId: string, data: GraphConstantNodeData): void {
    if (readOnly) return;
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
    if (readOnly) return;
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
    if (readOnly) return;
    if (edges.length >= catalogContract.nodeGraph.maximumEdges) return;
    edges = addConnection(connection, edges);
  }
</script>

<div class="graph-editor">
  <div class="graph-toolbar">
    <div class="graph-summary" aria-live="polite">
      <span><strong>{nodes.length}</strong> {nodes.length === 1 ? 'node' : 'nodes'}</span>
      <span><strong>{edges.length}</strong> {edges.length === 1 ? 'connection' : 'connections'}</span>
    </div>
    {#if !readOnly}
      <NodePalette
        catalog={catalogSnapshot}
        {nodes}
        additionDisabled={nodes.length >= catalogContract.nodeGraph.maximumNodes}
        onaddtrigger={addTrigger}
        onaddconstant={(constant) => addNode(createConstantNode(nodes, constant))}
        onaddcomparison={(comparison) => addNode(createComparisonNode(nodes, comparison))}
        onaddaction={(action) => addNode(createBrokerActionNode(nodes, action))}
      />
    {/if}
  </div>
  <div
    class="graph-canvas"
    class:read-only={readOnly}
    role={readOnly ? 'group' : 'application'}
    aria-labelledby={labelledby}
    aria-describedby={canvasDescription}
    aria-disabled={readOnly || undefined}
  >
    <SvelteFlow
      bind:nodes
      bind:edges
      {nodeTypes}
      isValidConnection={(connection) =>
        edges.length < catalogContract.nodeGraph.maximumEdges
        && connectionIsValid(connection, nodes, edges, catalogSnapshot)}
      onconnect={connect}
      nodesDraggable={!readOnly}
      nodesConnectable={!readOnly && edges.length < catalogContract.nodeGraph.maximumEdges}
      elementsSelectable={!readOnly}
      nodesFocusable={!readOnly}
      edgesFocusable={!readOnly}
      autoPanOnNodeFocus={!readOnly}
      autoPanOnConnect={!readOnly}
      autoPanOnNodeDrag={!readOnly}
      autoPanOnSelection={!readOnly}
      panOnDrag={!readOnly}
      panOnScroll={false}
      zoomOnScroll={!readOnly}
      zoomOnDoubleClick={!readOnly}
      zoomOnPinch={!readOnly}
      preventScrolling={!readOnly}
      clickConnect={!readOnly}
      disableKeyboardA11y={readOnly}
      proOptions={readOnly ? readOnlyFlowOptions : undefined}
      {nodeExtent}
      fitView
      minZoom={0.25}
      maxZoom={2}
    >
      {#if !readOnly}
        <Controls
          class="node-graph-controls"
          position="bottom-right"
          orientation="horizontal"
        />
      {/if}
      <Background variant={BackgroundVariant.Dots} gap={18} size={1} />
    </SvelteFlow>
  </div>
  {#if validationIssues.length > 0}
    <section
      class="graph-validation-summary"
      id={validationSummaryId}
      role="alert"
      aria-labelledby={`${validationSummaryId}-title`}
      tabindex="-1"
    >
      <div class="graph-validation-heading">
        <h3 id={`${validationSummaryId}-title`}>{GRAPH_VALIDATION_COPY.TITLE}</h3>
        <span>{validationIssues.length} {validationIssues.length === 1 ? 'issue' : 'issues'}</span>
      </div>
      <p>{GRAPH_VALIDATION_COPY.INTRO}</p>
      <ol>
        {#each validationIssues as issue (`${issue.location}:${issue.message}`)}
          <li>
            <strong>{issue.location}</strong>
            <span>{issue.message}</span>
          </li>
        {/each}
      </ol>
    </section>
  {/if}
</div>

<style>
  .graph-editor {
    display: grid;
    gap: 0.85rem;
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
    height: 38rem;
    overflow: hidden;
    border: 1px solid var(--line-strong);
    border-radius: var(--radius-surface);
    background: var(--surface-input);
  }

  .graph-canvas.read-only {
    pointer-events: none;
    user-select: none;
  }

  .graph-validation-summary {
    border: 1px solid rgb(223 164 158 / 0.34);
    border-left: 3px solid var(--danger);
    border-radius: var(--radius-surface);
    padding: 1rem;
    color: #f0c2bd;
    background: var(--danger-surface);
  }

  .graph-validation-summary:focus-visible {
    outline: 2px solid var(--danger);
    outline-offset: 3px;
  }

  .graph-validation-heading {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 1rem;
  }

  .graph-validation-heading h3,
  .graph-validation-summary p {
    margin: 0;
  }

  .graph-validation-heading h3 {
    color: var(--text);
    font-size: 0.95rem;
  }

  .graph-validation-heading span {
    flex: none;
    color: #e9b7b2;
    font-family: 'Geist Mono Variable', ui-monospace, monospace;
    font-size: 0.68rem;
  }

  .graph-validation-summary > p {
    margin-top: 0.35rem;
    color: #e9b7b2;
    font-size: 0.82rem;
    line-height: 1.5;
  }

  .graph-validation-summary ol {
    margin: 0.9rem 0 0;
    padding: 0;
    display: grid;
    gap: 0.6rem;
    list-style: none;
  }

  .graph-validation-summary li {
    border-top: 1px solid rgb(223 164 158 / 0.2);
    padding-top: 0.6rem;
    display: grid;
    gap: 0.15rem;
  }

  .graph-validation-summary li strong {
    color: var(--text);
    font-size: 0.78rem;
    font-weight: 620;
  }

  .graph-validation-summary li span {
    color: #e9b7b2;
    font-size: 0.82rem;
    line-height: 1.45;
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
    background: rgb(16 20 17 / 0.92);
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

    .graph-validation-heading {
      align-items: flex-start;
      flex-direction: column;
      gap: 0.25rem;
    }
  }

  @media (max-width: 767px) {
    .graph-toolbar {
      align-items: flex-start;
      flex-direction: column;
    }

    .graph-canvas {
      height: 32rem;
    }
  }
</style>
