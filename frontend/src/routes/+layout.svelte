<script lang="ts">
  import '../app.css';

  let { children } = $props();
</script>

<svelte:head>
  <title>Polybot control plane</title>
  <meta
    name="description"
    content="Private launch and run interface for Polybot paper trading."
  />
</svelte:head>

<header class="site-header">
  <a class="brand" href="/">Polybot</a>
  <span>Paper control plane</span>
</header>

<main>{@render children()}</main>
