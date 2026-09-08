<script lang="ts">
  import NodeIssues from './NodeIssues.svelte';
  import { getContext } from 'svelte';
  import { Handle, Position, useUpdateNodeInternals } from '@xyflow/svelte';
  import type { GraphOperationNodeData, GraphScalarType } from '$lib/api/generated';
  import { inputsForNode, outputsForNode, operationForNode, type CanvasNode } from './nodeGraph';
  import { NODE_GRAPH_EDITOR_CONTEXT, type NodeGraphEditorContext } from './nodeGraphContext';
  let { id, data }: { id: string; data: GraphOperationNodeData } = $props();
  const editor = getContext<NodeGraphEditorContext>(NODE_GRAPH_EDITOR_CONTEXT);
  const updateInternals = useUpdateNodeInternals();
  const node = $derived<CanvasNode>({ id, data, type: 'operation', position: { x: 0, y: 0 } });
  const descriptor = $derived(operationForNode(editor.catalog, data));
  const inputs = $derived(inputsForNode(node, editor.catalog));
  const outputs = $derived(outputsForNode(node, editor.catalog));
  $effect(() => { inputs; outputs; updateInternals(id); });
  function addInput() {
    const ids = inputs.map(port => port.handle_id);
    let suffix = 1;
    while (ids.includes(`input_${suffix}`)) suffix++;
    editor.setOperationData(id, { ...data, input_ids: [...ids, `input_${suffix}`] });
  }
</script>
<section class="operation-node" aria-label={`${descriptor.display_name} node`}>
  <header><strong>{descriptor.display_name}</strong><small>{descriptor.category}</small></header>
  <div class="nodrag nowheel settings">
    <select aria-label="Operation" disabled={editor.readOnly} value={data.operation} onchange={event => {
      const next = editor.catalog.operations?.find(item => item.operation === event.currentTarget.value);
      if (next) editor.setOperationData(id, { operation: next.operation, scalar_type: data.scalar_type, input_ids: next.expandable ? next.inputs.map(port => port.handle_id) : [] });
    }}>
      {#each editor.catalog.operations ?? [] as operation}<option value={operation.operation}>{operation.display_name}</option>{/each}
    </select>
    {#if descriptor.selectable_scalar_type}
      <select aria-label="Value type" disabled={editor.readOnly} value={data.scalar_type ?? 'number'} onchange={event => editor.setOperationData(id, { ...data, scalar_type: event.currentTarget.value as GraphScalarType })}>
        {#each editor.catalog.constants as constant}<option value={constant.scalar_type}>{constant.display_name}</option>{/each}
      </select>
    {/if}
  </div>
  {#each inputs as port (port.handle_id)}
    <div class="port"><Handle type="target" position={Position.Left} id={port.handle_id} isConnectable={!editor.readOnly} /><span title={port.description ?? undefined}>{port.display_name}{port.required ? '' : ' (optional)'}</span><small>{port.whole_number ? 'Whole number' : port.scalar_types.join(' / ')}</small>
      {#if descriptor.expandable && inputs.length > (descriptor.minimum_inputs ?? 0) && !editor.readOnly}<button type="button" class="nodrag" aria-label={`Remove ${port.handle_id}`} onclick={() => editor.setOperationData(id, { ...data, input_ids: inputs.filter(p => p.handle_id !== port.handle_id).map(p => p.handle_id) })}>×</button>{/if}
    </div>
  {/each}
  {#if descriptor.expandable && !editor.readOnly}<button type="button" class="nodrag" disabled={inputs.length >= (descriptor.maximum_inputs ?? Infinity)} onclick={addInput}>Add input</button>{/if}
  {#each outputs as port (port.handle_id)}<div class="port"><span>{port.display_name}</span><small>{port.scalar_type}</small><Handle type="source" position={Position.Right} id={port.handle_id} isConnectable={!editor.readOnly} /></div>{/each}
<NodeIssues {id} /></section>
<style>
  .operation-node { width: 18rem; border: 1px solid var(--line-strong); border-radius: .75rem; background: var(--surface-raised); }
  header, .port, .settings { position: relative; padding: .65rem .75rem; display: flex; align-items: center; justify-content: space-between; gap: .5rem; }
  header { border-bottom: 1px solid var(--line); } small { color: var(--text-muted); font-size: .65rem; } strong, span { font-size: .76rem; } select { width: 100%; } .settings { flex-wrap: wrap; }
</style>
