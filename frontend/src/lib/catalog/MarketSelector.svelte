<script lang="ts">
  import { untrack } from 'svelte';
  import { Check, MagnifyingGlass, Plus, X } from 'phosphor-svelte';
  import { lookupMarkets, searchMarkets, type MarketSuggestion } from '$lib/api/generated';
  import catalogContract from './catalogContract.fixture.json';

  let {
    value,
    onchange,
    labelId,
    descriptionId,
    invalid = false,
    disabled = false
  }: {
    value: string[];
    onchange: (slugs: string[]) => void;
    labelId: string;
    descriptionId?: string;
    invalid?: boolean;
    disabled?: boolean;
  } = $props();

  const limits = catalogContract.marketSearch;
  const debounceMilliseconds = 300;
  const listId = $derived(`${labelId}-options`);
  let input: HTMLInputElement;
  let query = $state('');
  let open = $state(false);
  let loading = $state(false);
  let searched = $state(false);
  let searchError = $state(false);
  let retry = $state(0);
  let results = $state<MarketSuggestion[]>([]);
  let hasMore = $state(false);
  let activeIndex = $state(-1);
  let metadata = $state<Record<string, MarketSuggestion>>({});
  let missing = $state<string[]>([]);
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
    searchError = false;
    hasMore = false;
    loading = text.length >= limits.minimumQueryLength;
    if (text.length < limits.minimumQueryLength) return;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const { data } = await searchMarkets({
          query: { q: text, limit: limits.defaultLimit },
          signal: controller.signal,
          throwOnError: true
        });
        if (controller.signal.aborted) return;
        results = data.markets;
        hasMore = data.has_more;
        searched = true;
      } catch {
        if (!controller.signal.aborted) searchError = true;
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
    const slugs: string[] = JSON.parse(selectedKey);
    lookupRetry;
    const unknown = untrack(() => slugs.filter((slug) => !metadata[slug]));
    lookupError = false;
    if (unknown.length === 0) return;
    const controller = new AbortController();
    void (async () => {
      try {
        const { data } = await lookupMarkets({
          body: { slugs: unknown }, signal: controller.signal, throwOnError: true
        });
        if (controller.signal.aborted) return;
        metadata = { ...metadata, ...Object.fromEntries(data.map((market) => [market.slug, market])) };
        missing = unknown.filter((slug) => !data.some((market) => market.slug === slug));
      } catch {
        if (!controller.signal.aborted) lookupError = true;
      }
    })();
    return () => controller.abort();
  });

  function select(market: MarketSuggestion): void {
    if (disabled || atLimit || value.includes(market.slug)) return;
    metadata = { ...metadata, [market.slug]: market };
    onchange([...value, market.slug]);
    query = '';
    input.focus();
  }

  function onkeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      open = false;
      activeIndex = -1;
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      open = true;
      if (results.length) {
        const next = event.key === 'ArrowDown';
        activeIndex = activeIndex < 0
          ? (next ? 0 : results.length - 1)
          : (activeIndex + (next ? 1 : -1) + results.length) % results.length;
        document.getElementById(`${listId}-${activeIndex}`)?.scrollIntoView?.({ block: 'nearest' });
      }
    } else if (event.key === 'Enter') {
      // Enter chooses a suggestion; it must never submit the surrounding form.
      event.preventDefault();
      if (open && activeIndex >= 0 && results[activeIndex]) select(results[activeIndex]);
    }
  }

  function closingDate(value: string | null): string | null {
    return value ? new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric' }).format(new Date(value)) : null;
  }
</script>

