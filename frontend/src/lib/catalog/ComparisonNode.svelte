<script lang="ts">
  import { getContext } from 'svelte';
  import { Handle, Position } from '@xyflow/svelte';

  import type { GraphComparisonNodeData } from '$lib/api/generated';
  import { comparisonForNode } from './nodeGraph';
  import {
    NODE_GRAPH_EDITOR_CONTEXT,
    type NodeGraphEditorContext
  } from './nodeGraphContext';

  let { data }: { data: GraphComparisonNodeData } = $props();
  const editor = getContext<NodeGraphEditorContext>(NODE_GRAPH_EDITOR_CONTEXT);
  const descriptor = $derived(comparisonForNode(editor.catalog, data));
  const nodeKind = 'comparison';
</script>

<section class="functional-node" aria-label={`${descriptor.display_name} ${nodeKind} node`}>
  <header>
    <strong>{descriptor.display_name}</strong>
    <span>{nodeKind}</span>
  </header>
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
  .port {
    display: grid;
    gap: 0.15rem;
    padding: 0.55rem 0.75rem;
  }
  header {
    grid-template-columns: 1fr auto;
    border-bottom: 1px solid var(--line);
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
