<script lang="ts">
  import { getContext } from 'svelte';
  import { Handle, Position } from '@xyflow/svelte';

  import type { GraphNodeData } from '$lib/api/generated';
  import { outputPathIsSelected, triggerForNode } from './nodeGraph';
  import {
    TRIGGER_NODE_EDITOR_CONTEXT,
    type TriggerNodeEditorContext
  } from './triggerNodeContext';

  let { id, data }: { id: string; data: GraphNodeData } = $props();

  const editor = getContext<TriggerNodeEditorContext>(
    TRIGGER_NODE_EDITOR_CONTEXT
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
    <fieldset class="nodrag nowheel">
      <legend>{trigger.payload.type_name} outputs</legend>
      {#each trigger.payload.fields as field (field.handle_id)}
        {@const selected = outputPathIsSelected(data, field.path)}
        <label>
          <input
            type="checkbox"
            checked={selected}
            aria-label={field.display_name}
            onchange={(event) =>
              editor.setOutputSelected(id, field.path, event.currentTarget.checked)}
          />
          <span>{field.display_name}</span>
          <small>
            {field.collection ? `collection<${field.value_type}>` : field.value_type}{field.nullable ? ' | null' : ''}
          </small>
          {#if selected}
            <Handle
              type="source"
              position={Position.Right}
              id={field.handle_id}
              isConnectable={false}
            />
          {/if}
        </label>
      {/each}
    </fieldset>
  {:else}
    <p class="lifecycle-only">Lifecycle trigger with context only.</p>
  {/if}
</section>

<style>
  .trigger-node {
    width: 20rem;
    overflow: hidden;
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
  fieldset label {
    position: relative;
  }

  .context-output {
    padding: 0.5rem 0.75rem;
    border-bottom: 1px solid var(--line);
    font-family: 'Geist Mono Variable', ui-monospace, monospace;
    font-size: 0.76rem;
  }

  fieldset {
    display: grid;
    max-height: 15rem;
    margin: 0;
    padding: 0.5rem 0.75rem 0.75rem;
    overflow-y: auto;
    overscroll-behavior: contain;
    border: 0;
    scrollbar-color: var(--control-line) transparent;
    scrollbar-width: thin;
  }

  fieldset::-webkit-scrollbar {
    width: 0.4rem;
  }

  fieldset::-webkit-scrollbar-thumb {
    border-radius: 1rem;
    background: var(--control-line);
  }

  fieldset::-webkit-scrollbar-track {
    background: transparent;
  }

  legend {
    padding-top: 0.4rem;
    color: var(--text-muted);
    font-size: 0.72rem;
  }

  fieldset label {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 0.1rem 0.45rem;
    align-items: center;
    padding: 0.3rem 0;
    cursor: pointer;
  }

  fieldset label span {
    overflow: hidden;
    font-family: 'Geist Mono Variable', ui-monospace, monospace;
    font-size: 0.72rem;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  fieldset small {
    grid-column: 2;
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
