<script lang="ts">
  import { FORM_COPY } from "$lib/formCopy";
  import { SERVICE_NAME } from "$lib/serviceIdentity";
  import { onMount, tick } from "svelte";
  import { goto } from "$app/navigation";
  import { listBotDefinitionsApiV1BotDefinitionsGet, type GraphExample } from "$lib/api/generated";
  import { hasGraphCapability, type GraphCapableDefinition } from "$lib/catalog/graphContracts";
  import LaunchForm from "$lib/catalog/LaunchForm.svelte";
  import { type LaunchInputs, type LaunchValidationIssue } from "$lib/catalog/schema/contracts";
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
  <header class="setup-heading">
    <h1>{ONBOARDING_COPY.START}</h1>
    <p>{ONBOARDING_COPY.PAPER_ONLY}</p>
  </header>
  <AccountUsage />
  <p><a href={contract.accountManagement.accountPath}>{ONBOARDING_COPY.VERIFY}</a></p>
  {#if loading}<div class="setup-loading" role="status">
      <p>{ONBOARDING_COPY.LOADING}</p>
      <div class="skeleton"></div>
      <div class="skeleton"></div>
    </div>
  {:else if !descriptor || !example}
    <p role="alert">{error || ONBOARDING_COPY.LOAD_ERROR}</p>
    <button onclick={loadOnboardingExamples}>{FORM_COPY.TRY_AGAIN}</button>
  {:else}
    <nav aria-label="Setup progress">
      <ol>
        {#each Object.values(ONBOARDING_STEP) as item}
          <li aria-current={step === item ? "step" : undefined}>{ONBOARDING_STEP_LABEL[item]}</li>
        {/each}
      </ol>
    </nav>
    <div class="setup-content">
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
    </div>
  {/if}
  <p class="setup-footer"><a href={NAVIGATION_PATH.NEW_BOT}>{ONBOARDING_COPY.ADVANCED}</a></p>
</section>

<style>
  .guided-bot {
    max-width: 960px;
    margin: 0 auto;
    font-size: 0.875rem;
  }
  .back-link {
    margin-bottom: 20px;
    font-size: 0.8125rem;
  }
  .setup-heading {
    margin-bottom: 24px;
  }
  h1 {
    font-size: clamp(1.5rem, 2.4vw, 1.75rem);
    margin: 0 0 10px;
    letter-spacing: -0.035em;
  }
  .setup-heading p {
    max-width: 65ch;
    margin: 0;
    color: var(--text-soft);
  }
  .guided-bot > :global(.allowance) {
    margin-bottom: 12px;
  }
  .guided-bot > p {
    font-size: 0.8125rem;
  }
  .setup-content {
    padding: 24px;
    border: 1px solid var(--line);
    border-top: 0;
    border-radius: 0 0 var(--radius-surface) var(--radius-surface);
  }
  h2 {
    font-size: 1rem;
    margin-bottom: 20px;
  }
  .setup-content :global(h3) {
    font-size: 0.9375rem;
  }
  .setup-content :global(p) {
    color: var(--text-soft);
  }
  .setup-content > div > .secondary {
    margin-top: 16px;
  }
  .setup-content :global(button),
  .setup-content :global(.primary-link) {
    font-size: 0.8125rem;
  }
  .setup-content :global(.configuration-section) {
    border-top: 0;
    padding-top: 0;
  }
  .setup-content :global(.form-grid) {
    gap: 20px;
  }
  .setup-content :global(input:not([type="checkbox"]):not([type="radio"])) {
    min-height: 44px;
    padding-block: 10px;
    font-size: 0.875rem;
  }
  fieldset {
    border: 0;
    padding: 0;
    display: grid;
    gap: 8px;
    margin: 0 0 16px;
  }
  label {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    gap: 4px 12px;
    padding: 16px;
    border: 1px solid var(--line-strong);
    border-radius: var(--radius-control);
    background: var(--surface);
    cursor: pointer;
  }
  label:hover {
    border-color: var(--control-line);
  }
  label:has(input:checked) {
    border-color: var(--accent);
    background: var(--surface-raised);
  }
  label:has(input:focus-visible) {
    outline: 2px solid var(--accent);
    outline-offset: 3px;
  }
  label input {
    grid-row: 1 / 3;
    margin-top: 2px;
  }
  label strong {
    font-weight: 600;
    color: var(--text);
  }
  label span {
    grid-column: 2;
    line-height: 1.6;
    color: var(--text-soft);
  }
  nav {
    margin-top: 24px;
    border: 1px solid var(--line);
    border-radius: var(--radius-surface) var(--radius-surface) 0 0;
    background: var(--surface);
  }
  ol {
    padding: 0;
    margin: 0;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    list-style: none;
  }
  li {
    padding: 16px;
    color: var(--text-muted);
    font-size: 0.8125rem;
    text-align: center;
  }
  li + li {
    border-left: 1px solid var(--line);
  }
  [aria-current="step"] {
    color: var(--text);
    font-weight: 600;
    box-shadow: inset 0 -2px var(--accent);
    background: var(--surface-raised);
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 24px;
  }
  .setup-footer {
    margin-top: 20px;
  }
  .setup-loading {
    padding-block: 24px;
    display: grid;
    gap: 12px;
  }
  .setup-loading .skeleton {
    height: 76px;
  }
  [hidden] {
    display: none;
  }
  @media (max-width: 767px) {
    .setup-content {
      padding: 20px 16px;
    }
    .setup-content :global(input:not([type="checkbox"]):not([type="radio"])) {
      font-size: 1rem;
    }
    ol {
      grid-template-columns: minmax(0, 1fr);
    }
    li {
      text-align: left;
      padding: 12px 16px;
    }
    li + li {
      border-left: 0;
      border-top: 1px solid var(--line);
    }
    [aria-current="step"] {
      box-shadow: inset 2px 0 var(--accent);
    }
    .actions {
      flex-direction: column;
    }
  }
</style>
