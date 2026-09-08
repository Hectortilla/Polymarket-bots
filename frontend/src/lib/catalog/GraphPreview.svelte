<script lang="ts">
  import "./graphPanels.css";
  import { untrack } from 'svelte';
  import { previewGraph, type NodeGraph, type GraphNodeCatalog, type GraphPreviewResponse } from '$lib/api/generated';
  import { requestValidationIssues, requestErrorDetail } from '$lib/api/requestErrors';
  let { graph, catalog }: { graph: NodeGraph; catalog: GraphNodeCatalog } = $props();
  const initial = untrack(() => catalog.triggers.find(item => graph.nodes.some(node => node.type === 'trigger' && node.data.hook_name === item.hook_name)));
  let hook = $state(initial?.hook_name ?? '');
  let payloadText = $state(JSON.stringify(initial?.sample_payload ?? null, null, 2));
  let now = $state(String(initial?.sample_time_ms ?? 0));
  let cash = $state('1000');
  let positions = $state('[]');
  let busy = $state(false);
  let error = $state('');
  let result = $state<GraphPreviewResponse>();
  let evaluatedGraph = $state('');
  const triggers = $derived(catalog.triggers.filter(item => graph.nodes.some(node => node.type === 'trigger' && node.data.hook_name === item.hook_name)));
  const stale = $derived(result !== undefined && evaluatedGraph !== JSON.stringify(graph));
  function selectTrigger(value: string) {
    hook = value;
    const trigger = catalog.triggers.find(item => item.hook_name === value);
    payloadText = JSON.stringify(trigger?.sample_payload ?? null, null, 2);
    now = String(trigger?.sample_time_ms ?? 0);
    result = undefined;
  }
  async function runPreview() {
    busy = true; error = ''; result = undefined;
    try {
      const nowMs = Number(now);
      if (!Number.isSafeInteger(nowMs) || nowMs < 0) throw new Error('Virtual time requires a nonnegative whole number.');
      const snapshot = JSON.parse(JSON.stringify(graph)) as NodeGraph;
      const response = await previewGraph({ body: { graph: snapshot, hook_name: hook, now_ms: nowMs, payload: JSON.parse(payloadText), portfolio: { available_cash: cash, positions: JSON.parse(positions) } }, throwOnError: true });
      result = response.data;
      evaluatedGraph = JSON.stringify(snapshot);
    } catch (failure) {
      const issues = requestValidationIssues(failure);
      error = issues.length ? issues.map(issue => `${issue.loc.join(' → ')}: ${issue.msg}`).join('\n') : requestErrorDetail(failure) ?? (failure instanceof Error ? failure.message : 'Preview failed. Check the sample inputs.');
    } finally { busy = false; }
  }
</script>
<details class="graph-panel preview"><summary>Try this event</summary>
  <div class="graph-panel-body">
  <p class="graph-panel-intro">Inspect one event using sample data. Orders are shown as planned; no trades or fills occur. Each preview starts with fresh cooldown and deduplication state.</p>
  <div class="fields">
    <label>Trigger<select value={hook} onchange={event => selectTrigger(event.currentTarget.value)}>{#each triggers as trigger}<option value={trigger.hook_name}>{trigger.hook_name}</option>{/each}</select></label>
    <label>Virtual time (milliseconds)<input type="text" bind:value={now} /></label>
    <label>Available cash<input type="text" bind:value={cash} /></label>
  </div>
  <div class="sample-fields">
  <label>Sample event<textarea rows="9" bind:value={payloadText} spellcheck="false"></textarea></label>
  <label>Sample positions<textarea rows="3" bind:value={positions} spellcheck="false" placeholder={JSON.stringify([{ token_id: "example-token", size: "2", average_entry_price: "0.4" }])}></textarea></label>
  </div>
  <div class="preview-submit">
  <small>Keep exact numeric amounts in quotation marks in sample JSON. Timestamps use whole numbers.</small>
  <div class="graph-panel-actions"><button type="button" disabled={busy || !triggers.some(item => item.hook_name === hook)} onclick={runPreview}>{busy ? 'Evaluating…' : 'Preview decisions'}</button></div>
  </div>
  {#if error}<p role="alert" class="error">{error}</p>{/if}
  {#if result}
    {#if stale}<p role="status">The graph has changed. Preview again to see updated results.</p>{/if}
    <section class="result-section">
    <h4>Node results</h4>
    <div class="results"><table><thead><tr><th>Node</th><th>Output</th><th>Value</th><th>Status / reason</th></tr></thead><tbody>
      {#each result.nodes as node}
        {#each Object.entries(node.outputs) as [name, output]}<tr><td>{node.node_id}</td><td>{name}</td><td>{output.value === null ? 'Unavailable' : String(output.value)}</td><td>{output.status}{output.reason ? ` · ${output.reason}` : ''}{output.message ? ` · ${output.input_handle_id ?? ''}: ${output.message}` : ''}</td></tr>{/each}
      {/each}
    </tbody></table></div>
    </section>
    <section class="result-section">
    <h4>Intended orders ({result.intended_orders.length})</h4>
    {#each result.intended_orders as order}<p>{order.side} {order.size} shares of {order.token_id} at a limit of {order.price} — planned</p>{:else}<p>No order requested for this sample.</p>{/each}
    </section>
  {/if}
  </div>
</details>
<style>
  label { min-width: 0; display: grid; gap: .6rem; margin: 0; font-size: .8rem; color: var(--text-soft); }
  .fields { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1rem; }
  .sample-fields { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr); gap: 1rem; }
  input, select, textarea { min-width: 0; width: 100%; }
  textarea { padding: .85rem; font-family: 'Geist Mono Variable', monospace; font-size: .78rem; line-height: 1.6; resize: vertical; min-height: 12rem; }
  .preview-submit { display: grid; gap: .85rem; }
  small { display: block; color: var(--text-muted); font-size: .75rem; line-height: 1.6; }
  .error { white-space: pre-wrap; color: var(--danger); margin: 0; }
  .result-section { min-width: 0; display: grid; gap: .85rem; border-top: 1px solid var(--line); padding-top: 1.25rem; }
  h4, .result-section p { margin: 0; }
  h4 { font-size: .85rem; }
  .result-section p { font-size: .82rem; line-height: 1.6; overflow-wrap: anywhere; }
  .results { overflow: auto; max-height: 24rem; }
  table { width: 100%; border-collapse: collapse; font-size: .8rem; }
  td, th { padding: .7rem .8rem; text-align: left; border-bottom: 1px solid var(--line); }
  th { color: var(--text-muted); font-weight: 550; white-space: nowrap; }
  @media (max-width: 700px) { .fields, .sample-fields { grid-template-columns: 1fr; } }
</style>
