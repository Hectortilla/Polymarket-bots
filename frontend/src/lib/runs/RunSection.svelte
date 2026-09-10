<script lang="ts">
  import { untrack, type Snippet } from "svelte";
  import CaretDownIcon from "phosphor-svelte/lib/CaretDownIcon";

  let {
    title,
    headingId,
    description,
    descriptionId,
    annotation,
    initiallyOpen = true,
    children,
  }: {
    title: string;
    headingId: string;
    description?: string;
    descriptionId?: string;
    annotation?: string;
    initiallyOpen?: boolean;
    children: Snippet;
  } = $props();
  let open = $state(untrack(() => initiallyOpen));
</script>

<section class="run-section" aria-labelledby={headingId}>
  <header class="run-section-header">
    <h2 id={headingId}>
      <button
        class="run-section-toggle"
        aria-expanded={open}
        aria-controls={`${headingId}-content`}
        onclick={() => (open = !open)}
      >
        <CaretDownIcon class={open ? "disclosure-icon expanded" : "disclosure-icon"} size={16} aria-hidden="true" />
        {title}
      </button>
    </h2>
    {#if annotation}<span class="section-count">{annotation}</span>{/if}
  </header>
  <div id={`${headingId}-content`} hidden={!open}>
    {#if open}
      {#if description}<p class="run-section-description" id={descriptionId}>{description}</p>{/if}
      {@render children()}
    {/if}
  </div>
</section>

<style>
  .run-section {
    min-width: 0;
    border-top: 1px solid var(--line);
  }
  .run-section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    min-height: 76px;
  }
  h2 {
    margin: 0;
    font-size: 1.15rem;
  }
  .run-section-toggle {
    display: flex;
    align-items: center;
    gap: 12px;
    min-height: 44px;
    padding: 8px 0;
    border: 0;
    border-radius: var(--radius-control);
    background: transparent;
    color: var(--text);
    font: inherit;
    font-weight: 600;
    text-align: left;
  }
  .run-section-toggle:hover {
    background: transparent;
    color: var(--accent);
  }
  .run-section-toggle:active {
    transform: translateY(1px);
  }
  .run-section-toggle :global(.disclosure-icon) {
    flex: none;
    transform: rotate(-90deg);
    color: var(--text-muted);
  }
  .run-section-toggle :global(.disclosure-icon.expanded) {
    transform: rotate(0);
  }
  .run-section-description {
    margin: 0 0 24px;
    max-width: 65ch;
    color: var(--text-muted);
    font-size: 0.88rem;
    line-height: 1.6;
  }
  .run-section > div:not([hidden]) {
    padding-bottom: 28px;
  }
</style>
