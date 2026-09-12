<script lang="ts">
  import { resourceLimitDetail } from "$lib/limits/validation";
  import type { SelectionSource, SelectionSuggestion } from "./selectionSearch";
  import { Check, MagnifyingGlass, Plus, X } from "phosphor-svelte";
  import { untrack } from "svelte";

  let {
    source,
    value,
    onchange,
    labelId,
    descriptionId,
    invalid = false,
    disabled = false,
  }: {
    source: SelectionSource;
    value: string[];
    onchange: (values: string[]) => void;
    labelId: string;
    descriptionId?: string;
    invalid?: boolean;
    disabled?: boolean;
  } = $props();

  const limits = $derived(source.limits);
  const debounceMilliseconds = 300;
  const listId = $derived(`${labelId}-options`);
  let input: HTMLInputElement;
  let query = $state("");
  let open = $state(false);
  let loading = $state(false);
  let searched = $state(false);
  let searchError = $state("");
  let retry = $state(0);
  let results = $state<SelectionSuggestion[]>([]);
  let hasMore = $state(false);
  let activeIndex = $state(-1);
  let metadata = $state<Record<string, SelectionSuggestion>>({});
  let missingMetadataIds = $state<string[]>([]);
  let lookupError = $state(false);
  let lookupRetry = $state(0);
  const atLimit = $derived(value.length >= limits.maximumSelections);
  const selectedKey = $derived(JSON.stringify(value));

  $effect(() => {
    const text = query.trim();
    retry;
    results = [];
    activeIndex = -1;
    searched = false;
    searchError = "";
    hasMore = false;
    loading = text.length >= limits.minimumQueryLength;
    if (text.length < limits.minimumQueryLength) return;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const data = await source.search(text, controller.signal);
        if (controller.signal.aborted) return;
        results = data.items;
        hasMore = data.has_more;
        searched = true;
      } catch (caught) {
        if (!controller.signal.aborted) searchError = resourceLimitDetail(caught) ?? source.copy.SEARCH_ERROR;
      } finally {
        if (!controller.signal.aborted) loading = false;
      }
    }, debounceMilliseconds);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  });

  $effect(() => {
    const ids: string[] = JSON.parse(selectedKey);
    lookupRetry;
    const lookupIds = untrack(() => ids.filter((id) => !metadata[id]));
    lookupError = false;
    if (lookupIds.length === 0) return;
    const controller = new AbortController();
    void (async () => {
      try {
        const data = await source.lookup(lookupIds, controller.signal);
        if (controller.signal.aborted) return;
        metadata = {
          ...metadata,
          ...Object.fromEntries(data.map((item) => [item.id, item])),
        };
        missingMetadataIds = lookupIds.filter((id) => !data.some((item) => item.id === id));
      } catch {
        if (!controller.signal.aborted) lookupError = true;
      }
    })();
    return () => controller.abort();
  });

  function select(item: SelectionSuggestion): void {
    if (disabled || atLimit || value.includes(item.id)) return;
    metadata = { ...metadata, [item.id]: item };
    onchange([...value, item.id]);
    query = "";
    input.focus();
    // Close after focus so later pointer clicks cannot shift when suggestions blur away.
    open = false;
  }

  function onkeydown(event: KeyboardEvent): void {
    if (event.key === "Escape") {
      open = false;
      activeIndex = -1;
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      open = true;
      if (results.length) {
        activeIndex = wrappedSelectionIndex(event.key === "ArrowDown");
        document.getElementById(`${listId}-${activeIndex}`)?.scrollIntoView?.({ block: "nearest" });
      }
    } else if (event.key === "Enter") {
      // Enter chooses a suggestion; it must never submit the surrounding form.
      event.preventDefault();
      if (open && activeIndex >= 0 && results[activeIndex]) select(results[activeIndex]);
    }
  }

  function retrySearch(): void {
    // Keep focus on the stable input before the retry button disappears.
    input.focus();
    open = true;
    retry += 1;
  }

  function wrappedSelectionIndex(forward: boolean): number {
    if (activeIndex < 0) return forward ? 0 : results.length - 1;
    const direction = forward ? 1 : -1;
    return (activeIndex + direction + results.length) % results.length;
  }
