<script lang="ts">
  import { useNodesInitialized, useSvelteFlow, useViewportInitialized, type FitViewOptions } from "@xyflow/svelte";
  import { untrack } from "svelte";

  let { canvasReady, options }: { canvasReady: boolean; options: FitViewOptions } = $props();
  const nodesInitialized = useNodesInitialized();
  const viewportInitialized = useViewportInitialized();
  const { fitView } = useSvelteFlow();
  let fitted = false;

  // Flow's initial fit can run after only the first batch of nodes is measured.
  // Wait for the entire graph, then leave subsequent viewport changes to the user.
  $effect(() => {
    if (fitted || !canvasReady || !nodesInitialized.current || !viewportInitialized.current) return;
    fitted = true;
    untrack(() => void fitView(options));
  });
</script>
