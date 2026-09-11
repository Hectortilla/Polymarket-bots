<script lang="ts">
  import { SERVICE_NAME } from "$lib/serviceIdentity";
  import { LaunchAttempt } from "$lib/bots/launchAttempt";
  import { HTTP_STATUS, isClientRejection } from "$lib/api/http";
  import { resourceLimitDetail } from "$lib/limits/validation";
  import { goto } from "$app/navigation";
  import { page } from "$app/state";
  import "$lib/bots/builder.css";
  import { BOT_BUILDER_COPY } from "$lib/bots/copy";
  import { readSavedBot, BotNotFoundError } from "$lib/bots/read";
  import ArrowLeftIcon from "phosphor-svelte/lib/ArrowLeftIcon";
  import TrashIcon from "phosphor-svelte/lib/TrashIcon";
  import PlayIcon from "phosphor-svelte/lib/PlayIcon";
  import { onMount, tick } from "svelte";

  import {
    deleteBotApiV1BotsBotIdDelete,
    launchBotRunApiV1BotsBotIdRunsPost,
    listBotDefinitionsApiV1BotDefinitionsGet,
    listBotsApiV1BotsGet,
    updateBotApiV1BotsBotIdPatch,
    type BotDefinitionDescriptor,
    type BotRead,
    type NodeGraph,
  } from "$lib/api/generated";
  import GraphSourcePicker from "$lib/bots/GraphSourcePicker.svelte";
  import { GRAPH_SOURCE_COPY } from "$lib/bots/graphSource";
  import LaunchForm from "$lib/catalog/LaunchForm.svelte";
  import NodeGraphInput from "$lib/catalog/NodeGraphInput.svelte";
  import { hasGraphCapability } from "$lib/catalog/graphContracts";
  import { graphValidationIssues, type GraphValidationIssue } from "$lib/catalog/graphValidation";
  import { nodeGraphsEqual } from "$lib/catalog/nodeGraphEquality";
  import { launchInputsFromConfig } from "$lib/catalog/schema/inputs";
  import { launchRequestValidationIssues } from "$lib/catalog/schema/validation";
  import { type LaunchInputs, type LaunchValidationIssue } from "$lib/catalog/schema/contracts";
  import { NAVIGATION_LABEL, NAVIGATION_PATH, runPath } from "$lib/navigation";
  import { formatTime } from "$lib/time";
  import { BOT_DETAIL_COPY } from "./copy";

  let bot = $state<BotRead>();
  let bots = $state<BotRead[]>([]);
  let descriptor = $state<BotDefinitionDescriptor>();
  let savedInputs = $state<LaunchInputs>({});
  let editedInputs = $state<LaunchInputs>({});
  let savedGraph = $state<NodeGraph>();
  let editedGraph = $state<NodeGraph>();
  let graphEditorResetKey = $state("");
  let graphSourceName = $state<string>(GRAPH_SOURCE_COPY.CURRENT);
  let loading = $state(true);
  let saving = $state(false);
  let running = $state(false);
  let confirmingDelete = $state(false);
  let deleting = $state(false);
  let error = $state("");
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
      const [savedBot, definitionsResponse, botsResponse] = await Promise.all([
        readSavedBot(botId),
        listBotDefinitionsApiV1BotDefinitionsGet({ throwOnError: true }),
        listBotsApiV1BotsGet({ throwOnError: true }),
      ]);
      bot = savedBot;
      bots = botsResponse.data;
      descriptor = definitionsResponse.data.find((definition) => definition.definition_id === bot?.definition_id);
      if (!descriptor) throw new Error("definition missing");
      savedInputs = launchInputsFromConfig(descriptor, bot.config);
      editedInputs = savedInputs;
      savedGraph = bot.config.graph ?? undefined;
      editedGraph = savedGraph;
      graphEditorResetKey = JSON.stringify(bot.config.graph);
    } catch (caught) {
      error = caught instanceof BotNotFoundError ? BOT_DETAIL_COPY.NOT_FOUND : BOT_DETAIL_COPY.LOAD_ERROR;
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
    if (!bot || saving || running || confirmingDelete || deleting) return;
    const graphToSave = editedGraph;
    const shouldSaveConfig = JSON.stringify(savedInputs) !== JSON.stringify(inputs);
    const shouldSaveGraph = !nodeGraphsEqual(savedGraph, graphToSave);
    if (!shouldSaveConfig && !shouldSaveGraph) return;

    saving = true;
    error = "";
    configServerIssues = [];
    graphServerIssues = [];
    try {
      const response = await updateBotApiV1BotsBotIdPatch({
        path: { bot_id: bot.id },
        body: { inputs, graph: graphToSave },
        throwOnError: true,
      });
      bot = response.data;
      savedInputs = inputs;
      editedInputs = inputs;
      savedGraph = bot.config.graph ?? undefined;
      editedGraph = savedGraph;
      graphSourceName = GRAPH_SOURCE_COPY.CURRENT;
      graphEditorResetKey = JSON.stringify(savedGraph);
    } catch (caught) {
      configServerIssues = launchRequestValidationIssues(caught);
      graphServerIssues = graphToSave ? graphValidationIssues(caught, graphToSave) : [];
      if (graphServerIssues.length > 0) {
        await tick();
        document.getElementById("bot-graph-validation")?.focus();
      }
      if (configServerIssues.length === 0 && graphServerIssues.length === 0) {
        error = resourceLimitDetail(caught) ?? BOT_DETAIL_COPY.CONFIG_SAVE_ERROR;
      }
    } finally {
      saving = false;
    }
  }

  async function runBot(): Promise<void> {
    if (!bot || hasUnsavedChanges || running || saving || confirmingDelete || deleting) return;
    running = true;
    error = "";
    const attempt = new LaunchAttempt(bot.id);
    try {
      const response = await launchBotRunApiV1BotsBotIdRunsPost({
        path: { bot_id: bot.id },
        headers: attempt.requestHeaders(),
      });
      if (!response.data) {
        const failure = resolveLaunchFailure(response.response?.status, response.error);
        if (failure.rejected) attempt.complete();
        error = failure.message;
        return;
      }
      await goto(runPath(response.data.id));
      attempt.complete();
    } catch (caught) {
      error = resourceLimitDetail(caught) ?? BOT_DETAIL_COPY.RUN_ERROR;
    } finally {
      running = false;
    }
  }
  async function deleteBot(): Promise<void> {
    if (!bot || !confirmingDelete || deleting || saving || running) return;
    deleting = true;
    error = "";
    try {
      const response = await deleteBotApiV1BotsBotIdDelete({ path: { bot_id: bot.id } });
      if (response.response?.status === HTTP_STATUS.CONFLICT) {
        error = BOT_DETAIL_COPY.DELETE_ACTIVE_RUNS;
        return;
      }
      if (response.response?.status !== HTTP_STATUS.NO_CONTENT && response.response?.status !== HTTP_STATUS.NOT_FOUND) {
        error = BOT_DETAIL_COPY.DELETE_ERROR;
        return;
      }
      await goto(NAVIGATION_PATH.HOME);
    } catch {
      error = BOT_DETAIL_COPY.DELETE_ERROR;
    } finally {
      deleting = false;
    }
  }

  function resolveLaunchFailure(status: number | undefined, detail: unknown): { rejected: boolean; message: string } {
    const admissionRejection = resourceLimitDetail(detail);
    const rejected = isClientRejection(status) || admissionRejection !== undefined;
    if (status === HTTP_STATUS.GONE) return { rejected, message: BOT_DETAIL_COPY.EXPIRED_LAUNCH };
    return { rejected, message: admissionRejection ?? BOT_DETAIL_COPY.RUN_ERROR };
  }
