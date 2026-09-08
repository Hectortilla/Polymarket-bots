<script lang="ts">
  import type { GraphOperationNodeData, GraphScalarType } from '$lib/api/generated';
  import { GRAPH_FIELD_COPY } from '$lib/catalog/copy';
  import { operationForNode } from '$lib/catalog/nodeGraph/catalog';
  import { type CanvasNode } from '$lib/catalog/nodeGraph/contracts';
  import { inputsForNode, outputsForNode } from '$lib/catalog/nodeGraph/ports';
  import { Handle, Position, useUpdateNodeInternals } from '@xyflow/svelte';
  import { getContext } from 'svelte';
  import {
    DEFAULT_OPERATION_SCALAR_TYPE,
    DEFAULT_PREVIEW_CASH,
    GRAPH_NODE_TYPE,
    GRAPH_PORT,
    GRAPH_SCALAR_TYPE,
  } from './graphContracts';
  import { NODE_GRAPH_EDITOR_CONTEXT, type NodeGraphEditorContext } from './nodeGraphContext';
  import NodeIssues from './NodeIssues.svelte';
  let { id, data }: { id: string; data: GraphOperationNodeData } = $props();
  const editor = getContext<NodeGraphEditorContext>(NODE_GRAPH_EDITOR_CONTEXT);
  const updateInternals = useUpdateNodeInternals();
  const node = $derived<CanvasNode>({
    id,
    data,
    type: GRAPH_NODE_TYPE.operation,
    position: { x: 0, y: 0 },
  });
  const descriptor = $derived(operationForNode(editor.catalog, data));
  const inputs = $derived(inputsForNode(node, editor.catalog));
  const outputs = $derived(outputsForNode(node, editor.catalog));
  $effect(() => {
    inputs;
    outputs;
    updateInternals(id);
  });
  function addInput() {
    const ids = inputs.map((port) => port.handle_id);
    let suffix = 1;
    while (ids.includes(`input_${suffix}`)) suffix++;
    editor.setOperationData(id, { ...data, input_ids: [...ids, `input_${suffix}`] });
  }
  function removeInput(inputHandleId: string) {
    const remainingInputIds = inputs
      .filter((port) => port.handle_id !== inputHandleId)
      .map((port) => port.handle_id);
    editor.setOperationData(id, { ...data, input_ids: remainingInputIds });
  }
  function selectOperation(operationName: string) {
    const next = editor.catalog.operations?.find((item) => item.operation === operationName);
    if (!next) return;
    editor.setOperationData(id, {
      operation: next.operation,
      scalar_type: data.scalar_type,
      input_ids: next.expandable ? next.inputs.map((port) => port.handle_id) : [],
    });
  }
</script>

<section class="operation-node" aria-label={`${descriptor.display_name} node`}>
  <header><strong>{descriptor.display_name}</strong><small>{descriptor.category}</small></header>
  <div class="nodrag nowheel settings">
    <select
      aria-label="Operation"
      disabled={editor.readOnly}
      value={data.operation}
      onchange={(event) => selectOperation(event.currentTarget.value)}
    >
      {#each editor.catalog.operations ?? [] as operation}<option value={operation.operation}
          >{operation.display_name}</option
        >{/each}
    </select>
    {#if descriptor.selectable_scalar_type}
      <select
        aria-label={GRAPH_FIELD_COPY.VALUE_TYPE}
        disabled={editor.readOnly}
        value={data.scalar_type ?? DEFAULT_OPERATION_SCALAR_TYPE}
        onchange={(event) =>
          editor.setOperationData(id, {
            ...data,
            scalar_type: event.currentTarget.value as GraphScalarType,
          })}
      >
        {#each editor.catalog.constants as constant}<option value={constant.scalar_type}
            >{constant.display_name}</option
          >{/each}
      </select>
    {/if}
  </div>
  {#each inputs as port (port.handle_id)}
    <div class="port">
      <Handle
        type="target"
        position={Position.Left}
        id={port.handle_id}
        isConnectable={!editor.readOnly}
      /><span title={port.description ?? undefined}
        >{port.display_name}{port.required ? '' : ' (optional)'}</span
      ><small>{port.whole_number ? 'Whole number' : port.scalar_types.join(' / ')}</small>
      {#if descriptor.expandable && inputs.length > (descriptor.minimum_inputs ?? 0) && !editor.readOnly}<button
          type="button"
          class="nodrag"
          aria-label={`Remove ${port.handle_id}`}
          onclick={() => removeInput(port.handle_id)}>×</button
        >{/if}
    </div>
  {/each}
  {#if descriptor.expandable && !editor.readOnly}<button
      type="button"
      class="nodrag"
      disabled={inputs.length >= (descriptor.maximum_inputs ?? Infinity)}
      onclick={addInput}>Add input</button
    >{/if}
  {#each outputs as port (port.handle_id)}<div class="port">
      <span>{port.display_name}</span><small>{port.scalar_type}</small><Handle
        type="source"
        position={Position.Right}
        id={port.handle_id}
        isConnectable={!editor.readOnly}
      />
    </div>{/each}
  <NodeIssues {id} />
</section>

<style>
  .operation-node {
    width: 18rem;
    border: 1px solid var(--line-strong);
    border-radius: 0.75rem;
    background: var(--surface-raised);
  }
  header,
  .port,
  .settings {
    position: relative;
    padding: 0.65rem 0.75rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
  }
  header {
    border-bottom: 1px solid var(--line);
  }
  small {
    color: var(--text-muted);
    font-size: 0.65rem;
  }
  strong,
  span {
    font-size: 0.76rem;
  }
  select {
    width: 100%;
  }
  .settings {
    flex-wrap: wrap;
  }
</style>
