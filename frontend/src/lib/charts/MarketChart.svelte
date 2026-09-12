<script module lang="ts">
  import { DASHBOARD_COPY } from "./copy";
  import type { ChartSamplePayload, MarketChartPointPayload } from "$lib/api/generated";
  import { SIDE } from "$lib/sides";
  import { MAX_CHART_TOKENS, OUTCOME_PRICE_CEILING, OUTCOME_PRICE_FLOOR, VALUATION_STATUS } from "./contracts";
  import type { EChartsCoreOption } from "./echarts";
  import { CHART_COLORS, PRICE_CHART_GRID, TIME_AXIS, VALUE_AXIS, priceChartTooltip } from "./appearance";

  const MARKET_SERIES_PALETTE = [
    "#57d3ff",
    "#cf84ff",
    "#f6c453",
    "#72df98",
    "#6fa8ff",
    "#ff847c",
    "#63e0d5",
    "#d8dedb",
    "#ff9e64",
    "#ad7cff",
    "#f57fb3",
    "#47b9a8",
    "#8bde64",
    "#edca58",
    "#fb7870",
    "#8c7dff",
    "#35ccd7",
    "#ff986f",
    "#55de82",
    "#bfc5c2",
  ];

  export function marketChartOption(
    samples: ChartSamplePayload[],
    hiddenTokens: ReadonlySet<string> = new Set(),
  ): EChartsCoreOption {
    const marketSeries = recentMarketSeries(samples);
    const pointsByToken = new Map(
      marketSeries.map(({ token_id }) => [token_id, Array<MarketChartPointPayload | undefined>(samples.length)]),
    );
    samples.forEach((sample, sampleIndex) => {
      for (const point of sample.markets) {
        const points = pointsByToken.get(point.token_id);
        if (points) points[sampleIndex] = point;
      }
    });
    return {
      animation: false,
      color: MARKET_SERIES_PALETTE,
      grid: PRICE_CHART_GRID,
      tooltip: priceChartTooltip((value) => value.toFixed(3)),
      xAxis: TIME_AXIS,
      yAxis: {
        ...VALUE_AXIS,
        min: OUTCOME_PRICE_FLOOR,
        max: OUTCOME_PRICE_CEILING,
        interval: (OUTCOME_PRICE_CEILING - OUTCOME_PRICE_FLOOR) / 4,
      },
      series: marketSeries.flatMap((market, index) =>
        hiddenTokens.has(market.token_id)
          ? []
          : marketSeriesForToken(samples, market, pointsByToken.get(market.token_id) ?? [], index),
      ),
    };
  }

  function recentMarketSeries(samples: ChartSamplePayload[]) {
    const markets = new Map<string, { token_id: string; label: string }>();
    for (let index = samples.length - 1; index >= 0; index -= 1) {
      for (const { token_id, label } of samples[index].markets) {
        if (!markets.has(token_id)) markets.set(token_id, { token_id, label });
        if (markets.size === MAX_CHART_TOKENS) return [...markets.values()];
      }
    }
    return [...markets.values()];
  }

  function marketSeriesForToken(
    samples: ChartSamplePayload[],
    market: { token_id: string; label: string },
    points: Array<MarketChartPointPayload | undefined>,
    index: number,
  ) {
    const { token_id: tokenId, label } = market;
    const color = MARKET_SERIES_PALETTE[index % MARKET_SERIES_PALETTE.length];
    const marketPricePoints = samples.map((sample, sampleIndex) => {
      const point = points[sampleIndex];
      return [sample.sampled_at_ms, point?.value == null ? null : Number(point.value)];
    });
    const markers = marketFillMarkers(samples, points, label);
    const seriesDataForStatus = (status: typeof VALUATION_STATUS.fresh | typeof VALUATION_STATUS.stale) =>
      marketPricePoints.map(([time, value], sampleIndex) => [
        time,
        points[sampleIndex]?.status === status ? value : null,
      ]);
    return [
      {
        id: `market:${tokenId}:fresh`,
        name: label,
        type: "line",
        showSymbol: false,
        connectNulls: false,
        itemStyle: { color },
        lineStyle: { color, width: 2 },
        data: seriesDataForStatus(VALUATION_STATUS.fresh),
      },
      {
        id: `market:${tokenId}:stale`,
        name: `${label} stale`,
        type: "line",
        showSymbol: false,
        silent: true,
        itemStyle: { color },
        lineStyle: { color, opacity: 0.4, type: "dashed", width: 2 },
        data: seriesDataForStatus(VALUATION_STATUS.stale),
      },
      {
        id: `market:${tokenId}:fills`,
        name: `${label} fills`,
        type: "scatter",
        clip: false,
        symbolSize: 8,
        data: markers,
      },
    ];
  }

  function marketFillMarkers(
    samples: ChartSamplePayload[],
    points: Array<MarketChartPointPayload | undefined>,
    label: string,
  ) {
    return points.flatMap((point, sampleIndex) =>
      point
        ? point.markers.map((side) => marketFillMarker(point, samples[sampleIndex].sampled_at_ms, label, side))
        : [],
    );
  }

  function marketFillMarker(
    point: MarketChartPointPayload,
    sampledAtMs: number,
    label: string,
    side: MarketChartPointPayload["markers"][number],
  ) {
    return {
      name: `${label} ${side === SIDE.buy ? "buy" : "sell"} fill`,
      value: [sampledAtMs, point.value == null ? null : Number(point.value)],
      symbol: side === SIDE.buy ? "triangle" : "diamond",
      itemStyle: {
        color: side === SIDE.buy ? CHART_COLORS.buy : CHART_COLORS.sell,
        borderColor: CHART_COLORS.surface,
        borderWidth: 1.5,
        opacity: 1,
      },
    };
  }
</script>

<script lang="ts">
  import EChart from "./EChart.svelte";

  let { samples }: { samples: ChartSamplePayload[] } = $props();
  let hiddenTokens = $state(new Set<string>());
  const markets = $derived(recentMarketSeries(samples));
  const option = $derived(marketChartOption(samples, hiddenTokens));

  function toggleMarket(tokenId: string): void {
    const next = new Set(hiddenTokens);
    if (next.has(tokenId)) next.delete(tokenId);
    else next.add(tokenId);
    hiddenTokens = next;
  }
</script>

<div class="market-chart-content">
  {#if markets.length}
    <div class="market-legend" role="group" aria-label="Visible markets">
      {#each markets as market, index (market.token_id)}
        <button
          class="market-legend-item"
          aria-pressed={!hiddenTokens.has(market.token_id)}
          onclick={() => toggleMarket(market.token_id)}
          title={market.label}
          style:--series-color={MARKET_SERIES_PALETTE[index % MARKET_SERIES_PALETTE.length]}
        >
          <span class="market-legend-swatch" aria-hidden="true"></span>
          <span>{market.label}</span>
        </button>
      {/each}
    </div>
    <div class="market-plot">
      <EChart {option} label="Market prices with buy and sell markers" />
    </div>
    <div
      class="chart-key"
      aria-label="Chart symbols"
      style:--buy-color={CHART_COLORS.buy}
      style:--sell-color={CHART_COLORS.sell}
    >
      <span><i class="chart-key-buy" aria-hidden="true"></i>Buy fill</span>
      <span><i class="chart-key-sell" aria-hidden="true"></i>Sell fill</span>
      <span><i class="chart-key-stale" aria-hidden="true"></i>{DASHBOARD_COPY.STALE_ESTIMATE}</span>
    </div>
  {:else}
    <p class="chart-empty">No market prices in this time window.</p>
  {/if}
</div>
