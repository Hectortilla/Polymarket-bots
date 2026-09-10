<script lang="ts">
  import type { ChartSamplePayload, WalletChartPointPayload } from "$lib/api/generated";
  import { onMount } from "svelte";
  import "./dashboard.css";

  import { chartWindowPoints } from "./chartWindow";
  import {
    DASHBOARD_KEY,
    INITIAL_TIME_ZOOM_LEVEL,
    MAX_CHART_HISTORY_POINTS,
    MAX_TIME_ZOOM_LEVEL,
    MIN_TIME_ZOOM_LEVEL,
  } from "./contracts";
  import { DASHBOARD_COPY } from "./copy";
  import EquityChart from "./EquityChart.svelte";
  import MarketChart from "./MarketChart.svelte";
  import WalletChart from "./WalletChart.svelte";

  const BASE_WINDOW_POINTS = 180;
  const MIN_WINDOW_POINTS = 12;

  let {
    active = true,
    samples,
    walletTimelinePoints,
    configuredWallets = [],
    terminal = false,
  }: {
    active?: boolean;
    samples: ChartSamplePayload[];
    walletTimelinePoints: WalletChartPointPayload[];
    configuredWallets?: string[];
    terminal?: boolean;
  } = $props();
  let view = $state<"market" | "wallet">("market");
  let zoom = $state(INITIAL_TIME_ZOOM_LEVEL);
  let panel: HTMLElement;
  let panelInObservationRange = $state(false);
  let chartsActivated = $state(false);
  let renderedSamples = $state<ChartSamplePayload[]>([]);
  let renderedWalletTimelinePoints = $state<WalletChartPointPayload[]>([]);

  const windowPoints = $derived(
    chartWindowPoints(BASE_WINDOW_POINTS, zoom, MIN_WINDOW_POINTS, MAX_CHART_HISTORY_POINTS),
  );
  const chartSamples = $derived(renderedSamples.slice(-windowPoints));
  const chartTimeRangeMs = $derived.by(() => {
    const chartStartMs = chartSamples[0]?.sampled_at_ms ?? renderedWalletTimelinePoints[0]?.trade_timestamp_ms ?? 0;
    const chartEndMs =
      chartSamples.at(-1)?.sampled_at_ms ?? renderedWalletTimelinePoints.at(-1)?.trade_timestamp_ms ?? chartStartMs + 1;
    return [chartStartMs, Math.max(chartStartMs + 1, chartEndMs)] as const;
  });
  $effect(() => {
    if (!active || !panelInObservationRange) return;
    renderedSamples = samples;
    renderedWalletTimelinePoints = walletTimelinePoints;
  });

  onMount(() => {
    const keydown = (event: KeyboardEvent) => {
      if (!active) return;
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
      handleControl(event.key.toLowerCase());
    };
    window.addEventListener("keydown", keydown);
    const visibility = new IntersectionObserver(
      ([entry]) => {
        panelInObservationRange = entry?.isIntersecting ?? false;
        chartsActivated ||= panelInObservationRange;
      },
      { rootMargin: "200px 0px" },
    );
    visibility.observe(panel);
    return () => {
      window.removeEventListener("keydown", keydown);
      visibility.disconnect();
    };
  });

  function handleControl(key: string): void {
    if (key === DASHBOARD_KEY.closer) zoom = Math.max(MIN_TIME_ZOOM_LEVEL, zoom - 1);
    else if (key === DASHBOARD_KEY.wider) zoom = Math.min(MAX_TIME_ZOOM_LEVEL, zoom + 1);
    else if (key === DASHBOARD_KEY.reset) zoom = INITIAL_TIME_ZOOM_LEVEL;
    else if (key === DASHBOARD_KEY.view) {
      view = view === "market" ? "wallet" : "market";
    }
  }
</script>

<section bind:this={panel} class="dashboard-panel" aria-label={DASHBOARD_COPY.ARIA_LABEL}>
  <div class="dashboard-grid" data-layout="stacked">
    <section class="chart-section" aria-labelledby="equity-chart-heading">
      <div class="dashboard-toolbar">
        <div>
          <h2 id="equity-chart-heading">{DASHBOARD_COPY.EQUITY}</h2>
          <p class="chart-context">{terminal ? DASHBOARD_COPY.RUN_HISTORY : DASHBOARD_COPY.LIVE}</p>
        </div>
        <div class="dashboard-controls" aria-label={DASHBOARD_COPY.CONTROLS_ARIA_LABEL}>
          <button
            onclick={() => handleControl(DASHBOARD_KEY.closer)}
            disabled={zoom === MIN_TIME_ZOOM_LEVEL}
            title={`Keyboard: ${DASHBOARD_KEY.closer}`}>{DASHBOARD_KEY.closer} · {DASHBOARD_COPY.CONTROL_CLOSER}</button
          >
          <button
            onclick={() => handleControl(DASHBOARD_KEY.wider)}
            disabled={zoom === MAX_TIME_ZOOM_LEVEL}
            title={`Keyboard: ${DASHBOARD_KEY.wider}`}>{DASHBOARD_KEY.wider} · {DASHBOARD_COPY.CONTROL_WIDER}</button
          >
          <button
            onclick={() => handleControl(DASHBOARD_KEY.reset)}
            disabled={zoom === INITIAL_TIME_ZOOM_LEVEL}
            title={`Keyboard: ${DASHBOARD_KEY.reset}`}>{DASHBOARD_KEY.reset} · {DASHBOARD_COPY.CONTROL_RESET}</button
          >
        </div>
      </div>
      <div class="equity-chart">
        {#if !chartsActivated}
          <div class="skeleton chart-placeholder" aria-hidden="true"></div>
        {:else if chartSamples.length === 0}
          <p class="chart-empty">{terminal ? DASHBOARD_COPY.NO_SAMPLES : DASHBOARD_COPY.WAITING_FOR_SAMPLE}</p>
        {:else}
          <EquityChart samples={chartSamples} />
        {/if}
      </div>
    </section>
    <section class="chart-section" aria-labelledby="market-chart-heading">
      <div class="dashboard-toolbar">
        <h2 id="market-chart-heading">
          {view === "market" ? DASHBOARD_COPY.MARKET_PRICES : DASHBOARD_COPY.WALLET_ACTIVITY}
        </h2>
        <div class="dashboard-controls">
          <button
            class:active={view === "wallet"}
            onclick={() => handleControl(DASHBOARD_KEY.view)}
            title={`Keyboard: ${DASHBOARD_KEY.view}`}>{DASHBOARD_KEY.view} · {DASHBOARD_COPY.CONTROL_VIEW}</button
          >
        </div>
      </div>
      <div class="primary-chart">
        {#if !chartsActivated}
          <div class="skeleton chart-placeholder" aria-hidden="true"></div>
        {:else if chartSamples.length === 0 && renderedWalletTimelinePoints.length === 0 && configuredWallets.length === 0}
          <p class="chart-empty">{terminal ? DASHBOARD_COPY.NO_SAMPLES : DASHBOARD_COPY.WAITING_FOR_SAMPLE}</p>
        {:else if view === "market"}
          <MarketChart samples={chartSamples} />
        {:else}
          <WalletChart
            {active}
            points={renderedWalletTimelinePoints}
            {configuredWallets}
            startMs={chartTimeRangeMs[0]}
            endMs={chartTimeRangeMs[1]}
          />
        {/if}
      </div>
    </section>
  </div>
</section>
