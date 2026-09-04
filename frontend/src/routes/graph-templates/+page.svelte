<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';

  import { NAVIGATION_PATH } from '$lib/navigation';

  onMount(() => {
    void goto(NAVIGATION_PATH.NEW_BOT, { replaceState: true });
  });
</script>

<svelte:head><title>New bot | Polybot</title></svelte:head>

<p class="empty-state" aria-live="polite">Opening the bot builder...</p>
