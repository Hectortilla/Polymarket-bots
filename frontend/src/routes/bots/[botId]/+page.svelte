<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { onMount, tick } from 'svelte';

  import {
    createBotGraphRevisionApiV1BotsBotIdGraphRevisionsPost,
    launchBotRunApiV1BotsBotIdRunsPost,
    listBotDefinitionsApiV1BotDefinitionsGet,
    readBotApiV1BotsBotIdGet,
    updateBotApiV1BotsBotIdPatch,
    type BotDefinitionDescriptor,
    type BotRead,
    type NodeGraph
  } from '$lib/api/generated';
  import LaunchForm from '$lib/catalog/LaunchForm.svelte';
  import NodeGraphInput from '$lib/catalog/NodeGraphInput.svelte';
  import { nodeGraphsEqual } from '$lib/catalog/nodeGraphEquality';
  import {
    graphValidationIssues,
    type GraphValidationIssue
  } from '$lib/catalog/graphValidation';
  import {
    launchInputsFromConfig,
    launchRequestValidationIssues,
    type LaunchInputs,
    type LaunchValidationIssue
  } from '$lib/catalog/schema';
  import { hasGraphCapability } from '$lib/catalog/graphContracts';
  import { formatTime } from '$lib/time';
  import { FORM_COPY } from '$lib/formCopy';
  import { NAVIGATION_LABEL, NAVIGATION_PATH, runPath } from '$lib/navigation';
  import { BOT_DETAIL_COPY, botGraphRevisionLabel } from './copy';

  let bot = $state<BotRead>();
  let descriptor = $state<BotDefinitionDescriptor>();
  let savedInputs = $state<LaunchInputs>({});
  let editedInputs = $state<LaunchInputs>({});
  let savedGraph = $state<NodeGraph>();
  let editedGraph = $state<NodeGraph>();
  let graphEditorResetKey = $state('');
  let loading = $state(true);
  let savingConfig = $state(false);
  let savingGraph = $state(false);
  let running = $state(false);
  let error = $state('');
  let configServerIssues = $state<LaunchValidationIssue[]>([]);
  let graphServerIssues = $state<GraphValidationIssue[]>([]);

  const configDirty = $derived(JSON.stringify(savedInputs) !== JSON.stringify(editedInputs));
  const graphDirty = $derived(!nodeGraphsEqual(savedGraph, editedGraph));
  const hasUnsavedChanges = $derived(configDirty || graphDirty);

  onMount(() => {
    void loadSavedBotEditor();
  });

  async function loadSavedBotEditor(): Promise<void> {
    const botId = page.params.botId;
    if (!botId) {
      error = BOT_DETAIL_COPY.NOT_FOUND;
      loading = false;
      return;
    }
    try {
      const [botResponse, definitionsResponse] = await Promise.all([
        readBotApiV1BotsBotIdGet({ path: { bot_id: botId }, throwOnError: true }),
        listBotDefinitionsApiV1BotDefinitionsGet({ throwOnError: true })
      ]);
      bot = botResponse.data;
      descriptor = definitionsResponse.data.find(
        (definition) => definition.definition_id === bot?.definition_id
      );
      if (!descriptor) throw new Error('definition missing');
      savedInputs = launchInputsFromConfig(descriptor, bot.config);
      editedInputs = savedInputs;
      savedGraph = bot.latest_graph_revision?.graph;
      editedGraph = savedGraph;
      graphEditorResetKey = bot.latest_graph_revision?.id ?? '';
    } catch {
      error = BOT_DETAIL_COPY.LOAD_ERROR;
    } finally {
      loading = false;
    }
  }

  async function saveConfig(inputs: LaunchInputs): Promise<void> {
    if (!bot) return;
    savingConfig = true;
    error = '';
    configServerIssues = [];
    try {
      const response = await updateBotApiV1BotsBotIdPatch({
        path: { bot_id: bot.id },
        body: { inputs },
        throwOnError: true
      });
      bot = response.data;
      savedInputs = inputs;
      editedInputs = inputs;
    } catch (caught) {
      configServerIssues = launchRequestValidationIssues(caught);
      if (configServerIssues.length === 0) {
        error = BOT_DETAIL_COPY.CONFIG_SAVE_ERROR;
      }
    } finally {
      savingConfig = false;
    }
  }

  async function saveGraph(): Promise<void> {
    if (!bot || !editedGraph) return;
    const graphToSave = editedGraph;
    savingGraph = true;
    error = '';
    graphServerIssues = [];
    try {
      const response = await createBotGraphRevisionApiV1BotsBotIdGraphRevisionsPost({
        path: { bot_id: bot.id },
        body: { graph: graphToSave },
        throwOnError: true
      });
      bot = response.data;
      savedGraph = response.data.latest_graph_revision?.graph;
      editedGraph = savedGraph;
      graphEditorResetKey = response.data.latest_graph_revision?.id ?? '';
    } catch (caught) {
      graphServerIssues = graphValidationIssues(caught, graphToSave);
      if (graphServerIssues.length > 0) {
        await tick();
        document.getElementById('bot-graph-validation')?.focus();
      } else {
        error = BOT_DETAIL_COPY.GRAPH_SAVE_ERROR;
      }
    } finally {
      savingGraph = false;
    }
  }

  async function runBot(): Promise<void> {
    if (!bot || hasUnsavedChanges) return;
    running = true;
    error = '';
    try {
      const response = await launchBotRunApiV1BotsBotIdRunsPost({
        path: { bot_id: bot.id },
        throwOnError: true
      });
      await goto(runPath(response.data.id));
    } catch {
      error = BOT_DETAIL_COPY.RUN_ERROR;
    } finally {
      running = false;
    }
  }
