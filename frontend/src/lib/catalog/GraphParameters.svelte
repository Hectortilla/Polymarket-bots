<script lang="ts">
  import type { GraphConstantNodeData, GraphNodeCatalog, GraphParameter } from "$lib/api/generated";
  import { GRAPH_FIELD_COPY } from "$lib/catalog/copy";
  import catalogContract from "./catalogContract.fixture.json";
  import { constantDataFromDescriptor, constantDataFromInput } from "./constantNode";
  import {
    DEFAULT_OPERATION_SCALAR_TYPE,
    DEFAULT_PREVIEW_CASH,
    GRAPH_NODE_TYPE,
    GRAPH_PORT,
    GRAPH_SCALAR_TYPE,
  } from "./graphContracts";
  import "./graphPanels.css";
  import { graphNumberIsValid } from "./numberValue";
  let {
    parameters,
    catalog,
    onchange,
    readOnly = false,
  }: {
    parameters: GraphParameter[];
    catalog: GraphNodeCatalog;
    onchange: (parameters: GraphParameter[]) => void;
    readOnly?: boolean;
  } = $props();
  function update(id: string, changes: Partial<GraphParameter>) {
    onchange(parameters.map((item) => (item.id === id ? { ...item, ...changes } : item)));
  }
  function setValue(id: string, data: GraphConstantNodeData, input: HTMLInputElement) {
    const next = constantDataFromInput(data.scalar_type, input);
    if (next) update(id, { data: next });
  }
  function updateParameterType(id: string, scalarType: string) {
    const descriptor = catalog.constants.find((item) => item.scalar_type === scalarType);
    if (descriptor) update(id, { data: constantDataFromDescriptor(descriptor) });
  }
  function addParameter() {
    const descriptor = catalog.constants.find((item) => item.scalar_type === GRAPH_SCALAR_TYPE.number);
    if (!descriptor) throw new Error("Number descriptor is missing from the graph catalog");
    let suffix = 1;
    while (
      parameters.some((parameter) => parameter.id === `parameter-${suffix}` || parameter.name === `Parameter ${suffix}`)
    )
      suffix++;
    onchange([
      ...parameters,
      {
        id: `parameter-${suffix}`,
        name: `Parameter ${suffix}`,
        data: constantDataFromDescriptor(descriptor),
      },
    ]);
  }
</script>

<details class="graph-panel">
  <summary>Strategy parameters <span class="graph-panel-count">{parameters.length}</span></summary>
  <div class="graph-panel-body">
    <p class="graph-panel-intro">
      Name your strategy settings here, then add them to the graph from Parameters in the node picker. Each run keeps
      its saved values.
    </p>
    <div class="parameter-list">
      {#each parameters as parameter (parameter.id)}
        <div class="parameter-row">
          <label
            ><span>Name</span><input
              aria-label="Parameter name"
              maxlength={catalogContract.maximumParameterNameLength}
              value={parameter.name}
              disabled={readOnly}
              onchange={(event) => update(parameter.id, { name: event.currentTarget.value })}
            /></label
          >
          <label
            ><span>Type</span><select
              aria-label={GRAPH_FIELD_COPY.PARAMETER_TYPE}
              value={parameter.data.scalar_type}
              disabled={readOnly}
              onchange={(event) => updateParameterType(parameter.id, event.currentTarget.value)}
            >
              {#each catalog.constants as constant}<option value={constant.scalar_type}>{constant.display_name}</option
                >{/each}
            </select></label
          >
          <label class:boolean-value={parameter.data.scalar_type === GRAPH_SCALAR_TYPE.boolean}
            ><span>{GRAPH_FIELD_COPY.VALUE}</span>
            {#if parameter.data.scalar_type === GRAPH_SCALAR_TYPE.boolean}<input
                aria-label={GRAPH_FIELD_COPY.PARAMETER_VALUE}
                type="checkbox"
                checked={parameter.data.value}
                disabled={readOnly}
                onchange={(event) => setValue(parameter.id, parameter.data, event.currentTarget)}
              />
            {:else}<input
                aria-label={GRAPH_FIELD_COPY.PARAMETER_VALUE}
                type="text"
                value={parameter.data.value}
                disabled={readOnly}
                onchange={(event) => setValue(parameter.id, parameter.data, event.currentTarget)}
              />{/if}</label
          >
          {#if !readOnly}<button
              type="button"
              class="secondary remove-parameter"
              aria-label={`Remove ${parameter.name}`}
              onclick={() => onchange(parameters.filter((item) => item.id !== parameter.id))}>Remove</button
            >{/if}
          {#if parameter.data.scalar_type === GRAPH_SCALAR_TYPE.number && !graphNumberIsValid(parameter.data.value)}<p
              role="alert"
            >
              {GRAPH_FIELD_COPY.INVALID_NUMBER}
            </p>{/if}
        </div>
      {:else}<p class="empty-parameters">No parameters yet. Add a setting such as Budget or Entry threshold.</p>
      {/each}
    </div>
    <div class="graph-panel-actions">
      {#if !readOnly}<button
          type="button"
          disabled={parameters.length >= catalogContract.maximumParameters}
          onclick={addParameter}>Add parameter</button
        >{/if}
    </div>
  </div>
</details>

<style>
  .parameter-list {
    display: grid;
    gap: 1rem;
  }
  .parameter-row {
    display: grid;
    grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr) minmax(0, 1fr) auto;
    gap: 0.85rem;
    align-items: end;
  }
  .parameter-row + .parameter-row {
    border-top: 1px solid var(--line);
    padding-top: 1rem;
  }
  label {
    min-width: 0;
    display: grid;
    gap: 0.5rem;
    font-size: 0.75rem;
    color: var(--text-soft);
  }
  input,
  select {
    min-width: 0;
    width: 100%;
    min-height: 2.75rem;
  }
  input[type="checkbox"] {
    width: 1.15rem;
    height: 1.15rem;
    min-height: 0;
    margin: 0.8rem 0;
  }
  .remove-parameter {
    width: auto;
  }
  .empty-parameters {
    margin: 0;
    padding: 0.25rem 0;
    color: var(--text-muted);
    font-size: 0.82rem;
    line-height: 1.6;
  }
  [role="alert"] {
    grid-column: 1 / -1;
    color: var(--danger);
    margin: 0;
    font-size: 0.8rem;
  }
  @media (max-width: 700px) {
    .parameter-row {
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    }
    .parameter-row > label:first-child {
      grid-column: 1 / -1;
    }
    .remove-parameter {
      justify-self: start;
    }
  }
</style>
