<script lang="ts">
  import { previewGraph, type GraphNodeCatalog, type GraphPreviewResponse, type NodeGraph } from "$lib/api/generated";
  import { requestErrorDetail, requestValidationIssues } from "$lib/api/requestErrors";
  import { GRAPH_FIELD_COPY, GRAPH_PREVIEW_COPY, intendedOrdersLabel } from "$lib/catalog/copy";
  import { isNonnegativeInteger } from "$lib/valueGuards";
  import { untrack } from "svelte";
  import {
    DEFAULT_OPERATION_SCALAR_TYPE,
    DEFAULT_PREVIEW_CASH,
    GRAPH_NODE_TYPE,
    GRAPH_PORT,
    GRAPH_SCALAR_TYPE,
  } from "./graphContracts";
  import "./graphPanels.css";
  let { graph, catalog }: { graph: NodeGraph; catalog: GraphNodeCatalog } = $props();
  const initialTrigger = untrack(() => triggersForGraph()[0]);
  let hook = $state(initialTrigger?.hook_name ?? "");
  let payloadText = $state(JSON.stringify(initialTrigger?.sample_payload ?? null, null, 2));
  let virtualTimestampText = $state(String(initialTrigger?.sample_time_ms ?? 0));
  let cash = $state(DEFAULT_PREVIEW_CASH);
  let positions = $state(untrack(() => JSON.stringify(catalog.sample_positions ?? [], null, 2)));
  let busy = $state(false);
  let error = $state("");
  let result = $state<GraphPreviewResponse>();
  let evaluatedGraph = $state("");
  const triggers = $derived(triggersForGraph());
  const stale = $derived(result !== undefined && evaluatedGraph !== JSON.stringify(graph));
  function selectTrigger(value: string) {
    hook = value;
    const trigger = catalog.triggers.find((item) => item.hook_name === value);
    payloadText = JSON.stringify(trigger?.sample_payload ?? null, null, 2);
    virtualTimestampText = String(trigger?.sample_time_ms ?? 0);
    result = undefined;
  }
  async function runPreview() {
    busy = true;
    error = "";
    result = undefined;
    try {
      const nowMs = Number(virtualTimestampText);
      if (!isNonnegativeInteger(nowMs)) throw new Error("Virtual time requires a nonnegative whole number.");
      const snapshot = JSON.parse(JSON.stringify(graph)) as NodeGraph;
      const response = await previewGraph({
        body: {
          graph: snapshot,
          hook_name: hook,
          now_ms: nowMs,
          payload: JSON.parse(payloadText),
          portfolio: { available_cash: cash, positions: JSON.parse(positions) },
        },
        throwOnError: true,
      });
      result = response.data;
      evaluatedGraph = JSON.stringify(snapshot);
    } catch (failure) {
      error = previewErrorMessage(failure);
    } finally {
      busy = false;
    }
  }
  function triggersForGraph() {
    const hooks = new Set(
      graph.nodes.filter((node) => node.type === GRAPH_NODE_TYPE.trigger).map((node) => node.data.hook_name),
    );
    return catalog.triggers.filter((trigger) => hooks.has(trigger.hook_name));
  }
  function previewErrorMessage(failure: unknown): string {
    const issues = requestValidationIssues(failure);
    if (issues.length) return issues.map((issue) => `${issue.loc.join(" → ")}: ${issue.msg}`).join("\n");
    const detail = requestErrorDetail(failure);
    if (detail) return detail;
    if (failure instanceof Error) return failure.message;
    return GRAPH_PREVIEW_COPY.ERROR;
  }
  function previewOutputDetails(output: GraphPreviewResponse["nodes"][number]["outputs"][string]): string {
    const reason = output.reason ? ` · ${output.reason}` : "";
    const message = output.message ? ` · ${output.input_handle_id ?? ""}: ${output.message}` : "";
    return `${output.status}${reason}${message}`;
  }
</script>

