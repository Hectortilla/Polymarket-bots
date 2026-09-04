<script lang="ts">
  import CopySimpleIcon from 'phosphor-svelte/lib/CopySimpleIcon';

  import type { BotRead, NodeGraph } from '$lib/api/generated';
  import { cloneNodeGraph } from '$lib/catalog/graphContracts';
  import { GRAPH_SOURCE_COPY } from './graphSource';

  let {
    bots,
    starterGraph,
    excludeBotId,
    onselect
  }: {
    bots: BotRead[];
    starterGraph: NodeGraph;
    excludeBotId?: string;
    onselect: (graph: NodeGraph, sourceName: string) => void;
  } = $props();

  const START_FRESH = '__start_fresh__';
  const graphBots = $derived(
    bots.filter(
      (bot) => bot.id !== excludeBotId && bot.latest_graph_revision !== null
        && bot.latest_graph_revision !== undefined
    )
  );
  let selectedSource = $state(START_FRESH);

  function applySource(): void {
    if (selectedSource === START_FRESH) {
      onselect(cloneNodeGraph(starterGraph), GRAPH_SOURCE_COPY.FRESH);
      return;
    }
    const source = graphBots.find((bot) => bot.id === selectedSource);
    const graph = source?.latest_graph_revision?.graph;
    if (source && graph) {
      onselect(cloneNodeGraph(graph), source.config.name);
    }
  }
</script>

<div class="graph-source-picker">
  <div>
    <label class="field-label" for="graph-source">Starting point</label>
    <span class="field-helper" id="graph-source-helper">
      Start with the default graph or copy the latest strategy from another bot.
    </span>
    <select id="graph-source" aria-describedby="graph-source-helper" bind:value={selectedSource}>
      <option value={START_FRESH}>Start fresh</option>
      {#each graphBots as source (source.id)}
        <option value={source.id}>{source.config.name}</option>
      {/each}
    </select>
  </div>
  <button class="secondary" type="button" onclick={applySource}>
    <CopySimpleIcon aria-hidden="true" size={17} />
    {selectedSource === START_FRESH ? 'Reset graph' : 'Copy graph'}
  </button>
</div>
