<script module lang="ts">
  export const ADD_NODE_LABEL = 'Add node';
</script>

<script lang="ts">
  import { tick } from 'svelte';
  import ArrowsLeftRightIcon from 'phosphor-svelte/lib/ArrowsLeftRightIcon';
  import HashStraightIcon from 'phosphor-svelte/lib/HashStraightIcon';
  import LightningIcon from 'phosphor-svelte/lib/LightningIcon';
  import PlusIcon from 'phosphor-svelte/lib/PlusIcon';
  import ShoppingCartSimpleIcon from 'phosphor-svelte/lib/ShoppingCartSimpleIcon';
  import TagIcon from 'phosphor-svelte/lib/TagIcon';
  import TextTIcon from 'phosphor-svelte/lib/TextTIcon';
  import ToggleLeftIcon from 'phosphor-svelte/lib/ToggleLeftIcon';

  import type {
    GraphBrokerActionDescriptor,
    GraphComparisonDescriptor,
    GraphConstantDescriptor,
    GraphNodeCatalog,
    GraphTriggerDescriptor
  } from '$lib/api/generated';
  import { SIDE } from '$lib/charts/contracts';
  import {
    GRAPH_NODE_TYPE,
    triggerAlreadyExists,
    type CanvasNode
  } from './nodeGraph';
  import { GRAPH_SCALAR_TYPE } from './graphContracts';

  let {
    catalog,
    nodes,
    additionDisabled = false,
    onaddtrigger,
    onaddconstant,
    onaddcomparison,
    onaddaction
  }: {
    catalog: GraphNodeCatalog;
    nodes: CanvasNode[];
    additionDisabled?: boolean;
    onaddtrigger: (trigger: GraphTriggerDescriptor) => void;
    onaddconstant: (constant: GraphConstantDescriptor) => void;
    onaddcomparison: (comparison: GraphComparisonDescriptor) => void;
    onaddaction: (action: GraphBrokerActionDescriptor) => void;
  } = $props();

  type NodeCategory = (typeof GRAPH_NODE_TYPE)[keyof typeof GRAPH_NODE_TYPE];
  type PaletteIcon =
    | 'trigger'
    | 'boolean'
    | 'number'
    | 'string'
    | 'comparison'
    | 'buy'
    | 'sell';

  type PaletteItem = {
    id: string;
    category: NodeCategory;
    icon: PaletteIcon;
    name: string;
    description: string;
    meta: string;
    searchTerms: string;
    disabled: boolean;
    select: () => void;
  };

  const categories = [
    {
      id: GRAPH_NODE_TYPE.trigger,
      label: 'Triggers',
      description: 'Start a branch from a runtime event.'
    },
    {
      id: GRAPH_NODE_TYPE.constant,
      label: 'Values',
      description: 'Supply a typed value to another node.'
    },
    {
      id: GRAPH_NODE_TYPE.comparison,
      label: 'Logic',
      description: 'Compare compatible values.'
    },
    {
      id: GRAPH_NODE_TYPE.brokerAction,
      label: 'Actions',
      description: 'Submit a fixed-side paper order.'
    }
  ] as const satisfies ReadonlyArray<{
    id: NodeCategory;
    label: string;
    description: string;
  }>;

  let open = $state(false);
  let query = $state('');
  let searchInput = $state<HTMLInputElement>();

  function comparisonPaletteItems(
    comparisons: GraphComparisonDescriptor[]
  ): PaletteItem[] {
    const defaultComparison = comparisons[0];
    if (!defaultComparison) return [];
    const operatorCount = comparisons.length;

    return [
      {
        id: 'comparison',
        category: GRAPH_NODE_TYPE.comparison,
        icon: 'comparison',
        name: 'Comparison',
        description: 'Compare two compatible values with a selectable operator.',
        meta: `${operatorCount} ${operatorCount === 1 ? 'operator' : 'operators'}`,
        searchTerms: [
          'comparison',
          'logic',
          ...comparisons.flatMap((comparison) => [
            comparison.display_name,
            comparison.operator
          ])
        ].join(' '),
        disabled: false,
        select: () => onaddcomparison(defaultComparison)
      }
    ];
  }

  function constantIcon(constant: GraphConstantDescriptor): PaletteIcon {
    switch (constant.scalar_type) {
      case GRAPH_SCALAR_TYPE.boolean:
        return 'boolean';
      case GRAPH_SCALAR_TYPE.integer:
      case GRAPH_SCALAR_TYPE.decimal:
        return 'number';
      case GRAPH_SCALAR_TYPE.string:
        return 'string';
    }
  }

  function actionIcon(action: GraphBrokerActionDescriptor): PaletteIcon {
    switch (action.side) {
      case SIDE.buy:
        return 'buy';
      case SIDE.sell:
        return 'sell';
    }
  }

  const paletteItems = $derived<PaletteItem[]>([
    ...catalog.triggers.map((trigger) => ({
      id: `trigger-${trigger.hook_name}`,
      category: GRAPH_NODE_TYPE.trigger,
      icon: 'trigger' as const,
      name: trigger.hook_name,
      description: trigger.payload
        ? `Start with ${trigger.payload.type_name} data.`
        : 'Start from a bot lifecycle event.',
      meta: 'event',
      searchTerms: `${trigger.hook_name} ${trigger.payload?.type_name ?? ''}`,
      disabled: additionDisabled || triggerAlreadyExists(nodes, trigger),
      select: () => onaddtrigger(trigger)
    })),
    ...catalog.constants.map((constant) => ({
      id: `constant-${constant.scalar_type}`,
      category: GRAPH_NODE_TYPE.constant,
      icon: constantIcon(constant),
      name: constant.display_name,
      description: `Use ${constant.scalar_type} as an input value.`,
      meta: constant.scalar_type,
      searchTerms: `${constant.display_name} ${constant.scalar_type}`,
      disabled: additionDisabled,
      select: () => onaddconstant(constant)
    })),
    ...comparisonPaletteItems(catalog.comparisons).map((item) => ({
      ...item,
      disabled: additionDisabled || item.disabled
    })),
    ...catalog.broker_actions.map((action) => ({
      id: `action-${action.action}`,
      category: GRAPH_NODE_TYPE.brokerAction,
      icon: actionIcon(action),
      name: action.display_name,
      description: `Submit a ${action.side} order through Broker.${action.method_name}.`,
      meta: action.side,
      searchTerms: `${action.display_name} ${action.action} ${action.side} ${action.method_name}`,
      disabled: additionDisabled,
      select: () => onaddaction(action)
    }))
  ]);

  const normalizedQuery = $derived(query.trim().toLocaleLowerCase());
  const visibleGroups = $derived(
    categories
      .map((category) => ({
        ...category,
        items: paletteItems.filter(
          (item) =>
            item.category === category.id &&
            item.searchTerms.toLocaleLowerCase().includes(normalizedQuery)
        )
      }))
      .filter((category) => category.items.length > 0)
  );
  const visibleItemCount = $derived(
    visibleGroups.reduce((count, group) => count + group.items.length, 0)
  );

  $effect(() => {
    if (open) void tick().then(() => searchInput?.focus());
  });

  function togglePalette(): void {
    open = !open;
    if (!open) query = '';
  }

  function closePalette(): void {
    open = false;
    query = '';
  }

  function addItem(item: PaletteItem): void {
    if (item.disabled) return;
    item.select();
    closePalette();
  }

  function handleWindowKeydown(event: KeyboardEvent): void {
    if (open && event.key === 'Escape') closePalette();
  }
