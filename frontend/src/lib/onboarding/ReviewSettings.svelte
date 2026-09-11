<script lang="ts">
  import type { BotDefinitionDescriptor, GraphExample } from "$lib/api/generated";
  import { fieldLabel } from "$lib/catalog/schema/presentation";
  import { launchFields, resolvedFieldSchema } from "$lib/catalog/schema/fields";
  import { type LaunchInputs } from "$lib/catalog/schema/contracts";
  import { ONBOARDING_COPY } from "./copy";
  let {
    descriptor,
    example,
    inputs,
  }: { descriptor: BotDefinitionDescriptor; example: GraphExample; inputs: LaunchInputs } = $props();
</script>

<h3>{example.name}</h3>
<p>{example.description}</p>
<h3>{ONBOARDING_COPY.PARAMETERS}</h3>
<dl>
  {#each example.graph.parameters ?? [] as parameter (parameter.id)}
    <div>
      <dt>{parameter.name}</dt>
      <dd>{String(parameter.data.value)}</dd>
    </div>
  {/each}
</dl>
<h3>{ONBOARDING_COPY.SETTINGS}</h3>
<dl>
  {#each launchFields(descriptor) as [name, schema] (name)}
    <div>
      <dt>{fieldLabel(name, resolvedFieldSchema(descriptor, schema))}</dt>
      <dd>{Array.isArray(inputs[name]) ? inputs[name].join(", ") : String(inputs[name] ?? "")}</dd>
    </div>
  {/each}
</dl>
<p>{ONBOARDING_COPY.PAPER_ONLY}</p>
<p>{ONBOARDING_COPY.NO_LAUNCH}</p>

<style>
  dl {
    display: grid;
    gap: 0.75rem;
  }
  dl div {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 1rem;
  }
  dt,
  dd {
    margin: 0;
    overflow-wrap: anywhere;
  }
  @media (max-width: 560px) {
    dl div {
      grid-template-columns: 1fr;
      gap: 0.2rem;
    }
  }
</style>
