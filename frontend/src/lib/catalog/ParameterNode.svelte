<script lang="ts">
  import NodeIssues from './NodeIssues.svelte';
  import { getContext } from 'svelte';
  import { Handle, Position } from '@xyflow/svelte';
  import type { GraphParameterNodeData } from '$lib/api/generated';
  import { NODE_GRAPH_EDITOR_CONTEXT, type NodeGraphEditorContext } from './nodeGraphContext';
  let { id = "", data }: { id?: string; data: GraphParameterNodeData } = $props();
  const editor = getContext<NodeGraphEditorContext>(NODE_GRAPH_EDITOR_CONTEXT);
  const parameter = $derived(editor.parameters.find(item => item.id === data.parameter_id));
</script>
<section aria-label="Parameter node"><strong>{parameter?.name ?? 'Missing parameter'}</strong><span>{String(parameter?.data.value ?? '')}</span><Handle type="source" position={Position.Right} id="value" isConnectable={!editor.readOnly && !!parameter} /><NodeIssues {id} /></section>
<style>section { position: relative; width: 14rem; padding: .8rem; border: 1px solid var(--line-strong); border-radius: .75rem; background: var(--surface-raised); display: grid; gap: .5rem; font-size: .8rem; } span { color: var(--text-muted); }</style>