</script>

<svelte:window onkeydown={handleWindowKeydown} />

<div class="node-palette">
  <button
    type="button"
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
          <section class="palette-group" aria-labelledby={`palette-group-${group.id}`}>
            <header>
              <div>
                <h3 id={`palette-group-${group.id}`}>{group.label}</h3>
                <p>{group.description}</p>
              </div>
              <span>{group.items.length}</span>
            </header>

            <div class="palette-grid">
              {#each group.items as item (item.id)}
                <button
                  type="button"
                  class="palette-item"
                  aria-label={`Add ${item.name}`}
                  disabled={item.disabled}
                  onclick={() => addItem(item)}
                >
                  <span class="palette-icon" aria-hidden="true">
                    {#if item.icon === 'trigger'}
                      <LightningIcon aria-hidden="true" size={18} />
                    {:else if item.icon === 'boolean'}
                      <ToggleLeftIcon aria-hidden="true" size={18} />
                    {:else if item.icon === 'number'}
                      <HashStraightIcon aria-hidden="true" size={18} />
                    {:else if item.icon === 'string'}
                      <TextTIcon aria-hidden="true" size={18} />
                    {:else if item.icon === 'comparison'}
                      <ArrowsLeftRightIcon aria-hidden="true" size={18} />
                    {:else if item.icon === 'buy'}
                      <ShoppingCartSimpleIcon aria-hidden="true" size={18} />
                    {:else}
                      <TagIcon aria-hidden="true" size={18} />
                    {/if}
                  </span>
                  <span class="item-heading">
                    <strong>{item.name}</strong>
                    <small>{item.disabled ? 'On canvas' : item.meta}</small>
                  </span>
                  <span>{item.description}</span>
                </button>
              {/each}
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

  .palette-panel {
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
    color: var(--text-muted);
    font-family: 'Geist Mono Variable', ui-monospace, monospace;
    font-size: 0.68rem;
  }

  .palette-search input {
    grid-column: 1 / -1;
    min-height: 2.7rem;
    padding: 0.7rem 0.8rem;
    font-size: 0.88rem;
  }

  .palette-results {
    max-height: min(34rem, calc(100dvh - 12rem));
    overflow-y: auto;
    overscroll-behavior: contain;
    scrollbar-color: var(--control-line) transparent;
    scrollbar-width: thin;
  }

  .palette-group {
    margin: 0;
    padding: 1rem;
  }

  .palette-group + .palette-group {
    border-top: 1px solid var(--line);
  }

  .palette-group header {
    margin-bottom: 0.7rem;
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    align-items: start;
  }

  .palette-group h3,
  .palette-group p {
    margin: 0;
  }

  .palette-group h3 {
    font-size: 0.82rem;
    font-weight: 640;
    letter-spacing: -0.01em;
  }

  .palette-group p {
    margin-top: 0.15rem;
    color: var(--text-muted);
    font-size: 0.7rem;
    line-height: 1.4;
  }

  .palette-group header > span {
    color: var(--text-muted);
    font-family: 'Geist Mono Variable', ui-monospace, monospace;
    font-size: 0.68rem;
  }

  .palette-grid {
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
    font-family: 'Geist Mono Variable', ui-monospace, monospace;
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
    .palette-panel {
      right: -0.25rem;
      width: min(31rem, calc(100vw - 2rem));
    }

    .palette-grid {
      grid-template-columns: 1fr;
    }
  }

  @media (prefers-reduced-transparency: reduce) {
    .palette-panel {
      background: var(--surface-raised);
      backdrop-filter: none;
      -webkit-backdrop-filter: none;
    }
  }
</style>
