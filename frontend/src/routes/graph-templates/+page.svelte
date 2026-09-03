<script lang="ts">
  import { onMount, tick } from 'svelte';

  import {
    createGraphTemplateApiV1GraphTemplatesPost,
    listBotDefinitionsApiV1BotDefinitionsGet,
    listGraphTemplatesApiV1GraphTemplatesGet,
    updateGraphTemplateApiV1GraphTemplatesTemplateIdPatch,
    type BotDefinitionDescriptor,
    type GraphTemplateRead,
    type NodeGraph
  } from '$lib/api/generated';
  import {
    readableValidationMessage,
    requestErrorDetail,
    requestValidationIssues
  } from '$lib/api/requestErrors';
  import NodeGraphInput from '$lib/catalog/NodeGraphInput.svelte';
  import {
    graphValidationIssues,
    type GraphValidationIssue
  } from '$lib/catalog/graphValidation';
  import { hasGraphCapability } from '$lib/catalog/graphContracts';
  import { FORM_COPY } from '$lib/formCopy';
  import { NAVIGATION_LABEL, NAVIGATION_PATH } from '$lib/navigation';
  import { GRAPH_TEMPLATE_COPY } from './copy';
  import {
    GRAPH_TEMPLATE_GRAPH_FIELD,
    GRAPH_TEMPLATE_NAME_FIELD,
    GRAPH_TEMPLATE_NAME_MAX_LENGTH
  } from './contracts';

  let graphCapableDefinition = $state<BotDefinitionDescriptor>();
  let templates = $state<GraphTemplateRead[]>([]);
  let selectedTemplateId = $state('');
  let name = $state('');
  let graph = $state<NodeGraph>();
  let graphEditorResetKey = $state(0);
  let loading = $state(true);
  let saving = $state(false);
  let error = $state('');
  let nameError = $state('');
  let graphServerIssues = $state<GraphValidationIssue[]>([]);

  const selectedTemplate = $derived(
    templates.find((template) => template.id === selectedTemplateId)
  );

  function templateNameError(
    nameIssue: { msg: string } | undefined,
    detail: string | undefined
  ): string {
    if (nameIssue) return readableValidationMessage(nameIssue.msg);
    return detail?.toLowerCase().includes(GRAPH_TEMPLATE_NAME_FIELD)
      ? readableValidationMessage(detail)
      : '';
  }

  onMount(() => {
    void loadGraphTemplateWorkspace();
  });

  async function loadGraphTemplateWorkspace(): Promise<void> {
    loading = true;
    error = '';
    try {
      const [definitionsResponse, templatesResponse] = await Promise.all([
        listBotDefinitionsApiV1BotDefinitionsGet({ throwOnError: true }),
        listGraphTemplatesApiV1GraphTemplatesGet({ throwOnError: true })
      ]);
      graphCapableDefinition = definitionsResponse.data.find(
        hasGraphCapability
      );
      templates = templatesResponse.data;
      if (templates[0]) selectTemplate(templates[0].id);
      else startNewGraphTemplate();
    } catch {
      error = GRAPH_TEMPLATE_COPY.LOAD_ERROR;
    } finally {
      loading = false;
    }
  }

  function selectTemplate(templateId: string): void {
    const template = templates.find((candidate) => candidate.id === templateId);
    if (!template) return;
    selectedTemplateId = template.id;
    name = template.name;
    graph = template.graph;
    graphEditorResetKey += 1;
    error = '';
    nameError = '';
    graphServerIssues = [];
  }

  function startNewGraphTemplate(): void {
    selectedTemplateId = '';
    name = '';
    graph = graphCapableDefinition?.starter_graph ?? undefined;
    graphEditorResetKey += 1;
    error = '';
    nameError = '';
    graphServerIssues = [];
  }

  async function saveGraphTemplate(): Promise<void> {
    if (!graph) return;
    if (!name.trim()) {
      nameError = GRAPH_TEMPLATE_COPY.NAME_REQUIRED;
      await tick();
      document.getElementById('graph-template-name')?.focus();
      return;
    }
    if (name.trim().length > GRAPH_TEMPLATE_NAME_MAX_LENGTH) {
      nameError = GRAPH_TEMPLATE_COPY.NAME_TOO_LONG(
        GRAPH_TEMPLATE_NAME_MAX_LENGTH
      );
      await tick();
      document.getElementById('graph-template-name')?.focus();
      return;
    }
    const graphToSave = graph;
    saving = true;
    error = '';
    nameError = '';
    graphServerIssues = [];
    try {
      if (selectedTemplate) {
        const response = await updateGraphTemplateApiV1GraphTemplatesTemplateIdPatch({
          path: { template_id: selectedTemplate.id },
          body: { name, graph: graphToSave },
          throwOnError: true
        });
        templates = templates.map((template) =>
          template.id === response.data.id ? response.data : template
        );
        selectTemplate(response.data.id);
      } else {
        const response = await createGraphTemplateApiV1GraphTemplatesPost({
          body: { name, graph: graphToSave },
          throwOnError: true
        });
        templates = [...templates, response.data].sort((left, right) =>
          left.name.localeCompare(right.name)
        );
        selectTemplate(response.data.id);
      }
    } catch (caught) {
      const validationIssues = requestValidationIssues(caught);
      const nameIssue = validationIssues.find((issue) =>
        issue.loc.includes(GRAPH_TEMPLATE_NAME_FIELD)
      );
      const graphIssues = validationIssues.filter((issue) =>
        issue.loc.includes(GRAPH_TEMPLATE_GRAPH_FIELD)
      );
      const detail = requestErrorDetail(caught);

      nameError = templateNameError(nameIssue, detail);
      graphServerIssues = graphValidationIssues(
        { detail: graphIssues },
        graphToSave
      );
      if (nameError) {
        await tick();
        document.getElementById('graph-template-name')?.focus();
      } else if (graphServerIssues.length > 0) {
        await tick();
        document.getElementById('graph-template-validation')?.focus();
      } else {
        error = validationIssues[0]
          ? readableValidationMessage(validationIssues[0].msg)
          : GRAPH_TEMPLATE_COPY.SAVE_ERROR;
      }
    } finally {
      saving = false;
    }
  }
