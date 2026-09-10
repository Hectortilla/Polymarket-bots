<script lang="ts">
  import { SERVICE_NAME } from "$lib/serviceIdentity";
  import { onMount, tick } from "svelte";
  import { goto } from "$app/navigation";
  import { listBotDefinitionsApiV1BotDefinitionsGet, type GraphExample } from "$lib/api/generated";
  import { hasGraphCapability, type GraphCapableDefinition } from "$lib/catalog/graphContracts";
  import LaunchForm from "$lib/catalog/LaunchForm.svelte";
  import { type LaunchInputs, type LaunchValidationIssue } from "$lib/catalog/schema";
  import { type GraphValidationIssue } from "$lib/catalog/graphValidation";
  import { SavedBotDraft } from "$lib/bots/savedDraft";
  import { DraftSaveFeedback } from "$lib/bots/savedDraft/feedback";
  import AccountUsage from "$lib/limits/AccountUsage.svelte";
  import contract from "$lib/runtimeContract.fixture.json";
  import { NAVIGATION_LABEL, NAVIGATION_PATH, botPath } from "$lib/navigation";
  import { ONBOARDING_COPY, ONBOARDING_STEP, ONBOARDING_STEP_LABEL, type OnboardingStep } from "./copy";
  import ReviewSettings from "./ReviewSettings.svelte";

  const draft = new SavedBotDraft();
  let descriptor = $state<GraphCapableDefinition>();
  let exampleIndex = $state(0);
  let example = $derived<GraphExample | undefined>(descriptor?.graph_examples?.[exampleIndex]);
  let step = $state<OnboardingStep>(ONBOARDING_STEP.EXAMPLE);
  let loading = $state(true);
  let saving = $state(false);
  let saveUncertain = $state(false);
  let error = $state("");
  let inputs = $state<LaunchInputs>({});
  let inputIssues = $state<LaunchValidationIssue[]>([]);
  let graphIssues = $state<GraphValidationIssue[]>([]);
  let heading = $state<HTMLHeadingElement>();
  const stepLabel = $derived(ONBOARDING_STEP_LABEL[step]);

  onMount(() => {
    void loadOnboardingExamples();
  });

  async function loadOnboardingExamples(): Promise<void> {
    loading = true;
    error = "";
    try {
      const response = await listBotDefinitionsApiV1BotDefinitionsGet({ throwOnError: true });
      descriptor = response.data.find(hasGraphCapability);
      if (!descriptor?.graph_examples?.length) error = ONBOARDING_COPY.LOAD_ERROR;
    } catch {
      error = ONBOARDING_COPY.LOAD_ERROR;
    } finally {
      loading = false;
    }
  }

  async function review(validatedInputs: LaunchInputs): Promise<void> {
    inputs = validatedInputs;
    inputIssues = [];
    error = "";
    await moveToStep(ONBOARDING_STEP.REVIEW);
  }

  async function savePrivateBot(): Promise<void> {
    if (saving || saveUncertain || !descriptor || !example) return;
    saving = true;
    error = "";
    graphIssues = [];
    try {
      const bot = await draft.save(descriptor.definition_id, inputs, example.graph);
      await goto(botPath(bot.id));
    } catch (caught) {
      const failure = DraftSaveFeedback.fromFailure(caught, example.graph);
      inputIssues = failure.inputIssues;
      graphIssues = failure.graphIssues;
      saveUncertain = failure.uncertain;
      error = failure.message(ONBOARDING_COPY.SAVE_ERROR);
      if (inputIssues.length) await moveToStep(ONBOARDING_STEP.SETTINGS);
    } finally {
      saving = false;
    }
  }
  async function moveToStep(next: OnboardingStep): Promise<void> {
    step = next;
    await tick();
    heading?.focus();
  }
</script>

