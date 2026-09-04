<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount, tick } from 'svelte';
  import ArrowLeftIcon from 'phosphor-svelte/lib/ArrowLeftIcon';

  import {
    createBotApiV1BotsPost,
    createGraphTemplateApiV1GraphTemplatesPost,
    listBotDefinitionsApiV1BotDefinitionsGet,
    listBotsApiV1BotsGet,
    type BotDefinitionDescriptor,
    type BotRead,
    type NodeGraph
  } from '$lib/api/generated';
  import GraphSourcePicker from '$lib/bots/GraphSourcePicker.svelte';
  import { GRAPH_SOURCE_COPY } from '$lib/bots/graphSource';
  import LaunchForm from '$lib/catalog/LaunchForm.svelte';
  import NodeGraphInput from '$lib/catalog/NodeGraphInput.svelte';
  import { cloneNodeGraph, hasGraphCapability } from '$lib/catalog/graphContracts';
  import {
    graphValidationIssues,
    type GraphValidationIssue
  } from '$lib/catalog/graphValidation';
  import {
    launchRequestValidationIssues,
    type LaunchInputs,
    type LaunchValidationIssue
  } from '$lib/catalog/schema';
  import { NAVIGATION_LABEL, NAVIGATION_PATH, botPath } from '$lib/navigation';

  const COPY = {
    LOAD_ERROR: 'The bot builder could not be loaded.',
    MISSING_DEFINITION: 'The node-based bot definition is unavailable.',
    SAVE_ERROR: 'The bot could not be saved. Your configuration and graph are still here.'
  } as const;

  let descriptor = $state<BotDefinitionDescriptor>();
  let bots = $state<BotRead[]>([]);
  let graph = $state<NodeGraph>();
  let graphEditorResetKey = $state(0);
  let graphSourceName = $state<string>(GRAPH_SOURCE_COPY.FRESH);
  let loading = $state(true);
  let saving = $state(false);
  let error = $state('');
  let configServerIssues = $state<LaunchValidationIssue[]>([]);
  let graphServerIssues = $state<GraphValidationIssue[]>([]);

  onMount(() => {
    void loadBuilder();
  });

  async function loadBuilder(): Promise<void> {
    loading = true;
    error = '';
    try {
      const [definitionsResponse, botsResponse] = await Promise.all([
        listBotDefinitionsApiV1BotDefinitionsGet({ throwOnError: true }),
        listBotsApiV1BotsGet({ throwOnError: true })
      ]);
      descriptor = definitionsResponse.data.find(hasGraphCapability);
      bots = botsResponse.data.filter((bot) => bot.latest_graph_revision);
      if (!hasGraphCapability(descriptor)) {
        error = COPY.MISSING_DEFINITION;
        return;
      }
      graph = cloneNodeGraph(descriptor.starter_graph);
    } catch {
      error = COPY.LOAD_ERROR;
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

  function privateTemplateName(): string {
    return `bot-draft-${Date.now()}`;
  }

  async function createSavedBot(inputs: LaunchInputs): Promise<void> {
    if (!hasGraphCapability(descriptor) || !graph) return;
    const graphToSave = graph;
    saving = true;
    error = '';
    configServerIssues = [];
    graphServerIssues = [];
    try {
      const templateResponse = await createGraphTemplateApiV1GraphTemplatesPost({
        body: { name: privateTemplateName(), graph: graphToSave },
        throwOnError: true
      });
      const botResponse = await createBotApiV1BotsPost({
        body: {
          definition_id: descriptor.definition_id,
          inputs,
          graph_template_id: templateResponse.data.id
        },
        throwOnError: true
      });
      await goto(botPath(botResponse.data.id));
    } catch (caught) {
      configServerIssues = launchRequestValidationIssues(caught);
      graphServerIssues = graphValidationIssues(caught, graphToSave);
      if (graphServerIssues.length > 0) {
        await tick();
        document.getElementById('new-bot-graph-validation')?.focus();
      } else if (configServerIssues.length === 0) {
        error = COPY.SAVE_ERROR;
      }
    } finally {
      saving = false;
    }
  }
</script>

<svelte:head>
  <title>New bot | Polybot</title>
  <meta
    name="description"
    content="Configure a paper bot and build its node strategy in one workspace."
  />
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
  <p class="notice error" role="alert">{error || COPY.MISSING_DEFINITION}</p>
{:else}
  <header class="builder-page-heading">
    <p class="page-kicker">New bot</p>
    <h1>Configure how your bot trades.</h1>
    <p>Set the operating limits and build the strategy graph before saving.</p>
  </header>

  {#if error}<p class="notice error" role="alert">{error}</p>{/if}

  <LaunchForm
    {descriptor}
    onsubmit={createSavedBot}
    busy={saving}
    submitLabel="Create bot"
    busyLabel="Creating bot"
    serverIssues={configServerIssues}
    showSelectionNotes={false}
    sectionTitle="Configuration"
    sectionDescription="Name the bot, choose its markets, and set paper-trading limits."
  >
    <section class="builder-section graph-builder-section">
      <header class="builder-section-heading">
        <div>
          <h2 id="new-bot-graph-label">Strategy graph</h2>
          <p>Build the event logic this bot will execute. Current source: {graphSourceName}.</p>
        </div>
      </header>
      <GraphSourcePicker
        {bots}
        starterGraph={descriptor.starter_graph}
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