</script>

<svelte:head><title>{NAVIGATION_LABEL.GRAPH_TEMPLATES} | Polybot</title></svelte:head>

<a class="back-link" href={NAVIGATION_PATH.HOME}>{NAVIGATION_LABEL.BACK_TO_OPERATIONS}</a>

<section class="page-heading">
  <div>
    <p class="page-kicker">Reusable catalog</p>
    <h1>{NAVIGATION_LABEL.GRAPH_TEMPLATES}</h1>
    <p>Templates are editable starting points. Saving a bot copies the template, so neither side changes the other.</p>
  </div>
  <button class="secondary" onclick={startNewGraphTemplate}>{GRAPH_TEMPLATE_COPY.NEW}</button>
</section>

{#if error}<p class="notice error" role="alert">{error}</p>{/if}

{#if loading}
  <p class="empty-state">Loading graph templates…</p>
{:else if !hasGraphCapability(graphCapableDefinition) || !graph}
  <p class="notice error">{GRAPH_TEMPLATE_COPY.MISSING_CAPABILITY}</p>
{:else}
  <section class="template-workspace">
    <aside class="template-list" aria-label={NAVIGATION_LABEL.GRAPH_TEMPLATES}>
      <button class:active={!selectedTemplateId} class="secondary" onclick={startNewGraphTemplate}>Untitled template</button>
      {#each templates as template (template.id)}
        <button
          class:active={selectedTemplateId === template.id}
          class="secondary"
          onclick={() => selectTemplate(template.id)}
        >{template.name}</button>
      {/each}
    </aside>

    <div class="template-editor">
      <label>
        <span class="field-label" id="graph-template-name-label">
          {GRAPH_TEMPLATE_COPY.NAME}
        </span>
        <input
          id="graph-template-name"
          maxlength={GRAPH_TEMPLATE_NAME_MAX_LENGTH}
          value={name}
          placeholder="Example: BTC threshold buyer"
          aria-labelledby="graph-template-name-label"
          aria-describedby={nameError ? 'graph-template-name-error' : undefined}
          aria-invalid={Boolean(nameError)}
          oninput={(event) => {
            name = event.currentTarget.value;
            nameError = '';
          }}
        />
        {#if nameError}
          <span class="field-errors" id="graph-template-name-error" aria-live="polite">
            <span>{nameError}</span>
          </span>
        {/if}
      </label>
      <!-- Remount canvas-owned state after switching persisted templates. -->
      {#key graphEditorResetKey}
        <NodeGraphInput
          initialGraph={graph}
          graphCatalog={graphCapableDefinition.graph_catalog}
          onchange={(nextGraph) => {
            graph = nextGraph;
            graphServerIssues = [];
          }}
          labelledby="graph-template-editor-label"
          validationIssues={graphServerIssues}
          validationSummaryId="graph-template-validation"
        />
      {/key}
      <span class="sr-only" id="graph-template-editor-label">Graph template editor</span>
      <button onclick={saveGraphTemplate} disabled={saving} aria-busy={saving}>
        {saving ? FORM_COPY.SAVING : selectedTemplate ? GRAPH_TEMPLATE_COPY.SAVE : GRAPH_TEMPLATE_COPY.CREATE}
      </button>
    </div>
  </section>
{/if}
