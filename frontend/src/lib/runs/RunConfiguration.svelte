<script lang="ts">
  import type { BotDefinitionDescriptor, PaperRunConfig } from "$lib/api/generated";
  import { BOT_BUILDER_COPY } from "$lib/bots/copy";
  import ConfigurationValue from "$lib/catalog/ConfigurationValue.svelte";
  import {
    fieldLabel,
    isWideLaunchField,
    launchFields,
    launchInputsFromConfig,
    resolvedFieldSchema,
  } from "$lib/catalog/schema";

  let { config, descriptor }: { config: PaperRunConfig; descriptor?: BotDefinitionDescriptor } = $props();
  const fields = $derived(
    descriptor
      ? launchFields(descriptor)
      : Object.keys(config)
          .filter((name) => name !== "graph")
          .map((name) => [name, {}] as const),
  );
  const values = $derived(descriptor ? launchInputsFromConfig(descriptor, config) : config);
</script>

<section class="builder-section configuration-section" aria-labelledby="run-configuration-heading">
  <header class="builder-section-heading">
    <div>
      <h2 id="run-configuration-heading">{BOT_BUILDER_COPY.CONFIGURATION}</h2>
      <p>Settings captured when this run was created. Later bot edits do not change them.</p>
    </div>
    <span class="save-state">Read only</span>
  </header>
  <dl class="form-grid">
    {#each fields as [name, field] (name)}
      {@const schema = descriptor ? resolvedFieldSchema(descriptor, field) : field}
      <div class="form-field" class:wide={isWideLaunchField(field) || name === "stream_rules"}>
        <dt class="field-label">{fieldLabel(name, schema)}</dt>
        <dd class="configuration-value"><ConfigurationValue value={values[name as keyof typeof values]} /></dd>
      </div>
    {/each}
  </dl>
</section>

<style>
  .configuration-value {
    margin: 0;
    min-width: 0;
    padding: 4px 0 8px;
    color: var(--text-soft);
    font-family: "Geist Mono Variable", ui-monospace, monospace;
    font-size: 0.88rem;
    line-height: 1.65;
    overflow-wrap: anywhere;
  }
</style>
