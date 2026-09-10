<script lang="ts">
  import type { BotDefinitionDescriptor, PaperRunConfig } from "$lib/api/generated";
  import { BOT_BUILDER_COPY } from "$lib/bots/copy";
  import RunSection from "./RunSection.svelte";
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

<RunSection
  title={BOT_BUILDER_COPY.CONFIGURATION}
  headingId="run-configuration-heading"
  description="Settings captured when this run was created. Later bot edits do not change them."
  annotation="Read only"
>
  <dl class="form-grid">
    {#each fields as [name, field] (name)}
      {@const schema = descriptor ? resolvedFieldSchema(descriptor, field) : field}
      <div class="form-field" class:wide={isWideLaunchField(field) || name === "stream_rules"}>
        <dt class="field-label">{fieldLabel(name, schema)}</dt>
        <dd class="configuration-value"><ConfigurationValue value={values[name as keyof typeof values]} /></dd>
      </div>
    {/each}
  </dl>
</RunSection>

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
