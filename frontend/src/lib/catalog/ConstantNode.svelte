<script lang="ts">
  import { getContext } from 'svelte';
  import { Handle, Position } from '@xyflow/svelte';

  import type { GraphConstantNodeData } from '$lib/api/generated';
  import { constantDataFromInput, constantInput } from './constantNode';
  import { constantForNode } from './nodeGraph';
  import {
    NODE_GRAPH_EDITOR_CONTEXT,
    type NodeGraphEditorContext
  } from './nodeGraphContext';

  let { id, data }: { id: string; data: GraphConstantNodeData } = $props();
  const editor = getContext<NodeGraphEditorContext>(NODE_GRAPH_EDITOR_CONTEXT);
  const descriptor = $derived(constantForNode(editor.catalog, data));
  const inputControl = $derived(constantInput(data.scalar_type));

  function updateValue(event: Event): void {
    const element = event.currentTarget as HTMLInputElement;
    const nextData = constantDataFromInput(data.scalar_type, element);
    if (nextData !== null) editor.setConstantData(id, nextData);
  }
</script>

<section class="functional-node" aria-label={`${descriptor.display_name} node`}>
  <header>
    <strong>{descriptor.display_name}</strong>
    <span>source</span>
  </header>
  <label class="nodrag nowheel">
    <span>{descriptor.output.display_name}</span>
    {#if inputControl.type === 'checkbox'}
      <input
        type="checkbox"
        checked={data.value === true}
        disabled={editor.readOnly}
        onchange={updateValue}
      />
    {:else}
      <input
        type={inputControl.type}
        value={data.value}
        step={inputControl.step}
        disabled={editor.readOnly}
        onchange={updateValue}
      />
    {/if}
    <Handle
      type="source"
      position={Position.Right}
      id={descriptor.output.handle_id}
      isConnectable={!editor.readOnly}
    />
  </label>
</section>

<style>
  .functional-node {
    width: 14rem;
    overflow: visible;
    border: 1px solid var(--line-strong);
    border-radius: 0.75rem;
    background: var(--surface-raised);
    box-shadow: 0 0.5rem 1.5rem rgb(8 15 30 / 12%);
  }
  header,
  label {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.65rem;
    padding: 0.65rem 0.75rem;
  }
  header {
    border-bottom: 1px solid var(--line);
  }
  header strong,
  label span {
    font-family: 'Geist Mono Variable', ui-monospace, monospace;
    font-size: 0.76rem;
  }
  header span {
    color: var(--text-muted);
    font-size: 0.7rem;
  }
  label {
    position: relative;
  }
  input[type='text'],
  input[type='number'] {
    min-width: 0;
    width: 7rem;
  }
  input:disabled {
    opacity: 1;
    color: var(--text);
    cursor: default;
    -webkit-text-fill-color: var(--text);
  }
  :global(.svelte-flow__handle) {
    width: 0.55rem;
    height: 0.55rem;
    background: var(--accent);
  }
</style>
