<script lang="ts">
  import type { GraphParameterNodeData } from "$lib/api/generated";
  import { Handle, Position } from "@xyflow/svelte";
  import { getContext } from "svelte";
  import {
    DEFAULT_OPERATION_SCALAR_TYPE,
    DEFAULT_PREVIEW_CASH,
    GRAPH_NODE_TYPE,
    GRAPH_PORT,
    GRAPH_SCALAR_TYPE,
  } from "./graphContracts";
  import { NODE_GRAPH_EDITOR_CONTEXT, type NodeGraphEditorContext } from "./nodeGraphContext";
  import NodeIssues from "./NodeIssues.svelte";
  let { id = "", data }: { id?: string; data: GraphParameterNodeData } = $props();
  const editor = getContext<NodeGraphEditorContext>(NODE_GRAPH_EDITOR_CONTEXT);
  const parameter = $derived(editor.parameters.find((item) => item.id === data.parameter_id));
</script>

<section aria-label="Parameter node">
  <strong>{parameter?.name ?? "Missing parameter"}</strong><span>{String(parameter?.data.value ?? "")}</span><Handle
    type="source"
    position={Position.Right}
    id={GRAPH_PORT.VALUE}
    isConnectable={!editor.readOnly && !!parameter}
  /><NodeIssues {id} />
</section>

<style>
  section {
    position: relative;
    width: 14rem;
    padding: 0.8rem;
    border: 1px solid var(--line-strong);
    border-radius: var(--radius-surface);
    background: var(--surface-raised);
    display: grid;
    gap: 0.5rem;
    font-size: 0.8rem;
  }
  span {
    color: var(--text-muted);
  }
</style>
