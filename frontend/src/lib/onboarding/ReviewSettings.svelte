<script lang="ts">
  import { LaunchFormSchema } from "$lib/catalog/schema";

  import type { BotDefinitionDescriptor, GraphExample } from "$lib/api/generated";
  import { fieldLabel } from "$lib/catalog/schema/presentation";

  import { type LaunchInputs } from "$lib/catalog/schema/contracts";
  import { ONBOARDING_COPY } from "./copy";
  let {
    descriptor,
    example,
    inputs,
  }: { descriptor: BotDefinitionDescriptor; example: GraphExample; inputs: LaunchInputs } = $props();
  const launchSchema = $derived(new LaunchFormSchema(descriptor));
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
  {#each launchSchema.fields() as [name, schema] (name)}
    <div>
      <dt>{fieldLabel(name, launchSchema.resolveFieldSchema(schema))}</dt>
      <dd>{Array.isArray(inputs[name]) ? inputs[name].join(", ") : String(inputs[name] ?? "")}</dd>
    </div>
  {/each}
</dl>
<p>{ONBOARDING_COPY.NO_LAUNCH}</p>

<style>
  dl {
    display: grid;
    gap: 0;
    margin: 12px 0 24px;
    border: 1px solid var(--line);
    border-radius: var(--radius-control);
    background: var(--surface);
  }
  dl div {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 1rem;
    padding: 12px 16px;
  }
  dl div + div {
    border-top: 1px solid var(--line);
  }
  dt {
    color: var(--text-muted);
  }
  dd {
    font-family: var(--font-mono);
    font-size: 0.8125rem;
  }
  dt,
  dd {
    margin: 0;
    overflow-wrap: anywhere;
  }
  @media (max-width: 767px) {
    dl div {
      grid-template-columns: 1fr;
      gap: 0.2rem;
    }
  }
</style>
