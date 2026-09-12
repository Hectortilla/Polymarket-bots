<script module lang="ts">
  export const ADD_NODE_LABEL = "Add node";
</script>

<script lang="ts">
  import { paletteItems, type PaletteItem } from "./nodePalette/items";
  import { visiblePaletteGroups, operationGroups } from "./nodePalette/grouping";

  import CaretRightIcon from "phosphor-svelte/lib/CaretRightIcon";
  import { tick } from "svelte";
  import ArrowsLeftRightIcon from "phosphor-svelte/lib/ArrowsLeftRightIcon";
  import HashStraightIcon from "phosphor-svelte/lib/HashStraightIcon";
  import LightningIcon from "phosphor-svelte/lib/LightningIcon";
  import PlusIcon from "phosphor-svelte/lib/PlusIcon";
  import ShoppingCartSimpleIcon from "phosphor-svelte/lib/ShoppingCartSimpleIcon";
  import TagIcon from "phosphor-svelte/lib/TagIcon";
  import TextTIcon from "phosphor-svelte/lib/TextTIcon";
  import ToggleLeftIcon from "phosphor-svelte/lib/ToggleLeftIcon";

  import type {
    GraphOperationDescriptor,
    GraphParameter,
    GraphBrokerActionDescriptor,
    GraphComparisonDescriptor,
    GraphConstantDescriptor,
    GraphNodeCatalog,
    GraphTriggerDescriptor,
  } from "$lib/api/generated";
  import { GRAPH_NODE_TYPE } from "$lib/catalog/graphContracts";
  import { type CanvasNode } from "$lib/catalog/nodeGraph/contracts";

  let {
    catalog,
    nodes,
    additionDisabled = false,
    onaddtrigger,
    onaddconstant,
    onaddcomparison,
    onaddaction,
    onaddoperation,
    onaddparameter,
    parameters = [],
  }: {
    catalog: GraphNodeCatalog;
    parameters?: GraphParameter[];
    onaddoperation: (operation: GraphOperationDescriptor) => void;
    onaddparameter: (parameter: GraphParameter) => void;
    nodes: CanvasNode[];
    additionDisabled?: boolean;
    onaddtrigger: (trigger: GraphTriggerDescriptor) => void;
    onaddconstant: (constant: GraphConstantDescriptor) => void;
    onaddcomparison: (comparison: GraphComparisonDescriptor) => void;
    onaddaction: (action: GraphBrokerActionDescriptor) => void;
  } = $props();

  let open = $state(false);
  let query = $state("");
  let expandedGroups = $state<Record<string, boolean>>({ [GRAPH_NODE_TYPE.operation]: true });
  let searchExpansion = $state<Record<string, boolean>>({});
  let searchInput = $state<HTMLInputElement>();
  let triggerButton = $state<HTMLButtonElement>();
  let opensAbove = $state(false);
  let panelMaxHeight = $state(544);

  const items = $derived(
    paletteItems(catalog, nodes, parameters, additionDisabled, {
      onaddoperation,
      onaddparameter,
      onaddtrigger,
      onaddconstant,
      onaddcomparison,
      onaddaction,
    }),
  );

  const normalizedQuery = $derived(query.trim().toLocaleLowerCase());
  const visibleGroups = $derived(visiblePaletteGroups(items, normalizedQuery));
  function groupIsExpanded(id: string): boolean {
    return normalizedQuery ? (searchExpansion[id] ?? true) : (expandedGroups[id] ?? false);
  }

  function toggleGroup(id: string): void {
    const expanded = !groupIsExpanded(id);
    if (normalizedQuery) searchExpansion = { ...searchExpansion, [id]: expanded };
    else expandedGroups = { ...expandedGroups, [id]: expanded };
  }

  $effect(() => {
    normalizedQuery;
    searchExpansion = {};
  });

  const visibleItemCount = $derived(visibleGroups.reduce((count, group) => count + group.items.length, 0));

  $effect(() => {
    if (open)
      void tick().then(() => {
        positionPanel();
        searchInput?.focus();
      });
  });

  function positionPanel(): void {
    if (!open || !triggerButton) return;
    const rect = triggerButton.getBoundingClientRect();
    const above = rect.top - 16;
    const below = window.innerHeight - rect.bottom - 16;
    opensAbove = below < 320 && above > below;
    panelMaxHeight = Math.max(180, opensAbove ? above : below);
  }

  function togglePalette(): void {
    open = !open;
    if (!open) query = "";
  }

  function closePalette(): void {
    open = false;
    query = "";
    triggerButton?.focus();
  }

  function addItem(item: PaletteItem): void {
    if (item.disabled) return;
    item.select();
    closePalette();
  }

  function handleWindowKeydown(event: KeyboardEvent): void {
    if (open && event.key === "Escape") closePalette();
  }
