<script lang="ts">
  import type { AnySchemaObject } from 'ajv';

  import type {
    BotDefinitionDescriptor,
    GraphNodeCatalog,
    NodeGraph
  } from '$lib/api/generated';
  import NodeGraphInput from './NodeGraphInput.svelte';
  import {
    WIDGET_KIND,
    fieldLabel,
    initialLaunchInputs,
    launchFields,
    launchValidator,
    resolvedFieldSchema,
    selectionExplanation,
    validationMessages,
    widgetKind,
    type LaunchInputs
  } from './schema';

  let {
    descriptor,
    onsubmit,
    busy = false
  }: {
    descriptor: BotDefinitionDescriptor;
    onsubmit: (inputs: LaunchInputs) => void | Promise<void>;
    busy?: boolean;
  } = $props();

  const fields = $derived(launchFields(descriptor));
  const validator = $derived(launchValidator(descriptor));
  let inputs = $state<LaunchInputs>({});
  let activeDefinitionId = $state('');
  let errors = $state<string[]>([]);

  $effect(() => {
    if (activeDefinitionId !== descriptor.definition_id) {
      activeDefinitionId = descriptor.definition_id;
      inputs = initialLaunchInputs(descriptor);
      errors = [];
    }
  });

  function update(name: string, value: unknown): void {
    inputs = { ...inputs, [name]: value };
    errors = validationMessages(validator, inputs);
  }

  function updateList(name: string, value: string): void {
    update(
      name,
      value
        .split(/[\n,]/)
        .map((item) => item.trim())
        .filter(Boolean)
    );
  }

  function updateJson(name: string, value: string): void {
    try {
      update(name, JSON.parse(value));
    } catch {
      update(name, value);
    }
  }

  function inputType(field: AnySchemaObject): string {
    const type = resolvedFieldSchema(descriptor, field).type;
    return type === 'integer' || type === 'number' ? 'number' : 'text';
  }

  function parseFieldInput(field: AnySchemaObject, value: string): string | number {
    return inputType(field) === 'number' && value !== '' ? Number(value) : value;
  }

  function initialGraphForField(name: string, field: AnySchemaObject): NodeGraph {
    return (inputs[name] ?? field.default) as NodeGraph;
  }

  function nodeGraphCatalog(): GraphNodeCatalog {
    if (!descriptor.graph_catalog) {
      throw new Error('Node graph widget requires graph catalog metadata.');
    }
    return descriptor.graph_catalog;
  }

  async function submit(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    errors = validationMessages(validator, inputs);
    if (errors.length === 0) await onsubmit(inputs);
  }
</script>

<div class="selection-notes" aria-label="Selection behavior">
  <p>{selectionExplanation('Market', descriptor.market_selection)}</p>
  <p>{selectionExplanation('Wallet', descriptor.wallet_selection)}</p>
</div>

<form class="launch-form" onsubmit={submit} novalidate aria-busy={busy}>
  <div class="form-grid">
    {#each fields as [name, field] (name)}
      {@const schema = resolvedFieldSchema(descriptor, field)}
      {@const widget = widgetKind(field)}
      {@const labelId = `field-${name}-label`}
      {@const helperId = `field-${name}-helper`}
      <svelte:element
        this={widget === WIDGET_KIND.nodeGraph ? 'div' : 'label'}
        class:wide={widget === WIDGET_KIND.streamRules || widget === WIDGET_KIND.nodeGraph}
        class:checkbox-field={schema.type === 'boolean'}
      >
        <span class="field-label" id={labelId}>{fieldLabel(name, schema)}</span>
        {#if typeof schema.description === 'string'}
          <span class="field-helper" id={helperId}>{schema.description}</span>
        {/if}

        {#if widget === WIDGET_KIND.nodeGraph}
          <!-- Reset canvas-owned state when the selected definition changes. -->
          {#key descriptor.definition_id}
            <NodeGraphInput
              initialGraph={initialGraphForField(name, schema)}
              graphCatalog={nodeGraphCatalog()}
              onchange={(graph) => update(name, graph)}
              labelledby={labelId}
              describedby={typeof schema.description === 'string' ? helperId : undefined}
            />
          {/key}
        {:else if widget === WIDGET_KIND.walletAddresses || widget === WIDGET_KIND.marketSlugs}
          <textarea
            rows="3"
            value={Array.isArray(inputs[name]) ? inputs[name].join('\n') : ''}
            oninput={(event) => updateList(name, event.currentTarget.value)}
            placeholder={widget === WIDGET_KIND.walletAddresses ? 'One wallet address per line' : 'One market slug per line'}
            aria-labelledby={labelId}
            aria-describedby={typeof schema.description === 'string' ? helperId : undefined}
          ></textarea>
        {:else if widget === WIDGET_KIND.streamRules}
          <textarea
            rows="6"
            value={JSON.stringify(inputs[name], null, 2)}
            oninput={(event) => updateJson(name, event.currentTarget.value)}
            spellcheck="false"
            aria-labelledby={labelId}
            aria-describedby={typeof schema.description === 'string' ? helperId : undefined}
          ></textarea>
        {:else if schema.type === 'boolean'}
          <input
            type="checkbox"
            checked={inputs[name] === true}
            onchange={(event) => update(name, event.currentTarget.checked)}
            aria-labelledby={labelId}
            aria-describedby={typeof schema.description === 'string' ? helperId : undefined}
          />
        {:else}
          <input
            type={widget === WIDGET_KIND.decimal ? 'text' : inputType(field)}
            inputmode={widget === WIDGET_KIND.decimal ? 'decimal' : undefined}
            value={String(inputs[name] ?? '')}
            required={Array.isArray(descriptor.input_schema.required) && descriptor.input_schema.required.includes(name)}
            min={typeof schema.minimum === 'number' ? schema.minimum : undefined}
            max={typeof schema.maximum === 'number' ? schema.maximum : undefined}
            step={inputType(field) === 'number' ? '1' : undefined}
            aria-labelledby={labelId}
            aria-describedby={typeof schema.description === 'string' ? helperId : undefined}
            oninput={(event) =>
              update(name, parseFieldInput(field, event.currentTarget.value))}
          />
        {/if}
      </svelte:element>
    {/each}
  </div>

  {#if errors.length > 0}
    <div class="form-errors" role="alert">
      {#each errors as error}
        <p>{error}</p>
      {/each}
    </div>
  {/if}

  <button type="submit" disabled={busy} aria-busy={busy}>{busy ? 'Starting…' : 'Start paper run'}</button>
</form>
