<script lang="ts">
  import "./graphPanels.css";
  import { graphNumberIsValid } from './numberValue';
  import catalogContract from "./catalogContract.fixture.json";
  import type { GraphParameter, GraphNodeCatalog, GraphConstantNodeData } from '$lib/api/generated';
  import { constantDataFromDescriptor, constantDataFromInput } from './constantNode';
  let { parameters, catalog, onchange, readOnly = false }: { parameters: GraphParameter[]; catalog: GraphNodeCatalog; onchange: (parameters: GraphParameter[]) => void; readOnly?: boolean } = $props();
  function update(id: string, changes: Partial<GraphParameter>) { onchange(parameters.map(item => item.id === id ? { ...item, ...changes } : item)); }
  function setValue(id: string, data: GraphConstantNodeData, input: HTMLInputElement) { const next = constantDataFromInput(data.scalar_type, input); if (next) update(id, { data: next }); }
</script>
<details class="graph-panel"><summary>Strategy parameters <span class="graph-panel-count">{parameters.length}</span></summary>
  <div class="graph-panel-body">
  <p class="graph-panel-intro">Name your strategy settings here, then add them to the graph from Parameters in the node picker. Each run keeps its saved values.</p>
  <div class="parameter-list">
  {#each parameters as parameter (parameter.id)}
    <div class="parameter-row">
      <label><span>Name</span><input aria-label="Parameter name" maxlength={catalogContract.maximumParameterNameLength} value={parameter.name} disabled={readOnly} onchange={event => update(parameter.id, { name: event.currentTarget.value })} /></label>
      <label><span>Type</span><select aria-label="Parameter type" value={parameter.data.scalar_type} disabled={readOnly} onchange={event => { const descriptor = catalog.constants.find(item => item.scalar_type === event.currentTarget.value); if (descriptor) update(parameter.id, { data: constantDataFromDescriptor(descriptor) }); }}>
        {#each catalog.constants as constant}<option value={constant.scalar_type}>{constant.display_name}</option>{/each}
      </select></label>
      <label class:boolean-value={parameter.data.scalar_type === 'boolean'}><span>Value</span>
      {#if parameter.data.scalar_type === 'boolean'}<input aria-label="Parameter value" type="checkbox" checked={parameter.data.value} disabled={readOnly} onchange={event => setValue(parameter.id, parameter.data, event.currentTarget)} />
      {:else}<input aria-label="Parameter value" type="text" value={parameter.data.value} disabled={readOnly} onchange={event => setValue(parameter.id, parameter.data, event.currentTarget)} />{/if}</label>
      {#if !readOnly}<button type="button" class="secondary remove-parameter" aria-label={`Remove ${parameter.name}`} onclick={() => onchange(parameters.filter(item => item.id !== parameter.id))}>Remove</button>{/if}
      {#if parameter.data.scalar_type === "number" && !graphNumberIsValid(parameter.data.value)}<p role="alert">Enter a finite Number within the supported range.</p>{/if}
    </div>
  {:else}<p class="empty-parameters">No parameters yet. Add a setting such as Budget or Entry threshold.</p>
  {/each}
  </div>
  <div class="graph-panel-actions">
  {#if !readOnly}<button type="button" disabled={parameters.length >= catalogContract.maximumParameters} onclick={() => { let suffix = 1; while (parameters.some(p => p.id === `parameter-${suffix}` || p.name === `Parameter ${suffix}`)) suffix++; onchange([...parameters, { id: `parameter-${suffix}`, name: `Parameter ${suffix}`, data: { scalar_type: 'number', value: '0' } }]); }}>Add parameter</button>{/if}
  </div>
  </div>
</details>
<style>
  .parameter-list { display: grid; gap: 1rem; }
  .parameter-row { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr) minmax(0, 1fr) auto; gap: .85rem; align-items: end; }
  .parameter-row + .parameter-row { border-top: 1px solid var(--line); padding-top: 1rem; }
  label { min-width: 0; display: grid; gap: .5rem; font-size: .75rem; color: var(--text-soft); }
  input, select { min-width: 0; width: 100%; min-height: 2.75rem; }
  input[type='checkbox'] { width: 1.15rem; height: 1.15rem; min-height: 0; margin: .8rem 0; }
  .remove-parameter { width: auto; }
  .empty-parameters { margin: 0; padding: .25rem 0; color: var(--text-muted); font-size: .82rem; line-height: 1.6; }
  [role='alert'] { grid-column: 1 / -1; color: var(--danger); margin: 0; font-size: .8rem; }
  @media (max-width: 700px) {
    .parameter-row { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
    .parameter-row > label:first-child { grid-column: 1 / -1; }
    .remove-parameter { justify-self: start; }
  }
</style>
