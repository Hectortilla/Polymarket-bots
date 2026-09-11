<script lang="ts">
  import { fieldLabel } from "$lib/catalog/schema/presentation";

  let { value }: { value: unknown } = $props();
</script>

{#snippet display(item: unknown)}
  {#if item === null || item === undefined || item === ""}
    <span class="empty-value">Not set</span>
  {:else if Array.isArray(item)}
    {#if item.length}
      <ul>
        {#each item as entry}<li>{@render display(entry)}</li>{/each}
      </ul>
    {:else}
      <span class="empty-value">None</span>
    {/if}
  {:else if typeof item === "object"}
    <dl>
      {#each Object.entries(item) as [name, entry]}
        <div>
          <dt>{fieldLabel(name, {})}</dt>
          <dd>{@render display(entry)}</dd>
        </div>
      {/each}
    </dl>
  {:else}
    <span>{typeof item === "boolean" ? (item ? "Yes" : "No") : String(item)}</span>
  {/if}
{/snippet}

{@render display(value)}

<style>
  ul,
  dl {
    margin: 0;
    padding: 0;
    display: grid;
    gap: 12px;
  }
  ul {
    list-style: none;
  }
  li,
  dd {
    overflow-wrap: anywhere;
  }
  dt,
  .empty-value {
    color: var(--text-muted);
  }
  dt {
    font-family: "Geist Variable", sans-serif;
    font-size: 0.78rem;
  }
  dd {
    margin: 4px 0 0;
  }
</style>
