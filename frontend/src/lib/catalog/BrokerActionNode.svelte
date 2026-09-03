<script lang="ts">
  import { getContext } from 'svelte';
  import { Handle, Position } from '@xyflow/svelte';

  import type { GraphBrokerActionNodeData } from '$lib/api/generated';
  import { brokerActionForNode } from './nodeGraph';
  import {
    NODE_GRAPH_EDITOR_CONTEXT,
    type NodeGraphEditorContext
  } from './nodeGraphContext';

  let { data }: { data: GraphBrokerActionNodeData } = $props();
  const editor = getContext<NodeGraphEditorContext>(NODE_GRAPH_EDITOR_CONTEXT);
  const descriptor = $derived(brokerActionForNode(editor.catalog, data));
</script>

<section class="action-node" aria-label={`${descriptor.display_name} broker action node`}>
  <header>
    <strong>{descriptor.display_name}</strong>
    <span>Broker.{descriptor.method_name}</span>
  </header>
  {#each descriptor.inputs as input (input.handle_id)}
    <div class="port">
      <Handle
        type="target"
        position={Position.Left}
        id={input.handle_id}
        isConnectable={!editor.readOnly}
      />
      <span>{input.display_name}{input.required ? '' : ' (optional)'}</span>
      <small>{input.scalar_types.join(' | ')}</small>
    </div>
  {/each}
</section>

<style>
  .action-node {
    width: 16rem;
    overflow: visible;
    border: 1px solid var(--accent);
    border-radius: 0.75rem;
    background: var(--surface-raised);
    box-shadow: 0 0.5rem 1.5rem rgb(8 15 30 / 12%);
  }
  header,
  .port {
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 0.15rem 0.65rem;
    padding: 0.5rem 0.75rem;
  }
  header,
  .port:not(:last-child) {
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
  }
  :global(.svelte-flow__handle) {
    width: 0.55rem;
    height: 0.55rem;
    background: var(--accent);
  }
</style>