<svelte:head><title>{ONBOARDING_COPY.START} | {SERVICE_NAME}</title></svelte:head>
<section class="guided-bot">
  <a class="back-link" href={NAVIGATION_PATH.HOME}>{NAVIGATION_LABEL.BACK_TO_BOTS}</a>
  <h1>{ONBOARDING_COPY.START}</h1>
  <p>{ONBOARDING_COPY.PAPER_ONLY}</p>
  <AccountUsage />
  <p><a href={contract.accountManagement.accountPath}>{ONBOARDING_COPY.VERIFY}</a></p>
  {#if loading}<p role="status">{ONBOARDING_COPY.LOADING}</p>
  {:else if !descriptor || !example}
    <p role="alert">{error || ONBOARDING_COPY.LOAD_ERROR}</p>
    <button onclick={loadOnboardingExamples}>{ONBOARDING_COPY.RETRY}</button>
  {:else}
    <nav aria-label="Setup progress">
      <ol>
        {#each Object.values(ONBOARDING_STEP) as item}
          <li aria-current={step === item ? "step" : undefined}>{ONBOARDING_STEP_LABEL[item]}</li>
        {/each}
      </ol>
    </nav>
    <h2 bind:this={heading} tabindex="-1">{stepLabel}</h2>
    {#if error}<p role="alert">{error}</p>{/if}
    {#each graphIssues as issue}<p role="alert">{issue.message}</p>{/each}
    <!-- Keep LaunchForm mounted so Back preserves the entered settings. -->
    <div hidden={step !== ONBOARDING_STEP.EXAMPLE}>
      <fieldset disabled={saving}>
        <legend class="sr-only">{ONBOARDING_COPY.CHOOSE}</legend>
        {#each descriptor.graph_examples ?? [] as option, index}
          <label
            ><input type="radio" name="example" value={index} bind:group={exampleIndex} />
            <strong>{option.name}</strong><span>{option.description}</span></label
          >
        {/each}
      </fieldset>
      <p>
        {ONBOARDING_COPY.PARAMETERS}: {(example.graph.parameters ?? [])
          .map((parameter) => `${parameter.name}: ${parameter.data.value}`)
          .join("; ")}
      </p>
      <button onclick={() => moveToStep(ONBOARDING_STEP.SETTINGS)}>{ONBOARDING_COPY.CONTINUE}</button>
    </div>
    <div hidden={step !== ONBOARDING_STEP.SETTINGS}>
      <LaunchForm
        {descriptor}
        onsubmit={review}
        busy={saving}
        serverIssues={inputIssues}
        submitLabel={ONBOARDING_COPY.REVIEW}
        showSelectionNotes={false}
        sectionDescription="Choose available markets and set the paper cash, order limits and simulated latency."
      />
      <button class="secondary" onclick={() => moveToStep(ONBOARDING_STEP.EXAMPLE)}>{ONBOARDING_COPY.BACK}</button>
    </div>
    <div hidden={step !== ONBOARDING_STEP.REVIEW}>
      <ReviewSettings {descriptor} {example} {inputs} />
      <div class="actions">
        <button onclick={savePrivateBot} disabled={saving || saveUncertain}
          >{saving ? ONBOARDING_COPY.SAVING : ONBOARDING_COPY.SAVE}</button
        >
        <button class="secondary" disabled={saving} onclick={() => moveToStep(ONBOARDING_STEP.SETTINGS)}
          >{ONBOARDING_COPY.BACK}</button
        >
      </div>
    </div>
  {/if}
  <p><a href={NAVIGATION_PATH.NEW_BOT}>{ONBOARDING_COPY.ADVANCED}</a></p>
</section>

<style>
  .guided-bot {
    max-width: 840px;
    margin: 0 auto;
    padding-block: 0;
  }
  .guided-bot > :global(.allowance) {
    margin-block: 24px;
  }
  .guided-bot > h2 {
    margin-bottom: 24px;
  }
  .guided-bot > p:last-child {
    margin-top: 24px;
  }
  .guided-bot > div > .secondary {
    margin-top: 16px;
  }
  fieldset {
    border: 0;
    padding: 0;
    display: grid;
    gap: 1rem;
    margin-bottom: 1.5rem;
  }
  label {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 0.4rem 0.75rem;
    padding: 16px;
    border: 1px solid var(--line);
    border-radius: var(--radius-control);
    background: var(--surface);
    cursor: pointer;
  }
  label:has(input:checked) {
    border-color: var(--accent);
  }
  label input {
    grid-row: 1 / 3;
    margin-top: 2px;
  }
  label span {
    grid-column: 2;
  }
  nav {
    margin-block: 24px;
  }
  ol {
    padding-left: 1.2rem;
    display: flex;
    flex-wrap: wrap;
    gap: 1rem 2rem;
  }
  [aria-current="step"] {
    font-weight: 700;
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem;
  }
  [hidden] {
    display: none;
  }
</style>
