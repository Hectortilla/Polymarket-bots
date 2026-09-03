<script lang="ts">
  import { getContext } from 'svelte';
  import { Handle, Position } from '@xyflow/svelte';

  import type { GraphTriggerNodeData } from '$lib/api/generated';
  import { triggerForNode } from './nodeGraph';
  import {
    NODE_GRAPH_EDITOR_CONTEXT,
    type NodeGraphEditorContext
  } from './nodeGraphContext';

  let { data }: { data: GraphTriggerNodeData } = $props();

  const editor = getContext<NodeGraphEditorContext>(
    NODE_GRAPH_EDITOR_CONTEXT
  );
  const trigger = $derived(triggerForNode(editor.catalog, data));
</script>

<section class="trigger-node" aria-label={`${trigger.hook_name} trigger node`}>
  <header>
    <strong>{trigger.hook_name}</strong>
    <span>event trigger</span>
  </header>

  <div class="output context-output">
    <span>{trigger.context_type_name}</span>
    <Handle
      type="source"
      position={Position.Right}
      id={trigger.context_handle_id}
      isConnectable={false}
    />
  </div>

  {#if trigger.payload}
    <div class="outputs nodrag nowheel">
      <p class="outputs-title">{trigger.payload.type_name} outputs</p>
      {#each trigger.payload.fields as field (field.handle_id)}
        <div class="field-output">
          <span>{field.display_name}</span>
          <small>
            {field.collection ? `collection<${field.value_type}>` : field.value_type}{field.nullable ? ' | null' : ''}
          </small>
          <Handle
            type="source"
            position={Position.Right}
            id={field.handle_id}
            isConnectable={!editor.readOnly && field.scalar_type !== null}
          />
        </div>
      {/each}
    </div>
  {:else}
    <p class="lifecycle-only">Lifecycle trigger with context only.</p>
  {/if}
</section>

<style>
  .trigger-node {
    width: 20rem;
    overflow: visible;
    border: 1px solid var(--line-strong);
    border-radius: 0.75rem;
    background: var(--surface-raised);
    box-shadow: 0 0.5rem 1.5rem rgb(8 15 30 / 12%);
  }

  header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 1rem;
    padding: 0.65rem 0.75rem;
    border-bottom: 1px solid var(--line);
  }

  header strong {
    font-family: 'Geist Mono Variable', ui-monospace, monospace;
    font-size: 0.88rem;
  }

  header span,
  small,
  .lifecycle-only {
    color: var(--text-muted);
    font-size: 0.72rem;
  }

  .output,
  .field-output {
    position: relative;
  }

  .context-output {
    padding: 0.5rem 0.75rem;
    border-bottom: 1px solid var(--line);
    font-family: 'Geist Mono Variable', ui-monospace, monospace;
    font-size: 0.76rem;
  }

  .outputs {
    display: grid;
    padding: 0.5rem 0 0.75rem;
    overflow: visible;
  }

  .outputs-title {
    margin: 0;
    padding: 0.4rem 0.75rem 0;
    color: var(--text-muted);
    font-size: 0.72rem;
  }

  .field-output {
    display: grid;
    gap: 0.1rem;
    align-items: center;
    padding: 0.3rem 0.75rem;
  }

  .field-output span {
    overflow: hidden;
    font-family: 'Geist Mono Variable', ui-monospace, monospace;
    font-size: 0.72rem;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .lifecycle-only {
    margin: 0;
    padding: 0.75rem;
  }

  :global(.svelte-flow__handle) {
    width: 0.55rem;
    height: 0.55rem;
    background: var(--accent);
  }
</style>
