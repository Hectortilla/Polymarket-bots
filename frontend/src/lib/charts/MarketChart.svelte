<script module lang="ts">
  import type {
    ChartSamplePayload,
    MarketChartPointPayload
  } from '$lib/api/generated';
  import {
    MAX_CHART_TOKENS,
    OUTCOME_PRICE_CEILING,
    OUTCOME_PRICE_FLOOR,
    SIDE,
    VALUATION_STATUS
  } from './contracts';
  import type { EChartsCoreOption } from './echarts';

  const MARKET_SERIES_PALETTE = [
    '#57d3ff', '#cf84ff', '#f6c453', '#72df98', '#6fa8ff',
    '#ff847c', '#63e0d5', '#d8dedb', '#ff9e64', '#ad7cff',
    '#f57fb3', '#47b9a8', '#8bde64', '#edca58', '#fb7870',
    '#8c7dff', '#35ccd7', '#ff986f', '#55de82', '#bfc5c2'
  ];

  export function marketChartOption(samples: ChartSamplePayload[]): EChartsCoreOption {
    const marketSeries = recentMarketSeries(samples);
    const pointsByToken = new Map(
      marketSeries.map(({ token_id }) => [
        token_id,
        Array<MarketChartPointPayload | undefined>(samples.length)
      ])
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
      grid: { left: 44, right: 16, top: 42, bottom: 28 },
      legend: { top: 0, textStyle: { color: '#b8bfbb' } },
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'time', axisLabel: { color: '#7e8781' } },
      yAxis: { type: 'value', min: OUTCOME_PRICE_FLOOR, max: OUTCOME_PRICE_CEILING, axisLabel: { color: '#7e8781' } },
      series: marketSeries.flatMap((market, index) =>
        marketSeriesForToken(
          samples,
          market,
          pointsByToken.get(market.token_id) ?? [],
          index
        )
      )
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
    index: number
  ) {
    const { token_id: tokenId, label } = market;
    const color = MARKET_SERIES_PALETTE[index % MARKET_SERIES_PALETTE.length];
    const values = samples.map((sample, sampleIndex) => {
      const point = points[sampleIndex];
      return [
        sample.sampled_at_ms,
        point?.value == null ? null : Number(point.value)
      ];
    });
    const markers = points.flatMap((point, sampleIndex) =>
      (point?.markers ?? []).map((side) => ({
        value: [samples[sampleIndex].sampled_at_ms, point?.value == null ? null : Number(point.value)],
        itemStyle: { color: side === SIDE.buy ? '#72df98' : '#ff847c' }
      }))
    );
    const data = (status: typeof VALUATION_STATUS.fresh | typeof VALUATION_STATUS.stale) =>
      values.map(([time, value], sampleIndex) => [
        time,
        points[sampleIndex]?.status === status ? value : null
      ]);
    return [
      {
        id: `market:${tokenId}:fresh`,
        name: label,
        type: 'line',
        showSymbol: false,
        connectNulls: false,
        lineStyle: { color, width: 1.5 },
        data: data(VALUATION_STATUS.fresh)
      },
      {
        id: `market:${tokenId}:stale`,
        name: `${label} stale`,
        type: 'line',
        showSymbol: false,
        silent: true,
        lineStyle: { color, opacity: 0.3, width: 1.5 },
        data: data(VALUATION_STATUS.stale)
      },
      {
        id: `market:${tokenId}:fills`,
        name: `${label} fills`,
        type: 'scatter',
        symbolSize: 8,
        data: markers
      }
    ];
  }
</script>

<script lang="ts">
  import EChart from './EChart.svelte';

  let { samples }: { samples: ChartSamplePayload[] } = $props();
  const option = $derived(marketChartOption(samples));
</script>

<EChart {option} label="Market prices with buy and sell markers" />