<div class="market-selector" onfocusout={(event) => {
  if (!event.currentTarget.contains(event.relatedTarget as Node | null)) open = false;
}}>
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
      placeholder={atLimit ? 'Selection limit reached' : 'Search markets by name or topic…'}
      disabled={disabled || atLimit}
      onfocus={() => open = true}
      oninput={() => open = true}
      {onkeydown}
    />
    {#if loading}<span class="search-spinner" aria-label="Searching"></span>{/if}
  </div>

  {#if open && !atLimit}
    <div class="suggestions">
      <div class="search-status" role="status" aria-live="polite">
        {#if searchError}
          <span>Search is unavailable. Please try again.</span>
          <button type="button" class="text-button" onclick={() => retry += 1}>Retry search</button>
        {:else if loading}
          Searching Polymarket…
        {:else if query.trim().length < limits.minimumQueryLength}
          Type at least {limits.minimumQueryLength} characters to find a market.
        {:else if searched && results.length === 0}
          No available markets found. Try a different name or topic.
        {:else if results.length}
          <span>Available markets</span><span>{results.length} results</span>
        {/if}
      </div>
      <div id={listId} role="listbox" aria-multiselectable="true" aria-label="Market search results" class="result-list">
        {#each results as market, index (market.slug)}
          {@const selected = value.includes(market.slug)}
          {@const endDate = closingDate(market.end_date)}
          <button
            type="button"
            role="option"
            id={`${listId}-${index}`}
            aria-selected={selected}
            aria-disabled={selected || disabled}
            tabindex="-1"
            class:active={activeIndex === index}
            class:selected
            class="market-option"
            onmousedown={(event) => event.preventDefault()}
            onclick={() => select(market)}
          >
            <span class="option-copy">
              {#if market.event_title && market.event_title !== market.question}<span class="event-title">{market.event_title}</span>{/if}
              <span class="question">{market.question}</span>
              <span class="market-detail"><span class="slug">{market.slug}</span>{#if endDate}<span>Ends {endDate}</span>{/if}</span>
            </span>
            <span class="option-action">{#if selected}<Check size={17} /><span class="sr-only">Selected</span>{:else}<Plus size={17} />{/if}</span>
          </button>
        {/each}
      </div>
      {#if hasMore}<p class="refine-hint">More matches available. Refine your search to narrow the list.</p>{/if}
    </div>
  {/if}

  {#if value.length}
    <div class="selection-heading"><span>Selected markets</span><span>{value.length} / {limits.maximumSelections}</span></div>
    <ul class="selected-markets" aria-label="Selected markets">
      {#each value as slug (slug)}
        {@const market = metadata[slug]}
        <li>
          <span class="selected-mark" aria-hidden="true"><Check size={15} /></span>
          <span class="selected-copy">
            <span class="question">{market?.question ?? slug}</span>
            {#if market}<span class="slug">{slug}</span>{/if}
            {#if market && !market.is_open_for_trading}<span class="unavailable">No longer available for trading</span>
            {:else if missing.includes(slug)}<span class="unavailable">Market not found — remove or replace this selection</span>{/if}
          </span>
          <button type="button" class="remove-market" aria-label={`Remove ${market?.question ?? slug}`} {disabled} onclick={() => onchange(value.filter((item) => item !== slug))}><X size={17} /></button>
        </li>
      {/each}
    </ul>
  {:else}
    <p class="selection-hint">Choose one or more markets. You can keep searching to add more.</p>
  {/if}
  {#if lookupError}
    <p class="lookup-error" role="status">Selected market details could not be loaded. Your selections are preserved. <button type="button" class="text-button" onclick={() => lookupRetry += 1}>Retry details</button></p>
  {/if}
</div>

<style>
  .market-selector { min-width: 0; }
  .search-field { position: relative; display: flex; align-items: center; }
  .search-field > :global(svg) { position: absolute; left: 15px; color: var(--text-muted); pointer-events: none; }
  .search-field input { width: 100%; padding-left: 44px; padding-right: 40px; }
  .search-spinner { position: absolute; right: 16px; width: 15px; height: 15px; border: 2px solid var(--line); border-top-color: var(--accent); border-radius: 50%; animation: spin .8s linear infinite; }
  .suggestions { margin-top: 8px; border: 1px solid var(--line); border-radius: 10px; overflow: hidden; background: var(--surface-raised); }
  .search-status, .selection-heading { display: flex; justify-content: space-between; align-items: center; gap: 12px; color: var(--text-muted); font-size: .75rem; }
  .search-status { padding: 12px 14px; }
  .result-list { max-height: 320px; overflow-y: auto; overscroll-behavior: contain; }
  .market-option { display: flex; width: 100%; align-items: center; justify-content: space-between; gap: 16px; text-align: left; background: transparent; border: 0; border-top: 1px solid var(--line); border-radius: 0; padding: 14px; color: var(--text); box-shadow: none; }
  .market-option:hover, .market-option.active { background: var(--surface-input); }
  .market-option.selected { color: var(--accent); }
  .option-copy, .selected-copy { display: grid; gap: 5px; min-width: 0; }
  .event-title { font-size: .69rem; color: var(--text-muted); font-weight: 400; }
  .question { font-size: .84rem; line-height: 1.45; font-weight: 500; overflow-wrap: anywhere; }
  .market-detail { display: flex; flex-wrap: wrap; gap: 4px 12px; color: var(--text-muted); font-size: .69rem; font-weight: 400; }
  .slug { font-family: var(--font-mono, monospace); font-size: .68rem; color: var(--text-muted); overflow-wrap: anywhere; }
  .option-action { display: grid; place-items: center; flex-shrink: 0; width: 28px; height: 28px; border: 1px solid var(--line); border-radius: 7px; }
  .refine-hint, .selection-hint, .lookup-error { margin: 0; padding: 12px 0 0; font-size: .75rem; color: var(--text-muted); line-height: 1.5; }
  .refine-hint { padding: 10px 14px; border-top: 1px solid var(--line); }
  .selection-heading { margin: 18px 0 8px; }
  .selected-markets { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
  .selected-markets li { display: flex; align-items: center; gap: 12px; padding: 12px; border: 1px solid var(--line); border-radius: 9px; background: var(--surface-input); }
  .selected-mark { color: var(--accent); display: flex; flex-shrink: 0; }
  .selected-copy { flex: 1; }
  .remove-market { display: grid; place-items: center; padding: 8px; min-height: 34px; background: transparent; color: var(--text-muted); border: 0; box-shadow: none; }
  .remove-market:hover { color: var(--danger); background: var(--surface-raised); }
  .unavailable { color: var(--danger); font-size: .72rem; }
  .text-button { padding: 0; min-height: auto; border: 0; background: transparent; color: var(--accent); text-decoration: underline; font-size: inherit; box-shadow: none; }
  .sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
  @keyframes spin { to { transform: rotate(360deg); } }
  @media (prefers-reduced-motion: reduce) { .search-spinner { animation: none; } }
</style>
