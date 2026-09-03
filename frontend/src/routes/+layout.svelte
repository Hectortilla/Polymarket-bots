<script lang="ts">
  import '@fontsource-variable/geist';
  import '@fontsource-variable/geist-mono';
  import '../app.css';
  import { NAVIGATION_PATH } from '$lib/navigation';
  import { configureApiResponseValidation } from '$lib/api/responseValidation';

  configureApiResponseValidation();

  let { children } = $props();
</script>

<svelte:head>
  <title>Polybot control plane</title>
  <meta
    name="description"
    content="Private launch and run interface for Polybot paper trading."
  />
</svelte:head>

<a class="skip-link" href="#main-content">Skip to content</a>

<header class="site-header">
  <div class="site-header-inner">
    <a class="brand" href={NAVIGATION_PATH.HOME} aria-label="Polybot catalog">
      <span class="brand-mark" aria-hidden="true"></span>
      <span>Polybot</span>
    </a>
    <div class="header-context">
      <span>Private control plane</span>
      <span class="environment-label">paper only</span>
    </div>
  </div>
</header>

<main id="main-content">{@render children()}</main>
