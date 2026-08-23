<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { onMount } from 'svelte';

  import {
    launchRunApiV1RunsPost,
    listBotDefinitionsApiV1BotDefinitionsGet,
    type BotDefinitionDescriptor
  } from '$lib/api/generated';
  import LaunchForm from '$lib/catalog/LaunchForm.svelte';
  import type { LaunchInputs } from '$lib/catalog/schema';

  let descriptor = $state<BotDefinitionDescriptor | undefined>();
  let loading = $state(true);
  let busy = $state(false);
  let error = $state('');

  onMount(() => {
    void loadDefinition();
  });

  async function loadDefinition(): Promise<void> {
    try {
      const response = await listBotDefinitionsApiV1BotDefinitionsGet({ throwOnError: true });
      descriptor = response.data.find(
        (definition) => definition.definition_id === page.params.definitionId
      );
      if (!descriptor) error = 'Bot definition not found.';
    } catch {
      error = 'The bot catalog could not be loaded.';
    } finally {
      loading = false;
    }
  }

  async function launch(inputs: LaunchInputs): Promise<void> {
    if (!descriptor) return;
    busy = true;
    error = '';
    try {
      const response = await launchRunApiV1RunsPost({
        body: {
          definition_id: descriptor.definition_id,
          definition_version: descriptor.version,
          inputs
        },
        throwOnError: true
      });
      await goto(`/runs/${response.data.id}`);
    } catch {
      error = 'The run could not be started. Reload the catalog and try again.';
    } finally {
      busy = false;
    }
  }
</script>

<svelte:head>
  <title>{descriptor ? `${descriptor.display_name} | Polybot` : 'Configure run | Polybot'}</title>
</svelte:head>

<a class="back-link" href="/">Back to catalog</a>

{#if loading}
  <div class="loading-state" aria-live="polite">
    <span class="sr-only">Loading definition</span>
    <div class="skeleton skeleton-heading" aria-hidden="true"></div>
    <div class="skeleton skeleton-line" aria-hidden="true"></div>
    <div class="skeleton skeleton-panel" aria-hidden="true"></div>
  </div>
{:else if !descriptor}
  <p class="notice error" role="alert">{error}</p>
{:else}
  <section class="launch-page">
    <header class="launch-intro">
      <p class="route-meta">Paper run / {descriptor.label.replace('_', ' ')}</p>
      <h1>{descriptor.display_name}</h1>
      <p>{descriptor.description}</p>
    </header>

    <div class="launch-controls">
      {#if error}
        <p class="notice error" role="alert">{error}</p>
      {/if}

      <LaunchForm {descriptor} onsubmit={launch} {busy} />
    </div>
  </section>
{/if}
