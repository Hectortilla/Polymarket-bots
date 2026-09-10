<script lang="ts">
  import type { Snippet } from "svelte";
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
<article class="public-page" data-sveltekit-preload-data={PUBLIC_PRELOAD_DATA_POLICY}>
  <header>
    <p class="page-kicker">Paper trading preview</p>
    <h1>{title}</h1>
    <p class="intro">{intro}</p>
  </header>
  {@render children()}
  <footer>
    <nav aria-label={PUBLIC_INFORMATION_NAV_LABEL}>
      {#each Object.values(PUBLIC_INFORMATION_PATH) as path}<a href={path}>{PUBLIC_INFORMATION_LABEL[path]}</a>{/each}
    </nav>
  </footer>
</article>

<style>
  .public-page {
    max-width: 850px;
    margin-inline: auto;
    padding-block: 1rem;
  }
  header {
    margin-bottom: 3rem;
  }
  h1 {
    max-width: 20ch;
    font-size: clamp(2rem, 6vw, 3.8rem);
    line-height: 1.08;
    letter-spacing: -0.04em;
  }
  .intro {
    font-size: 1.15rem;
    max-width: 62ch;
    color: var(--text-muted);
  }
  .public-page :global(section) {
    margin-block: 2.5rem;
  }
  .public-page :global(p),
  .public-page :global(li) {
    line-height: 1.7;
    max-width: 72ch;
    overflow-wrap: anywhere;
  }
  .public-page :global(h2) {
    font-size: 1.4rem;
    margin-bottom: 12px;
  }
  .public-page :global(a) {
    text-underline-offset: 0.2em;
  }
  footer {
    margin-top: 3rem;
    padding-top: 1.5rem;
    border-top: 1px solid var(--line);
  }
  nav {
    display: flex;
    flex-wrap: wrap;
    gap: 1rem 1.5rem;
  }
</style>
