<script lang="ts">
  import "$lib/bots/builder.css";
  import type { AnySchemaObject } from "ajv";
  import { tick, type Snippet } from "svelte";

  import type { BotDefinitionDescriptor } from "$lib/api/generated";
  import { LAUNCH_FORM_COPY } from "./copy";
  import WalletSelector from "./WalletSelector.svelte";
  import MarketSelector from "./MarketSelector.svelte";
  import { WIDGET_KIND, type LaunchInputs, type LaunchValidationIssue } from "$lib/catalog/schema/contracts";
  import { fieldLabel, isWideLaunchField, selectionExplanation } from "$lib/catalog/schema/presentation";
  import { initialLaunchInputs } from "$lib/catalog/schema/inputs";
  import { launchFields, resolvedFieldSchema, widgetKind } from "$lib/catalog/schema/fields";
  import { launchValidationIssues, launchValidator, visibleLaunchIssues } from "$lib/catalog/schema/validation";

  let {
    descriptor,
    onsubmit,
    busy = false,
    disabled = false,
    initialInputs,
    submitLabel = LAUNCH_FORM_COPY.SAVE_BOT,
    busyLabel = LAUNCH_FORM_COPY.SAVING,
    onchange,
    serverIssues = [],
    showSelectionNotes = true,
    sectionTitle,
    sectionDescription,
    children,
  }: {
    descriptor: BotDefinitionDescriptor;
    onsubmit: (inputs: LaunchInputs) => void | Promise<void>;
    busy?: boolean;
    disabled?: boolean;
    initialInputs?: LaunchInputs;
    submitLabel?: string;
    busyLabel?: string;
    onchange?: (inputs: LaunchInputs) => void;
    serverIssues?: LaunchValidationIssue[];
    showSelectionNotes?: boolean;
    sectionTitle?: string;
    sectionDescription?: string;
    children?: Snippet;
  } = $props();

  const fields = $derived(launchFields(descriptor));
  const validator = $derived(launchValidator(descriptor));
  let inputs = $state<LaunchInputs>({});
  let activeInputsKey = $state("");
  let localIssues = $state<LaunchValidationIssue[]>([]);
  let touchedFields = $state<Set<string>>(new Set());
  let submitted = $state(false);
  let formElement: HTMLFormElement;
  const visibleIssues = $derived(visibleLaunchIssues(localIssues, serverIssues, touchedFields, submitted));
  const formIssues = $derived(visibleIssues.filter((issue) => issue.field === undefined));

  $effect(() => {
    // Compare serialized values so parent object identity changes do not erase edits.
    const nextInputs = initialInputs ?? initialLaunchInputs(descriptor);
    const nextKey = `${descriptor.definition_id}:${JSON.stringify(nextInputs)}`;
    if (activeInputsKey !== nextKey) {
      activeInputsKey = nextKey;
      inputs = nextInputs;
      localIssues = [];
      touchedFields = new Set();
      submitted = false;
      onchange?.(inputs);
    }
  });

  async function submit(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    submitted = true;
    localIssues = launchValidationIssues(validator, inputs);
    if (localIssues.length === 0) {
      await onsubmit(inputs);
      return;
    }
    await tick();
    formElement.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
  }

  function update(name: string, value: unknown): void {
    inputs = { ...inputs, [name]: value };
    touchedFields = new Set([...touchedFields, name]);
    localIssues = launchValidationIssues(validator, inputs);
    onchange?.(inputs);
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
    return type === "integer" || type === "number" ? "number" : "text";
  }

  function parseFieldInput(field: AnySchemaObject, value: string): string | number {
    return inputType(field) === "number" && value !== "" ? Number(value) : value;
  }

  function issuesForField(name: string): LaunchValidationIssue[] {
    return visibleIssues.filter((issue) => issue.field === name);
  }

  function fieldDescription(
    helperId: string,
    hasHelper: boolean,
    errorId: string,
    hasError: boolean,
  ): string | undefined {
    const descriptions = [hasHelper ? helperId : undefined, hasError ? errorId : undefined].filter(Boolean).join(" ");
    return descriptions || undefined;
  }
</script>

