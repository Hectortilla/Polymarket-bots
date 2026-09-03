<script lang="ts">
  import { getContext } from 'svelte';
  import { Handle, Position } from '@xyflow/svelte';

  import type { GraphComparisonNodeData } from '$lib/api/generated';
  import { comparisonForNode } from './nodeGraph';
  import { GRAPH_NODE_TYPE } from './graphContracts';
  import {
    NODE_GRAPH_EDITOR_CONTEXT,
    type NodeGraphEditorContext
  } from './nodeGraphContext';

  let { id, data }: { id: string; data: GraphComparisonNodeData } = $props();
  const editor = getContext<NodeGraphEditorContext>(NODE_GRAPH_EDITOR_CONTEXT);
  const descriptor = $derived(comparisonForNode(editor.catalog, data));
  const nodeKind = GRAPH_NODE_TYPE.comparison;

  function updateOperator(event: Event): void {
    const select = event.currentTarget as HTMLSelectElement;
    const comparison = editor.catalog.comparisons.find(
      ({ operator }) => operator === select.value
    );
    if (!comparison) return;
    editor.setComparisonData(id, {
      operator: comparison.operator
    });
  }
</script>

<section class="functional-node" aria-label={`${descriptor.display_name} ${nodeKind} node`}>
  <header>
    <strong>Comparison</strong>
    <span>{nodeKind}</span>
  </header>
  <label class="operator-control nodrag nowheel">
    <span>Operator</span>
    <select aria-label="Comparison operator" value={data.operator} onchange={updateOperator}>
      {#each editor.catalog.comparisons as comparison (comparison.operator)}
        <option value={comparison.operator}>{comparison.display_name}</option>
      {/each}
    </select>
  </label>
  {#each descriptor.inputs as input (input.handle_id)}
    <div class="port input-port">
      <Handle type="target" position={Position.Left} id={input.handle_id} />
      <span>{input.display_name}</span>
      <small>{input.scalar_types.join(' | ')}</small>
    </div>
  {/each}
  <div class="port output-port">
    <span>{descriptor.output.display_name}</span>
    <small>{descriptor.output.scalar_type}</small>
    <Handle type="source" position={Position.Right} id={descriptor.output.handle_id} />
  </div>
</section>

<style>
  .functional-node {
    width: 15rem;
    overflow: visible;
    border: 1px solid var(--line-strong);
    border-radius: 0.75rem;
    background: var(--surface-raised);
    box-shadow: 0 0.5rem 1.5rem rgb(8 15 30 / 12%);
  }
  header,
  .operator-control,
  .port {
    display: grid;
    gap: 0.15rem;
    padding: 0.55rem 0.75rem;
  }
  header {
    grid-template-columns: 1fr auto;
    border-bottom: 1px solid var(--line);
  }
  .operator-control {
    grid-template-columns: auto minmax(0, 1fr);
    align-items: center;
    border-bottom: 1px solid var(--line);
  }
  .operator-control span {
    color: var(--text-muted);
    font-size: 0.7rem;
  }
  .operator-control select {
    min-width: 0;
    width: 100%;
    min-height: 2rem;
    border: 1px solid var(--control-line);
    border-radius: var(--radius-control);
    padding: 0.35rem 1.8rem 0.35rem 0.5rem;
    color: var(--text);
    background: var(--surface-input);
    font-family: 'Geist Mono Variable', ui-monospace, monospace;
    font-size: 0.7rem;
    transition:
      border-color var(--transition),
      background-color var(--transition),
      box-shadow var(--transition);
  }
  .operator-control select:hover {
    border-color: var(--control-line-hover);
  }
  .operator-control select:focus {
    border-color: var(--accent);
    outline: 0;
    background: var(--surface);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 10%, transparent);
  }
  header strong,
  .port span {
    font-family: 'Geist Mono Variable', ui-monospace, monospace;
    font-size: 0.76rem;
  }
  header span,
  .port small {
    color: var(--text-muted);
    font-size: 0.7rem;
  }
  .port {
    position: relative;
    border-bottom: 1px solid var(--line);
  }
  .output-port {
    text-align: right;
  }
  :global(.svelte-flow__handle) {
    width: 0.55rem;
    height: 0.55rem;
    background: var(--accent);
  }
</style>