</script>

<svelte:head>
  <title>{bot ? `${bot.config.name} | ${SERVICE_NAME}` : `Bot | ${SERVICE_NAME}`}</title>
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
    <div class="bot-actions">
      <button
        class="danger-action"
        onclick={() => {
          confirmingDelete = true;
          error = "";
        }}
        disabled={saving || running || confirmingDelete || deleting}
        aria-expanded={confirmingDelete}
        aria-controls="delete-bot-confirmation"
      >
        <TrashIcon aria-hidden="true" size={17} />
        {BOT_DETAIL_COPY.DELETE}
      </button>
      <button
        onclick={runBot}
        disabled={running || saving || hasUnsavedChanges || confirmingDelete || deleting}
        aria-busy={running}
      >
        <PlayIcon aria-hidden="true" size={17} weight="fill" />
        {running ? BOT_DETAIL_COPY.STARTING : BOT_DETAIL_COPY.RUN}
      </button>
    </div>
  </header>

  {#if confirmingDelete}
    <section id="delete-bot-confirmation" class="delete-bot-confirmation" aria-labelledby="delete-bot-heading">
      <h2 id="delete-bot-heading">{BOT_DETAIL_COPY.DELETE}: {bot.config.name}</h2>
      <p>{BOT_DETAIL_COPY.DELETE_DESCRIPTION}</p>
      <div class="bot-actions">
        <button
          class="secondary"
          onclick={() => {
            confirmingDelete = false;
            error = "";
          }}
          disabled={deleting}
        >
          {BOT_DETAIL_COPY.DELETE_CANCEL}
        </button>
        <button class="danger-action" onclick={deleteBot} disabled={deleting} aria-busy={deleting}>
          {deleting ? BOT_DETAIL_COPY.DELETING : BOT_DETAIL_COPY.DELETE_CONFIRM}
        </button>
      </div>
    </section>
  {/if}
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
    disabled={!hasUnsavedChanges || running || confirmingDelete || deleting}
    submitLabel={BOT_DETAIL_COPY.SAVE_CHANGES}
    busyLabel={BOT_DETAIL_COPY.SAVING_CHANGES}
    serverIssues={configServerIssues}
    showSelectionNotes={false}
    sectionTitle={BOT_BUILDER_COPY.CONFIGURATION}
    sectionDescription="Adjust the market scope, risk limits, and paper execution behavior."
  >
    {#if hasGraphCapability(descriptor) && savedGraph && editedGraph}
      <section class="builder-section graph-builder-section">
        <header class="builder-section-heading">
          <div>
            <h2 id="bot-graph-editor-label">
              {BOT_BUILDER_COPY.STRATEGY_GRAPH}
            </h2>
            <p>
              Edit the current graph or replace it with the latest graph from another bot. Current source: {graphSourceName}.
            </p>
          </div>
          <span class="save-state">{graphDirty ? BOT_DETAIL_COPY.UNSAVED : BOT_DETAIL_COPY.SAVED}</span>
        </header>
        <GraphSourcePicker
          {bots}
          starterGraph={descriptor.starter_graph}
          examples={descriptor.graph_examples}
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

<style>
  .bot-actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.75rem;
  }

  .delete-bot-confirmation {
    margin-bottom: 1.5rem;
    padding: 1.25rem;
    border: 1px solid var(--danger);
    border-radius: var(--radius-surface);
    background: var(--danger-surface);
  }

  .delete-bot-confirmation p {
    margin: 0.75rem 0 1rem;
  }
</style>
