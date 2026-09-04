<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { onMount, tick } from 'svelte';
  import ArrowLeftIcon from 'phosphor-svelte/lib/ArrowLeftIcon';
  import PlayIcon from 'phosphor-svelte/lib/PlayIcon';

  import {
    createBotGraphRevisionApiV1BotsBotIdGraphRevisionsPost,
    launchBotRunApiV1BotsBotIdRunsPost,
    listBotDefinitionsApiV1BotDefinitionsGet,
    listBotsApiV1BotsGet,
    readBotApiV1BotsBotIdGet,
    updateBotApiV1BotsBotIdPatch,
    type BotDefinitionDescriptor,
    type BotRead,
    type NodeGraph
  } from '$lib/api/generated';
  import GraphSourcePicker from '$lib/bots/GraphSourcePicker.svelte';
  import { GRAPH_SOURCE_COPY } from '$lib/bots/graphSource';
  import LaunchForm from '$lib/catalog/LaunchForm.svelte';
  import NodeGraphInput from '$lib/catalog/NodeGraphInput.svelte';
  import { hasGraphCapability } from '$lib/catalog/graphContracts';
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
  import { NAVIGATION_LABEL, NAVIGATION_PATH, runPath } from '$lib/navigation';
  import { formatTime } from '$lib/time';
  import { BOT_DETAIL_COPY, botGraphRevisionLabel } from './copy';

  let bot = $state<BotRead>();
  let bots = $state<BotRead[]>([]);
  let descriptor = $state<BotDefinitionDescriptor>();
  let savedInputs = $state<LaunchInputs>({});
  let editedInputs = $state<LaunchInputs>({});
  let savedGraph = $state<NodeGraph>();
  let editedGraph = $state<NodeGraph>();
  let graphEditorResetKey = $state('');
  let graphSourceName = $state<string>(GRAPH_SOURCE_COPY.CURRENT);
  let loading = $state(true);
  let saving = $state(false);
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
      const [botResponse, definitionsResponse, botsResponse] = await Promise.all([
        readBotApiV1BotsBotIdGet({ path: { bot_id: botId }, throwOnError: true }),
        listBotDefinitionsApiV1BotDefinitionsGet({ throwOnError: true }),
        listBotsApiV1BotsGet({ throwOnError: true })
      ]);
      bot = botResponse.data;
      bots = botsResponse.data;
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

  function selectGraph(nextGraph: NodeGraph, sourceName: string): void {
    editedGraph = nextGraph;
    graphSourceName = sourceName;
    graphServerIssues = [];
    graphEditorResetKey = `${sourceName}:${Date.now()}`;
  }

  async function saveChanges(inputs: LaunchInputs): Promise<void> {
    if (!bot) return;
    const graphToSave = editedGraph;
    const shouldSaveConfig = JSON.stringify(savedInputs) !== JSON.stringify(inputs);
    const shouldSaveGraph = !nodeGraphsEqual(savedGraph, graphToSave);
    if (!shouldSaveConfig && !shouldSaveGraph) return;

    saving = true;
    error = '';
    configServerIssues = [];
    graphServerIssues = [];
    let phase: 'config' | 'graph' = 'config';
    try {
      if (shouldSaveConfig) {
        const response = await updateBotApiV1BotsBotIdPatch({
          path: { bot_id: bot.id },
          body: { inputs },
          throwOnError: true
        });
        bot = response.data;
        savedInputs = inputs;
        editedInputs = inputs;
      }

      if (shouldSaveGraph && graphToSave) {
        phase = 'graph';
        const response = await createBotGraphRevisionApiV1BotsBotIdGraphRevisionsPost({
          path: { bot_id: bot.id },
          body: { graph: graphToSave },
          throwOnError: true
        });
        bot = response.data;
        savedGraph = response.data.latest_graph_revision?.graph;
        editedGraph = savedGraph;
        graphSourceName = GRAPH_SOURCE_COPY.CURRENT;
        graphEditorResetKey = response.data.latest_graph_revision?.id ?? '';
      }
    } catch (caught) {
      if (phase === 'config') {
        configServerIssues = launchRequestValidationIssues(caught);
        if (configServerIssues.length === 0) error = BOT_DETAIL_COPY.CONFIG_SAVE_ERROR;
      } else if (graphToSave) {
        graphServerIssues = graphValidationIssues(caught, graphToSave);
        if (graphServerIssues.length > 0) {
          await tick();
          document.getElementById('bot-graph-validation')?.focus();
        } else {
          error = BOT_DETAIL_COPY.GRAPH_SAVE_ERROR;
        }
      }
    } finally {
      saving = false;
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

<svelte:head>
  <title>{bot ? `${bot.config.name} | Polybot` : 'Bot | Polybot'}</title>
</svelte:head>

<a class="back-link" href={NAVIGATION_PATH.HOME}>
  <ArrowLeftIcon aria-hidden="true" size={16} />
  {NAVIGATION_LABEL.BACK_TO_BOTS}
</a>

{#if loading}
  <div class="loading-state" aria-live="polite">
    <span class="sr-only">Loading bot</span>
    <div class="skeleton skeleton-heading" aria-hidden="true"></div>
    <div class="skeleton skeleton-line" aria-hidden="true"></div>
    <div class="skeleton skeleton-panel" aria-hidden="true"></div>
  </div>
{:else if !bot || !descriptor}
  <p class="notice error" role="alert">{error}</p>
{:else}
  <header class="bot-detail-heading page-heading">
    <div>
      <p class="route-meta">Updated {formatTime(bot.updated_at)}</p>
      <h1>{bot.config.name}</h1>
      <p>Configuration and strategy are saved together before a run can start.</p>
    </div>
    <button onclick={runBot} disabled={running || hasUnsavedChanges} aria-busy={running}>
      <PlayIcon aria-hidden="true" size={17} weight="fill" />
      {running ? BOT_DETAIL_COPY.STARTING : BOT_DETAIL_COPY.RUN}
    </button>
  </header>

  {#if error}<p class="notice error" role="alert">{error}</p>{/if}
  {#if hasUnsavedChanges}
    <p class="notice unsaved-notice">{BOT_DETAIL_COPY.UNSAVED_RUN_BLOCK}</p>
  {/if}

  <LaunchForm
    {descriptor}
    initialInputs={savedInputs}
    onsubmit={saveChanges}
    onchange={(inputs) => {
      editedInputs = inputs;
      configServerIssues = [];
    }}
    busy={saving}
    disabled={!hasUnsavedChanges}
    submitLabel={BOT_DETAIL_COPY.SAVE_CHANGES}
    busyLabel={BOT_DETAIL_COPY.SAVING_CHANGES}
    serverIssues={configServerIssues}
    showSelectionNotes={false}
    sectionTitle="Configuration"
    sectionDescription="Adjust the market scope, risk limits, and paper execution behavior."
  >
    {#if hasGraphCapability(descriptor) && savedGraph && editedGraph}
      <section class="builder-section graph-builder-section">
        <header class="builder-section-heading">
          <div>
            <h2 id="bot-graph-editor-label">
              Strategy graph
              <span class="revision-label">{botGraphRevisionLabel(bot.latest_graph_revision?.revision)}</span>
            </h2>
            <p>Edit the current graph or replace it with the latest graph from another bot. Current source: {graphSourceName}.</p>
          </div>
          <span class="save-state">{graphDirty ? BOT_DETAIL_COPY.UNSAVED : BOT_DETAIL_COPY.SAVED}</span>
        </header>
        <GraphSourcePicker
          {bots}
          starterGraph={descriptor.starter_graph}
          excludeBotId={bot.id}
          onselect={selectGraph}
        />
        {#key graphEditorResetKey}
          <NodeGraphInput
            initialGraph={editedGraph}
            graphCatalog={descriptor.graph_catalog}
            onchange={(nextGraph) => {
              editedGraph = nextGraph;
              graphServerIssues = [];
            }}
            labelledby="bot-graph-editor-label"
            validationIssues={graphServerIssues}
            validationSummaryId="bot-graph-validation"
          />
        {/key}
      </section>
    {/if}
  </LaunchForm>
{/if}
