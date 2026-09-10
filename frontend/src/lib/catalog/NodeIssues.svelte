<script lang="ts">
  import { getContext } from "svelte";
  import { NODE_GRAPH_EDITOR_CONTEXT, type NodeGraphEditorContext } from "./nodeGraphContext";
  let { id }: { id: string } = $props();
  const editor = getContext<NodeGraphEditorContext>(NODE_GRAPH_EDITOR_CONTEXT);
  const issues = $derived(editor.issuesForNode?.(id) ?? []);
</script>

{#if issues.length}<div role="alert" class="node-issues">
    {#each issues as issue}<p>{issue}</p>{/each}
  </div>{/if}

<style>
  .node-issues {
    padding: 0.4rem 0.7rem;
    color: var(--danger);
    border-top: 1px solid var(--danger);
    font-size: 0.7rem;
  }
  p {
    margin: 0.2rem 0;
  }
</style>
