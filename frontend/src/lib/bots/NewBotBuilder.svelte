<script lang="ts">
  import { SERVICE_NAME } from "$lib/serviceIdentity";
  import { SavedBotDraft } from "./savedDraft";
  import { DraftSaveFeedback } from "./savedDraft/feedback";
  import { goto } from "$app/navigation";
  import { BOT_BUILDER_COPY } from "$lib/bots/copy";
  import ArrowLeftIcon from "phosphor-svelte/lib/ArrowLeftIcon";
  import { onMount, tick } from "svelte";
  import "./builder.css";

  import {
    listBotDefinitionsApiV1BotDefinitionsGet,
    listBotsApiV1BotsGet,
    type BotDefinitionDescriptor,
    type BotRead,
    type NodeGraph,
  } from "$lib/api/generated";
  import GraphSourcePicker from "$lib/bots/GraphSourcePicker.svelte";
  import { GRAPH_SOURCE_COPY } from "$lib/bots/graphSource";
  import LaunchForm from "$lib/catalog/LaunchForm.svelte";
  import NodeGraphInput from "$lib/catalog/NodeGraphInput.svelte";
  import { cloneNodeGraph, hasGraphCapability } from "$lib/catalog/graphContracts";
  import { type GraphValidationIssue } from "$lib/catalog/graphValidation";
  import { type LaunchInputs, type LaunchValidationIssue } from "$lib/catalog/schema";
  import { NAVIGATION_LABEL, NAVIGATION_PATH, botPath } from "$lib/navigation";

  let descriptor = $state<BotDefinitionDescriptor>();
  let bots = $state<BotRead[]>([]);
  let graph = $state<NodeGraph>();
  let graphEditorResetKey = $state(0);
  let graphSourceName = $state<string>(GRAPH_SOURCE_COPY.FRESH);
  let loading = $state(true);
  let saving = $state(false);
  let saveUncertain = $state(false);
  const savedDraft = new SavedBotDraft();
  let error = $state("");
  let configServerIssues = $state<LaunchValidationIssue[]>([]);
  let graphServerIssues = $state<GraphValidationIssue[]>([]);

  onMount(() => {
    void loadBuilder();
  });

  async function loadBuilder(): Promise<void> {
    loading = true;
    error = "";
    try {
      const [definitionsResponse, botsResponse] = await Promise.all([
        listBotDefinitionsApiV1BotDefinitionsGet({ throwOnError: true }),
        listBotsApiV1BotsGet({ throwOnError: true }),
      ]);
      descriptor = definitionsResponse.data.find(hasGraphCapability);
      bots = botsResponse.data.filter((bot) => bot.config.graph);
      if (!hasGraphCapability(descriptor)) {
        error = BOT_BUILDER_COPY.MISSING_DEFINITION;
        return;
      }
      graph = cloneNodeGraph(descriptor.starter_graph);
    } catch {
      error = BOT_BUILDER_COPY.LOAD_ERROR;
    } finally {
      loading = false;
    }
  }

  function selectGraph(nextGraph: NodeGraph, sourceName: string): void {
    graph = nextGraph;
    graphSourceName = sourceName;
    graphServerIssues = [];
    graphEditorResetKey += 1;
  }

  async function createSavedBot(inputs: LaunchInputs): Promise<void> {
    if (saving || saveUncertain || !hasGraphCapability(descriptor) || !graph) return;
    const graphToSave = graph;
    saving = true;
    error = "";
    configServerIssues = [];
    graphServerIssues = [];
    try {
      const bot = await savedDraft.save(descriptor.definition_id, inputs, graphToSave);
      await goto(botPath(bot.id));
    } catch (caught) {
      const failure = DraftSaveFeedback.fromFailure(caught, graphToSave);
      configServerIssues = failure.inputIssues;
      graphServerIssues = failure.graphIssues;
      saveUncertain = failure.uncertain;
      if (graphServerIssues.length > 0) {
        await tick();
        document.getElementById("new-bot-graph-validation")?.focus();
      } else if (configServerIssues.length === 0) {
        error = failure.message(BOT_BUILDER_COPY.SAVE_ERROR);
      }
    } finally {
      saving = false;
    }
  }
</script>

<svelte:head>
  <title>{NAVIGATION_LABEL.NEW_BOT} | {SERVICE_NAME}</title>
  <meta name="description" content="Configure a paper bot and build its node strategy in one workspace." />
</svelte:head>

<a class="back-link" href={NAVIGATION_PATH.HOME}>
  <ArrowLeftIcon aria-hidden="true" size={16} />
  {NAVIGATION_LABEL.BACK_TO_BOTS}
</a>

{#if loading}
  <div class="loading-state" aria-live="polite">
    <span class="sr-only">Loading bot builder</span>
    <div class="skeleton skeleton-heading" aria-hidden="true"></div>
    <div class="skeleton skeleton-line" aria-hidden="true"></div>
    <div class="skeleton skeleton-panel" aria-hidden="true"></div>
  </div>
{:else if !hasGraphCapability(descriptor) || !graph}
  <p class="notice error" role="alert">{error || BOT_BUILDER_COPY.MISSING_DEFINITION}</p>
{:else}
  <header class="builder-page-heading">
    <p class="page-kicker">{NAVIGATION_LABEL.NEW_BOT}</p>
    <h1>Configure how your bot trades.</h1>
    <p>Set the operating limits and build the strategy graph before saving.</p>
  </header>

  {#if error}<p class="notice error" role="alert">{error}</p>{/if}

  <LaunchForm
    {descriptor}
    onsubmit={createSavedBot}
    busy={saving}
    disabled={saveUncertain}
    submitLabel={BOT_BUILDER_COPY.CREATE}
    busyLabel={BOT_BUILDER_COPY.CREATING}
    serverIssues={configServerIssues}
    showSelectionNotes={false}
    sectionTitle={BOT_BUILDER_COPY.CONFIGURATION}
    sectionDescription="Name the bot, choose its markets, and set paper-trading limits."
  >
    <section class="builder-section graph-builder-section">
      <header class="builder-section-heading">
        <div>
          <h2 id="new-bot-graph-label">{BOT_BUILDER_COPY.STRATEGY_GRAPH}</h2>
          <p>Build the event logic this bot will execute. Current source: {graphSourceName}.</p>
        </div>
      </header>
      <GraphSourcePicker
        {bots}
        starterGraph={descriptor.starter_graph}
        examples={descriptor.graph_examples}
        onselect={selectGraph}
      />
      {#key graphEditorResetKey}
        <NodeGraphInput
          initialGraph={graph}
          graphCatalog={descriptor.graph_catalog}
          onchange={(nextGraph) => {
            graph = nextGraph;
            graphServerIssues = [];
          }}
          labelledby="new-bot-graph-label"
          validationIssues={graphServerIssues}
          validationSummaryId="new-bot-graph-validation"
        />
      {/key}
    </section>
  </LaunchForm>
{/if}