<details class="graph-panel preview">
  <summary>Try this event</summary>
  <div class="graph-panel-body">
    <p class="graph-panel-intro">
      Inspect one event using sample data. Orders are shown as planned; no trades or fills occur. Each preview starts
      with fresh cooldown and deduplication state.
    </p>
    <div class="fields">
      <label
        >Trigger<select value={hook} onchange={(event) => selectTrigger(event.currentTarget.value)}
          >{#each triggers as trigger}<option value={trigger.hook_name}>{trigger.hook_name}</option>{/each}</select
        ></label
      >
      <label>Virtual time (milliseconds)<input type="text" bind:value={virtualTimestampText} /></label>
      <label>{GRAPH_PREVIEW_COPY.AVAILABLE_CASH}<input type="text" bind:value={cash} /></label>
    </div>
    <div class="sample-fields">
      <label
        >{GRAPH_PREVIEW_COPY.SAMPLE_EVENT}<textarea rows="9" bind:value={payloadText} spellcheck="false"
        ></textarea></label
      >
      <label
        >{GRAPH_PREVIEW_COPY.SAMPLE_POSITIONS}<textarea rows="3" bind:value={positions} spellcheck="false"
        ></textarea></label
      >
    </div>
    <div class="preview-submit">
      <small>Keep exact numeric amounts in quotation marks in sample JSON. Timestamps use whole numbers.</small>
      <div class="graph-panel-actions">
        <button type="button" disabled={busy || !triggers.some((item) => item.hook_name === hook)} onclick={runPreview}
          >{busy ? GRAPH_PREVIEW_COPY.BUSY : GRAPH_PREVIEW_COPY.PREVIEW}</button
        >
      </div>
    </div>
    {#if error}<p role="alert" class="error">{error}</p>{/if}
    {#if result}
      {#if stale}<p role="status">The graph has changed. Preview again to see updated results.</p>{/if}
      <section class="result-section">
        <h4>{GRAPH_PREVIEW_COPY.NODE_RESULTS}</h4>
        <div class="results">
          <table>
            <thead><tr><th>Node</th><th>Output</th><th>{GRAPH_FIELD_COPY.VALUE}</th><th>Status / reason</th></tr></thead
            ><tbody>
              {#each result.nodes as node}
                {#each Object.entries(node.outputs) as [outputHandleId, output]}<tr
                    ><td>{node.node_id}</td><td>{outputHandleId}</td><td
                      >{output.value === null ? GRAPH_PREVIEW_COPY.UNAVAILABLE : String(output.value)}</td
                    ><td>{previewOutputDetails(output)}</td></tr
                  >{/each}
              {/each}
            </tbody>
          </table>
        </div>
      </section>
      <section class="result-section">
        <h4>{intendedOrdersLabel(result.intended_orders.length)}</h4>
        {#each result.intended_orders as order}<p>
            {order.side}
            {order.size} shares of {order.token_id} at a limit of {order.price} — planned
          </p>{:else}<p>{GRAPH_PREVIEW_COPY.NO_ORDER}</p>{/each}
      </section>
    {/if}
  </div>
</details>

<style>
  label {
    min-width: 0;
    display: grid;
    gap: 0.6rem;
    margin: 0;
    font-size: 0.8rem;
    color: var(--text-soft);
  }
  .fields {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 1rem;
  }
  .sample-fields {
    display: grid;
    grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr);
    gap: 1rem;
  }
  input,
  select,
  textarea {
    min-width: 0;
    width: 100%;
  }
  textarea {
    padding: 0.85rem;
    font-family: "Geist Mono Variable", monospace;
    font-size: 0.78rem;
    line-height: 1.6;
    resize: vertical;
    min-height: 12rem;
  }
  .preview-submit {
    display: grid;
    gap: 0.85rem;
  }
  small {
    display: block;
    color: var(--text-muted);
    font-size: 0.75rem;
    line-height: 1.6;
  }
  .error {
    white-space: pre-wrap;
    color: var(--danger);
    margin: 0;
  }
  .result-section {
    min-width: 0;
    display: grid;
    gap: 0.85rem;
    border-top: 1px solid var(--line);
    padding-top: 1.25rem;
  }
  h4,
  .result-section p {
    margin: 0;
  }
  h4 {
    font-size: 0.85rem;
  }
  .result-section p {
    font-size: 0.82rem;
    line-height: 1.6;
    overflow-wrap: anywhere;
  }
  .results {
    overflow: auto;
    max-height: 24rem;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.8rem;
  }
  td,
  th {
    padding: 0.7rem 0.8rem;
    text-align: left;
    border-bottom: 1px solid var(--line);
  }
  th {
    color: var(--text-muted);
    font-weight: 550;
    white-space: nowrap;
  }
  @media (max-width: 700px) {
    .fields,
    .sample-fields {
      grid-template-columns: 1fr;
    }
  }
</style>
