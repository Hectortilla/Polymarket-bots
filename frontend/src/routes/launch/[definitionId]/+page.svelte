<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { onMount } from 'svelte';

  import {
    createBotApiV1BotsPost,
    listBotDefinitionsApiV1BotDefinitionsGet,
    listGraphTemplatesApiV1GraphTemplatesGet,
    type BotDefinitionDescriptor,
    type GraphTemplateRead
  } from '$lib/api/generated';
  import LaunchForm from '$lib/catalog/LaunchForm.svelte';
  import {
    type LaunchInputs
  } from '$lib/catalog/schema';
  import { hasGraphCapability } from '$lib/catalog/graphContracts';
  import {
    NAVIGATION_LABEL,
    NAVIGATION_PATH,
    botPath
  } from '$lib/navigation';
  import { BOT_CREATION_COPY } from './copy';

  let descriptor = $state<BotDefinitionDescriptor | undefined>();
  let loading = $state(true);
  let templates = $state<GraphTemplateRead[]>([]);
  let selectedTemplateId = $state('');
  let busy = $state(false);
  let error = $state('');

  onMount(() => {
    void loadCreationOptions();
  });

  async function loadCreationOptions(): Promise<void> {
    try {
      const [definitionsResponse, templatesResponse] = await Promise.all([
        listBotDefinitionsApiV1BotDefinitionsGet({ throwOnError: true }),
        listGraphTemplatesApiV1GraphTemplatesGet({ throwOnError: true })
      ]);
      descriptor = definitionsResponse.data.find(
        (definition) => definition.definition_id === page.params.definitionId
      );
      templates = templatesResponse.data;
      selectedTemplateId = templates[0]?.id ?? '';
      if (!descriptor) error = BOT_CREATION_COPY.DEFINITION_NOT_FOUND;
    } catch {
      error = BOT_CREATION_COPY.CATALOG_LOAD_ERROR;
    } finally {
      loading = false;
    }
  }

  async function createSavedBot(inputs: LaunchInputs): Promise<void> {
    if (!descriptor) return;
    busy = true;
    error = '';
    try {
      const response = await createBotApiV1BotsPost({
        body: {
          definition_id: descriptor.definition_id,
          inputs,
          ...(hasGraphCapability(descriptor)
            ? { graph_template_id: selectedTemplateId }
            : {})
        },
        throwOnError: true
      });
      await goto(botPath(response.data.id));
    } catch {
      error = BOT_CREATION_COPY.SAVE_ERROR;
    } finally {
      busy = false;
    }
  }
</script>

<svelte:head>
  <title>{descriptor ? `${descriptor.display_name} | Polybot` : 'Create bot | Polybot'}</title>
</svelte:head>

<a class="back-link" href={NAVIGATION_PATH.HOME}>{NAVIGATION_LABEL.BACK_TO_CATALOG}</a>

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
  <section
    class="launch-page"
    class:graph-launch={hasGraphCapability(descriptor)}
  >
    <header class="launch-intro">
      <p class="route-meta">Saved bot / {descriptor.label.replace('_', ' ')}</p>
      <h1>{descriptor.display_name}</h1>
      <p>{descriptor.description}</p>
    </header>

    <div class="launch-controls">
      {#if error}
        <p class="notice error" role="alert">{error}</p>
      {/if}

      {#if hasGraphCapability(descriptor)}
        <label class="template-selector">
          <span class="field-label">Graph template</span>
          <span class="field-helper">The selected graph becomes the first immutable revision. Later template edits do not affect this bot.</span>
          <select bind:value={selectedTemplateId} required>
            {#each templates as template (template.id)}
              <option value={template.id}>{template.name}</option>
            {/each}
          </select>
        </label>
        {#if templates.length === 0}
          <p class="notice">{BOT_CREATION_COPY.TEMPLATE_REQUIRED} <a href={NAVIGATION_PATH.GRAPH_TEMPLATES}>{BOT_CREATION_COPY.OPEN_GRAPH_TEMPLATES}</a>.</p>
        {/if}
      {/if}

      <LaunchForm
        {descriptor}
        onsubmit={createSavedBot}
        {busy}
        disabled={hasGraphCapability(descriptor) && !selectedTemplateId}
      />
    </div>
  </section>
{/if}