{#if showSelectionNotes}
  <div class="selection-notes" aria-label="Selection behavior">
    <p>{selectionExplanation("Market", descriptor.market_selection)}</p>
    <p>{selectionExplanation("Wallet", descriptor.wallet_selection)}</p>
  </div>
{/if}

<form bind:this={formElement} class="launch-form" onsubmit={submit} novalidate aria-busy={busy}>
  <section class="builder-section configuration-section">
    {#if sectionTitle}
      <header class="builder-section-heading">
        <div>
          <h2>{sectionTitle}</h2>
          {#if sectionDescription}<p>{sectionDescription}</p>{/if}
        </div>
      </header>
    {/if}
    <div class="form-grid">
      {#each fields as [name, field] (name)}
        {@const schema = resolvedFieldSchema(descriptor, field)}
        {@const widget = widgetKind(field)}
        {@const labelId = `field-${name}-label`}
        {@const helperId = `field-${name}-helper`}
        {@const errorId = `field-${name}-error`}
        {@const fieldIssues = issuesForField(name)}
        {@const hasHelper = typeof schema.description === "string"}
        <div class="form-field" class:wide={isWideLaunchField(field)} class:checkbox-field={schema.type === "boolean"}>
          <label class="field-label" id={labelId} for={`${labelId}-input`}>{fieldLabel(name, schema)}</label>
          {#if typeof schema.description === "string"}
            <span class="field-helper" id={helperId}>{schema.description}</span>
          {/if}

          {#if widget === WIDGET_KIND.MARKET_SLUGS}
            <MarketSelector
              value={Array.isArray(inputs[name])
                ? inputs[name].filter((value: unknown): value is string => typeof value === "string")
                : []}
              onchange={(slugs) => update(name, slugs)}
              {labelId}
              descriptionId={fieldDescription(helperId, hasHelper, errorId, fieldIssues.length > 0)}
              invalid={fieldIssues.length > 0}
              disabled={busy}
            />
          {:else if widget === WIDGET_KIND.WALLET_ADDRESSES}
            <WalletSelector
              value={Array.isArray(inputs[name])
                ? inputs[name].filter((value: unknown): value is string => typeof value === "string")
                : []}
              onchange={(addresses) => update(name, addresses)}
              {labelId}
              descriptionId={fieldDescription(helperId, hasHelper, errorId, fieldIssues.length > 0)}
              invalid={fieldIssues.length > 0}
              disabled={busy}
            />
          {:else if widget === WIDGET_KIND.STREAM_RULES}
            <textarea
              id={`${labelId}-input`}
              rows="6"
              value={JSON.stringify(inputs[name], null, 2)}
              oninput={(event) => updateJson(name, event.currentTarget.value)}
              spellcheck="false"
              aria-labelledby={labelId}
              aria-describedby={fieldDescription(helperId, hasHelper, errorId, fieldIssues.length > 0)}
              aria-invalid={fieldIssues.length > 0}></textarea>
          {:else if schema.type === "boolean"}
            <input
              id={`${labelId}-input`}
              type="checkbox"
              checked={inputs[name] === true}
              onchange={(event) => update(name, event.currentTarget.checked)}
              aria-labelledby={labelId}
              aria-describedby={fieldDescription(helperId, hasHelper, errorId, fieldIssues.length > 0)}
              aria-invalid={fieldIssues.length > 0}
            />
          {:else}
            <input
              id={`${labelId}-input`}
              type={widget === WIDGET_KIND.DECIMAL ? "text" : inputType(field)}
              inputmode={widget === WIDGET_KIND.DECIMAL ? "decimal" : undefined}
              value={String(inputs[name] ?? "")}
              required={Array.isArray(descriptor.input_schema.required) &&
                descriptor.input_schema.required.includes(name)}
              min={typeof schema.minimum === "number" ? schema.minimum : undefined}
              max={typeof schema.maximum === "number" ? schema.maximum : undefined}
              step={inputType(field) === "number" ? "1" : undefined}
              aria-labelledby={labelId}
              aria-describedby={fieldDescription(helperId, hasHelper, errorId, fieldIssues.length > 0)}
              aria-invalid={fieldIssues.length > 0}
              oninput={(event) => update(name, parseFieldInput(field, event.currentTarget.value))}
            />
          {/if}
          {#if fieldIssues.length > 0}
            <span class="field-errors" id={errorId} aria-live="polite">
              {#each fieldIssues as issue (issue.message)}
                <span>{issue.message}</span>
              {/each}
            </span>
          {/if}
        </div>
      {/each}
    </div>
  </section>

  {#if children}{@render children()}{/if}

  {#if formIssues.length > 0}
    <div class="form-errors" role="alert">
      {#each formIssues as issue (issue.message)}
        <p>{issue.message}</p>
      {/each}
    </div>
  {/if}

  <footer class="builder-actions">
    <button type="submit" disabled={busy || disabled} aria-busy={busy}>{busy ? busyLabel : submitLabel}</button>
  </footer>
</form>
