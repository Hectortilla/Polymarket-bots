<script lang="ts">
  import type { Snippet } from "svelte";
  import CaretDownIcon from "phosphor-svelte/lib/CaretDownIcon";

  let {
    title,
    headingId,
    count,
    icon,
    children,
  }: {
    title: string;
    headingId: string;
    count: number;
    icon: Snippet;
    children: Snippet;
  } = $props();

  let expanded = $state(true);
</script>

<section class="home-section" aria-labelledby={headingId}>
  <h2 id={headingId}>
    <button
      class="home-section-toggle"
      aria-labelledby={`${headingId}-label`}
      aria-describedby={`${headingId}-count`}
      aria-expanded={expanded}
      aria-controls={`${headingId}-content`}
      onclick={() => (expanded = !expanded)}
    >
      <span class="home-section-icon" aria-hidden="true">{@render icon()}</span>
      <span id={`${headingId}-label`} class="home-section-title">{title}</span>
      <span class="home-section-count" aria-hidden="true">{count}</span>
      <span id={`${headingId}-count`} class="sr-only">{count} {count === 1 ? "item" : "items"}</span>
      <span class="home-section-chevron" class:collapsed={!expanded} aria-hidden="true">
        <CaretDownIcon size={14} />
      </span>
    </button>
  </h2>
  <div id={`${headingId}-content`} class="home-section-content" hidden={!expanded}>
    {@render children()}
  </div>
</section>

<style>
  .home-section {
    min-width: 0;
    border: 1px solid var(--line);
    border-radius: var(--radius-surface);
  }

  .home-section-toggle {
    width: 100%;
    min-height: 64px;
    padding: 16px 20px;
    justify-content: flex-start;
    gap: 12px;
    border: 0;
    border-radius: var(--radius-surface);
    color: var(--text);
    background: var(--surface);
    text-align: left;
  }

  .home-section-toggle:hover {
    background: var(--surface-raised);
  }

  .home-section-toggle:focus-visible {
    outline-offset: -3px;
  }

  .home-section-toggle:active {
    transform: none;
    background: var(--surface-raised);
  }

  .home-section-toggle[aria-expanded="true"] {
    border-bottom-right-radius: 0;
    border-bottom-left-radius: 0;
  }

  .home-section-icon,
  .home-section-chevron {
    display: inline-flex;
    flex: none;
    color: var(--text-soft);
  }

  .home-section-title {
    font-size: 0.94rem;
    font-weight: 610;
    letter-spacing: -0.02em;
    line-height: 1.4;
    white-space: normal;
  }

  .home-section-count {
    min-width: 24px;
    padding: 4px 6px;
    border: 1px solid var(--line-strong);
    border-radius: var(--radius-control);
    color: var(--text-soft);
    font-family: var(--font-mono);
    font-size: 0.68rem;
    font-weight: 500;
    text-align: center;
  }

  .home-section-chevron {
    margin-left: auto;
  }

  .home-section-chevron.collapsed {
    transform: rotate(-90deg);
  }

  .home-section-content {
    border-top: 1px solid var(--line);
  }

  @media (prefers-reduced-motion: no-preference) {
    .home-section-chevron {
      transition: transform var(--transition);
    }
  }

  @media (max-width: 767px) {
    .home-section-toggle {
      min-height: 60px;
      padding: 14px 16px;
      gap: 10px;
    }
  }

</style>