</script>

<svelte:head><title>{bot ? `${bot.config.name} | Polybot` : 'Saved bot | Polybot'}</title></svelte:head>

<a class="back-link" href={NAVIGATION_PATH.HOME}>{NAVIGATION_LABEL.BACK_TO_OPERATIONS}</a>

{#if loading}
  <p class="empty-state">Loading saved bot…</p>
{:else if !bot || !descriptor}
  <p class="notice error" role="alert">{error}</p>
{:else}
  <section class="page-heading run-heading">
    <div>
      <p class="route-meta">{descriptor.display_name} / saved {formatTime(bot.updated_at)}</p>
      <h1>{bot.config.name}</h1>
      <p>Runs copy the latest saved settings and graph revision. Unsaved changes are never executed.</p>
    </div>
    <button onclick={runBot} disabled={running || hasUnsavedChanges} aria-busy={running}>
      {running ? BOT_DETAIL_COPY.STARTING : BOT_DETAIL_COPY.RUN}
    </button>
  </section>

  {#if error}<p class="notice error" role="alert">{error}</p>{/if}
  {#if hasUnsavedChanges}
    <p class="notice">{BOT_DETAIL_COPY.UNSAVED_RUN_BLOCK}</p>
  {/if}

  <section class="bot-editor-section">
    <div class="section-heading">
      <h2>Bot configuration</h2>
      <span class="section-count">{configDirty ? BOT_DETAIL_COPY.UNSAVED : BOT_DETAIL_COPY.SAVED}</span>
    </div>
    <LaunchForm
      {descriptor}
      initialInputs={savedInputs}
      onsubmit={saveConfig}
      onchange={(inputs) => {
        editedInputs = inputs;
        configServerIssues = [];
      }}
      busy={savingConfig}
      submitLabel={BOT_DETAIL_COPY.SAVE_CONFIGURATION}
      busyLabel={FORM_COPY.SAVING}
      serverIssues={configServerIssues}
    />
  </section>

  {#if hasGraphCapability(descriptor) && savedGraph}
    <section class="bot-editor-section">
      <div class="section-heading">
        <div>
          <h2>{botGraphRevisionLabel(bot.latest_graph_revision?.revision)}</h2>
          <p>Saving creates a new immutable revision. The source template and earlier runs stay unchanged.</p>
        </div>
        <span class="section-count">{graphDirty ? BOT_DETAIL_COPY.UNSAVED : BOT_DETAIL_COPY.SAVED}</span>
      </div>
      <!-- Remount canvas-owned state after accepting a new immutable revision. -->
      {#key graphEditorResetKey}
        <NodeGraphInput
          initialGraph={savedGraph}
          graphCatalog={descriptor.graph_catalog}
          onchange={(graph) => {
            editedGraph = graph;
            graphServerIssues = [];
          }}
          labelledby="bot-graph-editor-label"
          validationIssues={graphServerIssues}
          validationSummaryId="bot-graph-validation"
        />
      {/key}
      <span class="sr-only" id="bot-graph-editor-label">Bot graph editor</span>
      <button onclick={saveGraph} disabled={savingGraph || !graphDirty} aria-busy={savingGraph}>
        {savingGraph ? FORM_COPY.SAVING : BOT_DETAIL_COPY.SAVE_GRAPH_REVISION}
      </button>
    </section>
  {/if}
{/if}
