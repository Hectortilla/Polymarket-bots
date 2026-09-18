<script lang="ts">
  import type { Snippet } from "svelte";
  import { page } from "$app/state";
  import {
    PUBLIC_INFORMATION_LABEL,
    PUBLIC_INFORMATION_PATH,
    PUBLIC_PRELOAD_DATA_POLICY,
    PUBLIC_INFORMATION_NAV_LABEL,
  } from "./navigation";
  import { SERVICE_IDENTITY } from "./identity";
  let { title, intro, children }: { title: string; intro: string; children: Snippet } = $props();
</script>

<svelte:head><title>{title} | {SERVICE_IDENTITY.name}</title><meta name="description" content={intro} /></svelte:head>
<!-- Information links must not fetch account/private data on hover. -->
<div class="public-layout" data-sveltekit-preload-data={PUBLIC_PRELOAD_DATA_POLICY}>
  <nav aria-label={PUBLIC_INFORMATION_NAV_LABEL}>
    {#each Object.values(PUBLIC_INFORMATION_PATH) as path}
      <a href={path} aria-current={decodeURI(page.url.pathname) === path ? "page" : undefined}>
        {PUBLIC_INFORMATION_LABEL[path]}
      </a>
    {/each}
  </nav>
  <article class="public-page">
    <header>
      <h1>{title}</h1>
      <p class="intro">{intro}</p>
    </header>
    <div class="public-content">{@render children()}</div>
  </article>
</div>

<style>
  .public-layout {
    display: grid;
    grid-template-columns: 168px minmax(0, 720px);
    gap: 48px;
    max-width: 1000px;
    margin: 8px auto 0;
  }
  .public-page {
    min-width: 0;
  }
  header {
    padding-bottom: 24px;
    border-bottom: 1px solid var(--line);
  }
  h1 {
    max-width: 32ch;
    margin: 0 0 10px;
    font-size: clamp(1.5rem, 2.4vw, 1.75rem);
    line-height: 1.2;
    letter-spacing: -0.035em;
  }
  .intro {
    margin: 0;
    font-size: 0.875rem;
    max-width: 65ch;
    color: var(--text-soft);
  }
  .public-content {
    padding-top: 24px;
    font-size: 0.875rem;
  }
  .public-content :global(section) {
    margin: 0 0 24px;
  }
  .public-content :global(section + section) {
    padding-top: 24px;
    border-top: 1px solid var(--line);
  }
  .public-page :global(p),
  .public-page :global(li) {
    line-height: 1.65;
    max-width: 65ch;
    overflow-wrap: anywhere;
    color: var(--text-soft);
  }
  .public-content :global(p) {
    margin-bottom: 12px;
  }
  .public-content :global(section > :last-child) {
    margin-bottom: 0;
  }
  .public-content :global(ol) {
    padding-left: 20px;
    margin: 0;
  }
  .public-content :global(li) {
    padding-left: 6px;
    margin-bottom: 14px;
  }
  .public-content :global(li::marker) {
    font-family: var(--font-mono);
    color: var(--text-muted);
    font-size: 0.75rem;
  }
  .public-page :global(h2) {
    font-size: 0.9375rem;
    margin-bottom: 10px;
    letter-spacing: -0.015em;
  }
  .public-page :global(a) {
    text-underline-offset: 0.2em;
    text-decoration-color: var(--control-line);
  }
  .public-page :global(a:hover) {
    color: var(--text);
    text-decoration-color: currentColor;
  }
  nav {
    display: grid;
    align-content: start;
    gap: 4px;
    position: sticky;
    top: 96px;
    align-self: start;
  }
  nav a {
    display: flex;
    align-items: center;
    min-height: 44px;
    padding: 0 14px;
    border-radius: var(--radius-control);
    color: var(--text-muted);
    font-size: 0.8125rem;
    text-decoration: none;
  }
  nav a:hover {
    background: var(--surface);
    color: var(--text);
  }
  nav a[aria-current="page"] {
    color: var(--text);
    background: var(--surface-raised);
    font-weight: 600;
    box-shadow: inset 2px 0 var(--accent);
  }
  @media (max-width: 767px) {
    .public-layout {
      grid-template-columns: minmax(0, 1fr);
      gap: 24px;
      margin-top: 0;
    }
    nav {
      position: static;
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
      border-bottom: 1px solid var(--line);
      padding-bottom: 12px;
    }
    nav a {
      padding-inline: 12px;
    }
    nav a[aria-current="page"] {
      box-shadow: inset 0 -2px var(--accent);
    }
  }
</style>