</script>

{#snippet itemGrid(items: PaletteItem[])}
  <div class="palette-grid">
    {#each items as item (item.id)}
      <button
        type="button"
        class="palette-item"
        aria-label={`Add ${item.name}`}
        disabled={item.disabled}
        onclick={() => addItem(item)}
      >
        <span class="palette-icon" aria-hidden="true">
          {#if item.icon === "trigger"}
            <LightningIcon aria-hidden="true" size={18} />
          {:else if item.icon === "boolean"}
            <ToggleLeftIcon aria-hidden="true" size={18} />
          {:else if item.icon === "number"}
            <HashStraightIcon aria-hidden="true" size={18} />
          {:else if item.icon === "string"}
            <TextTIcon aria-hidden="true" size={18} />
          {:else if item.icon === "comparison"}
            <ArrowsLeftRightIcon aria-hidden="true" size={18} />
          {:else if item.icon === "buy"}
            <ShoppingCartSimpleIcon aria-hidden="true" size={18} />
          {:else}
            <TagIcon aria-hidden="true" size={18} />
          {/if}
        </span>
        <span class="item-heading">
          <strong>{item.name}</strong>
          <small>{item.disabled ? "On canvas" : item.meta}</small>
        </span>
        <span>{item.description}</span>
      </button>
    {/each}
  </div>
{/snippet}

<svelte:window onkeydown={handleWindowKeydown} onresize={positionPanel} onscroll={positionPanel} />

<div class="node-palette">
  <button
    type="button"
    bind:this={triggerButton}
    class="palette-trigger"
    aria-label={ADD_NODE_LABEL}
    aria-expanded={open}
    aria-controls="node-palette-panel"
    onclick={togglePalette}
  >
    <PlusIcon aria-hidden="true" size={15} weight="bold" />
    <span>{ADD_NODE_LABEL}</span>
  </button>

  {#if open}
    <div
      class="palette-panel"
      class:above={opensAbove}
      style:max-height={`${panelMaxHeight}px`}
      id="node-palette-panel"
      role="dialog"
      aria-label="Add graph node"
    >
      <div class="palette-search">
        <label for="node-palette-search">Find a node</label>
        <input
          bind:this={searchInput}
          bind:value={query}
          id="node-palette-search"
          type="search"
          placeholder="Search triggers, values, logic, and actions"
          autocomplete="off"
        />
        <span aria-live="polite">{visibleItemCount} available</span>
      </div>

      <div class="palette-results">
        {#each visibleGroups as group (group.id)}
          <section class="palette-group">
            <button
              type="button"
              class="group-toggle"
              aria-label={group.label}
              aria-expanded={groupIsExpanded(group.id)}
              aria-controls={`palette-items-${group.id}`}
              onclick={() => toggleGroup(group.id)}
            >
              <span class="group-chevron" class:expanded={groupIsExpanded(group.id)}
                ><CaretRightIcon size={14} aria-hidden="true" /></span
              >
              <span class="group-heading"><strong>{group.label}</strong><small>{group.description}</small></span>
              <span class="group-count">{group.items.length}</span>
            </button>
            <div id={`palette-items-${group.id}`} hidden={!groupIsExpanded(group.id)}>
              {#if group.id === GRAPH_NODE_TYPE.operation}
                {#each operationGroups(group.items) as subgroup (subgroup.id)}
                  <section class="palette-subgroup">
                    <button
                      type="button"
                      class="group-toggle subgroup-toggle"
                      aria-label={subgroup.label}
                      aria-expanded={groupIsExpanded(subgroup.id)}
                      aria-controls={`palette-items-${subgroup.id}`}
                      onclick={() => toggleGroup(subgroup.id)}
                    >
                      <span class="group-chevron" class:expanded={groupIsExpanded(subgroup.id)}
                        ><CaretRightIcon size={13} aria-hidden="true" /></span
                      >
                      <strong>{subgroup.label}</strong><span class="group-count">{subgroup.items.length}</span>
                    </button>
                    <div id={`palette-items-${subgroup.id}`} hidden={!groupIsExpanded(subgroup.id)}>
                      {@render itemGrid(subgroup.items)}
                    </div>
                  </section>
                {/each}
              {:else}
                {@render itemGrid(group.items)}
              {/if}
            </div>
          </section>
        {:else}
          <div class="palette-empty">
            <strong>No matching nodes</strong>
            <p>Try a node name, data type, operator, or action.</p>
          </div>
        {/each}
      </div>
    </div>
  {/if}
</div>

<style>
  .node-palette {
    position: relative;
  }

  .palette-trigger {
    width: auto;
    min-height: 2.4rem;
    padding: 0.55rem 0.85rem;
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    font-size: 0.8rem;
  }

  .palette-panel.above {
    top: auto;
    bottom: calc(100% + 0.65rem);
  }

  .palette-panel {
    display: flex;
    flex-direction: column;
    position: absolute;
    top: calc(100% + 0.65rem);
    right: 0;
    z-index: 2;
    width: min(40rem, calc(100vw - 3rem));
    overflow: hidden;
    border: 1px solid var(--line-strong);
    border-radius: var(--radius-surface);
    background: color-mix(in srgb, var(--surface-raised) 96%, transparent);
    box-shadow: 0 1.5rem 4rem rgb(2 6 4 / 0.48);
    backdrop-filter: blur(16px) saturate(120%);
    -webkit-backdrop-filter: blur(16px) saturate(120%);
  }

  .palette-search {
    flex: none;
    position: relative;
    border-bottom: 1px solid var(--line);
    padding: 1rem;
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 0.45rem 1rem;
    align-items: center;
  }

  .palette-search label {
    color: var(--text-soft);
    font-size: 0.76rem;
    font-weight: 620;
  }

  .palette-search > span {
    grid-column: 2;
    grid-row: 1;
    color: var(--text-muted);
    font-family: "Geist Mono Variable", ui-monospace, monospace;
    font-size: 0.68rem;
  }

  .palette-search input {
    grid-column: 1 / -1;
    min-height: 2.7rem;
    padding: 0.7rem 0.8rem;
    font-size: 0.88rem;
  }

  .palette-results {
    min-height: 0;
    max-height: 34rem;
    overflow-y: auto;
    overscroll-behavior: contain;
    scrollbar-color: var(--control-line) transparent;
    scrollbar-width: thin;
  }

  .palette-group {
    margin: 0;
    padding: 0.35rem 0.75rem;
  }
  .palette-group + .palette-group {
    border-top: 1px solid var(--line);
  }
  .group-toggle {
    width: 100%;
    padding: 0.8rem 0.35rem;
    display: flex;
    gap: 0.65rem;
    align-items: center;
    justify-content: flex-start;
    border: 0;
    background: transparent;
    color: var(--text-soft);
    text-align: left;
    white-space: normal;
  }
  .group-toggle:hover {
    background: var(--surface-input);
    color: var(--text);
  }
  .group-heading {
    display: grid;
    gap: 0.3rem;
  }
  .group-toggle strong {
    font-size: 0.82rem;
    font-weight: 640;
  }
  .group-heading small {
    color: var(--text-muted);
    font-size: 0.7rem;
    font-weight: 400;
    line-height: 1.5;
  }
  .group-count {
    margin-left: auto;
    color: var(--text-muted);
    font-size: 0.7rem;
  }
  .group-chevron {
    display: inline-flex;
    flex: none;
    transition: transform var(--transition);
  }
  .group-chevron.expanded {
    transform: rotate(90deg);
  }
  .palette-subgroup {
    margin: 0 0 0.2rem 0.6rem;
    border-left: 1px solid var(--line);
    padding-left: 0.65rem;
  }
  .subgroup-toggle {
    padding: 0.65rem 0.35rem;
    min-height: 2.5rem;
  }
  .subgroup-toggle strong {
    font-size: 0.76rem;
  }
  [hidden] {
    display: none !important;
  }

  .palette-grid {
    padding: 0.25rem 0 0.85rem;
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.5rem;
  }

  .palette-item {
    width: 100%;
    min-height: 4.9rem;
    border-color: var(--line);
    padding: 0.55rem 0.7rem 0.55rem 0.55rem;
    display: grid;
    grid-template-columns: 2.35rem minmax(0, 1fr);
    gap: 0.3rem 0.7rem;
    align-content: start;
    justify-items: stretch;
    color: var(--text-soft);
    background: var(--surface-input);
    text-align: left;
    white-space: normal;
  }

  .palette-item:hover {
    border-color: var(--control-line-hover);
    color: var(--text);
    background: color-mix(in srgb, var(--accent) 4%, var(--surface-input));
  }

  .palette-item:disabled {
    border-color: var(--line);
    color: var(--text-muted);
    background: transparent;
    opacity: 0.58;
  }

  .palette-icon {
    grid-row: 1 / span 2;
    min-height: 3.75rem;
    border-right: 1px solid var(--line);
    display: grid;
    place-items: center;
    color: var(--text-muted);
    transition: color var(--transition);
  }

  .palette-item:hover .palette-icon {
    color: var(--accent);
  }

  .item-heading {
    grid-column: 2;
    display: flex;
    justify-content: space-between;
    gap: 0.75rem;
    align-items: baseline;
  }

  .item-heading strong,
  .item-heading small {
    font-family: "Geist Mono Variable", ui-monospace, monospace;
  }

  .item-heading strong {
    min-width: 0;
    overflow: hidden;
    color: var(--text);
    font-size: 0.74rem;
    font-weight: 620;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .item-heading small {
    flex: none;
    color: var(--text-muted);
    font-size: 0.62rem;
    font-weight: 520;
    text-transform: lowercase;
  }

  .palette-item > span:last-child {
    grid-column: 2;
    color: var(--text-muted);
    font-size: 0.69rem;
    font-weight: 430;
    line-height: 1.35;
  }

  .palette-empty {
    min-height: 12rem;
    padding: 2rem;
    display: grid;
    place-content: center;
    text-align: center;
  }

  .palette-empty strong {
    color: var(--text-soft);
    font-size: 0.86rem;
  }

  .palette-empty p {
    max-width: 28ch;
    margin: 0.35rem 0 0;
    font-size: 0.74rem;
  }

  @media (max-width: 560px) {
    .palette-panel.above {
      top: auto;
      bottom: calc(100% + 0.65rem);
    }

    .palette-panel {
      display: flex;
      flex-direction: column;
      right: -0.25rem;
      width: min(31rem, calc(100vw - 2rem));
    }

    .palette-grid {
      padding: 0.25rem 0 0.85rem;
      grid-template-columns: 1fr;
    }
  }

  @media (prefers-reduced-transparency: reduce) {
    .palette-panel.above {
      top: auto;
      bottom: calc(100% + 0.65rem);
    }

    .palette-panel {
      display: flex;
      flex-direction: column;
      background: var(--surface-raised);
      backdrop-filter: none;
      -webkit-backdrop-filter: none;
    }
  }
</style>