</script>

<div
  class="item-selector"
  onfocusout={(event) => {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) open = false;
  }}
>
  <div class="search-field">
    <MagnifyingGlass size={19} aria-hidden="true" />
    <input
      id={`${labelId}-input`}
      bind:this={input}
      bind:value={query}
      role="combobox"
      aria-autocomplete="list"
      aria-expanded={open && !atLimit}
      aria-controls={listId}
      aria-activedescendant={open && activeIndex >= 0 ? `${listId}-${activeIndex}` : undefined}
      aria-labelledby={labelId}
      aria-describedby={descriptionId}
      aria-invalid={invalid}
      autocomplete="off"
      maxlength={limits.maximumQueryLength}
      placeholder={atLimit ? "Selection limit reached" : source.copy.PLACEHOLDER}
      disabled={disabled || atLimit}
      onfocus={() => (open = true)}
      oninput={() => (open = true)}
      {onkeydown}
    />
    {#if loading}<span class="search-spinner" aria-label="Searching"></span>{/if}
  </div>

  {#if open && !atLimit}
    <div class="suggestions">
      <div class="search-status" role="status" aria-live="polite">
        {#if searchError}
          <span>{searchError}</span>
          <button type="button" class="text-button" onclick={retrySearch}>{source.copy.RETRY_SEARCH}</button>
        {:else if loading}
          Searching Polymarket…
        {:else if query.trim().length < limits.minimumQueryLength}
          {source.copy.TYPE_HINT}
        {:else if searched && results.length === 0}
          {source.copy.NO_RESULTS}
        {:else if results.length}
          <span>{source.copy.RESULTS_LABEL}</span><span>{results.length} results</span>
        {/if}
      </div>
      <div
        id={listId}
        role="listbox"
        aria-multiselectable="true"
        aria-label={source.copy.RESULTS_LABEL}
        class="result-list"
      >
        {#each results as item, index (item.id)}
          {@const selected = value.includes(item.id)}
          {@const detail = item.detail}
          <button
            type="button"
            role="option"
            id={`${listId}-${index}`}
            aria-selected={selected}
            aria-disabled={selected || disabled}
            tabindex="-1"
            class:active={activeIndex === index}
            class:selected
            class="item-option"
            onmousedown={(event) => event.preventDefault()}
            onclick={() => select(item)}
          >
            <span class="option-copy">
              {#if item.subtitle && item.subtitle !== item.title}<span class="event-title">{item.subtitle}</span>{/if}
              <span class="question">{item.title}</span>
              <span class="item-detail"
                ><span class="id">{item.id}</span>{#if detail}<span>{detail}</span>{/if}</span
              >
            </span>
            <span class="option-action"
              >{#if selected}<Check size={17} /><span class="sr-only">Selected</span>{:else}<Plus
                  size={17}
                />{/if}</span
            >
          </button>
        {/each}
      </div>
      {#if hasMore}<p class="refine-hint">More matches available. Refine your search to narrow the list.</p>{/if}
    </div>
  {/if}

  {#if value.length}
    <div class="selection-heading">
      <span>{source.copy.SELECTED_LABEL}</span><span>{value.length} / {limits.maximumSelections}</span>
    </div>
    <ul class="selected-items" aria-label={source.copy.SELECTED_LABEL}>
      {#each value as id (id)}
        {@const item = metadata[id]}
        <li>
          <span class="selected-mark" aria-hidden="true"><Check size={15} /></span>
          <span class="selected-copy">
            <span class="question">{item?.title ?? id}</span>
            {#if item}<span class="id">{id}</span>{/if}
            {#if item && item.unavailable}<span class="unavailable">{source.copy.UNAVAILABLE}</span>
            {:else if missingMetadataIds.includes(id)}<span class="unavailable">{source.copy.MISSING}</span>{/if}
          </span>
          <button
            type="button"
            class="remove-item"
            aria-label={`Remove ${item?.title ?? id}`}
            {disabled}
            onclick={() => onchange(value.filter((item) => item !== id))}><X size={17} /></button
          >
        </li>
      {/each}
    </ul>
  {:else}
    <p class="selection-hint">{source.copy.SELECTION_HINT}</p>
  {/if}
  {#if lookupError}
    <p class="lookup-error" role="status">
      {source.copy.LOOKUP_ERROR}
      <button type="button" class="text-button" onclick={() => (lookupRetry += 1)}>{source.copy.RETRY_DETAILS}</button>
    </p>
  {/if}
</div>

<style>
  .item-selector {
    min-width: 0;
  }
  .search-field {
    position: relative;
    display: flex;
    align-items: center;
  }
  .search-field > :global(svg) {
    position: absolute;
    left: 15px;
    color: var(--text-muted);
    pointer-events: none;
  }
  .search-field input {
    width: 100%;
    padding-left: 44px;
    padding-right: 40px;
  }
  .search-spinner {
    position: absolute;
    right: 16px;
    width: 15px;
    height: 15px;
    border: 2px solid var(--line);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  .suggestions {
    margin-top: 8px;
    border: 1px solid var(--line);
    border-radius: var(--radius-surface);
    overflow: hidden;
    background: var(--surface-raised);
  }
  .search-status,
  .selection-heading {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    color: var(--text-muted);
    font-size: 0.75rem;
  }
  .search-status {
    padding: 12px 14px;
  }
  .result-list {
    max-height: 320px;
    overflow-y: auto;
    overscroll-behavior: contain;
  }
  .item-option {
    display: flex;
    width: 100%;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    text-align: left;
    white-space: normal;
    background: transparent;
    border: 0;
    border-top: 1px solid var(--line);
    border-radius: 0;
    padding: 14px;
    color: var(--text);
    box-shadow: none;
  }
  .item-option:hover,
  .item-option.active {
    background: var(--surface-input);
  }
  .item-option.selected {
    color: var(--accent);
  }
  .option-copy,
  .selected-copy {
    display: grid;
    gap: 5px;
    min-width: 0;
  }
  .event-title {
    font-size: 0.69rem;
    color: var(--text-muted);
    font-weight: 400;
  }
  .question {
    font-size: 0.84rem;
    line-height: 1.45;
    font-weight: 500;
    overflow-wrap: anywhere;
  }
  .item-detail {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 12px;
    color: var(--text-muted);
    font-size: 0.69rem;
    font-weight: 400;
  }
  .id {
    font-family: var(--font-mono, monospace);
    font-size: 0.68rem;
    color: var(--text-muted);
    overflow-wrap: anywhere;
  }
  .option-action {
    display: grid;
    place-items: center;
    flex-shrink: 0;
    width: 28px;
    height: 28px;
    border: 1px solid var(--line);
    border-radius: var(--radius-control);
  }
  .refine-hint,
  .selection-hint,
  .lookup-error {
    margin: 0;
    padding: 12px 0 0;
    font-size: 0.75rem;
    color: var(--text-muted);
    line-height: 1.5;
  }
  .refine-hint {
    padding: 10px 14px;
    border-top: 1px solid var(--line);
  }
  .selection-heading {
    margin: 18px 0 8px;
  }
  .selected-items {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 6px;
  }
  .selected-items li {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px;
    border: 1px solid var(--line);
    border-radius: var(--radius-control);
    background: var(--surface-input);
  }
  .selected-mark {
    color: var(--accent);
    display: flex;
    flex-shrink: 0;
  }
  .selected-copy {
    flex: 1;
  }
  .remove-item {
    display: grid;
    place-items: center;
    padding: 8px;
    min-height: 44px;
    min-width: 44px;
    background: transparent;
    color: var(--text-muted);
    border: 0;
    box-shadow: none;
  }
  .remove-item:hover {
    color: var(--danger);
    background: var(--surface-raised);
  }
  .unavailable {
    color: var(--danger);
    font-size: 0.72rem;
  }
  .text-button {
    padding: 0;
    min-height: auto;
    border: 0;
    background: transparent;
    color: var(--accent);
    text-decoration: underline;
    font-size: inherit;
    box-shadow: none;
  }
  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
  }
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .search-spinner {
      animation: none;
    }
  }
</style>
