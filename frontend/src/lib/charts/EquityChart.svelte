<script module lang="ts">
  import type { ChartSamplePayload } from "$lib/api/generated";
  import { VALUATION_STATUS, type AvailableValuationStatus } from "./contracts";
  import type { EChartsCoreOption } from "./echarts";
  import { CHART_COLORS, PRICE_CHART_GRID, TIME_AXIS, VALUE_AXIS, priceChartTooltip } from "./appearance";
  import { DASHBOARD_COPY } from "./copy";

  export function equityChartOption(samples: ChartSamplePayload[]): EChartsCoreOption {
    const seriesDataForStatus = (status: AvailableValuationStatus) =>
      samples.map((sample) => [
        sample.sampled_at_ms,
        sample.equity.status === status && sample.equity.value !== null ? Number(sample.equity.value) : null,
      ]);
    return {
      animation: false,
      grid: PRICE_CHART_GRID,
      tooltip: priceChartTooltip((value) =>
        value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
      ),
      xAxis: TIME_AXIS,
      yAxis: { ...VALUE_AXIS, scale: true, boundaryGap: ["15%", "15%"] },
      series: [
        {
          id: "equity:fresh",
          name: DASHBOARD_COPY.EQUITY,
          type: "line",
          showSymbol: false,
          itemStyle: { color: CHART_COLORS.buy },
          lineStyle: { color: CHART_COLORS.buy, width: 2 },
          data: seriesDataForStatus(VALUATION_STATUS.fresh),
        },
        {
          id: "equity:stale",
          name: DASHBOARD_COPY.STALE_ESTIMATE,
          type: "line",
          showSymbol: false,
          itemStyle: { color: CHART_COLORS.buy },
          lineStyle: { color: CHART_COLORS.buy, opacity: 0.4, type: "dashed", width: 2 },
          data: seriesDataForStatus(VALUATION_STATUS.stale),
        },
      ],
    };
  }
</script>

<script lang="ts">
  import EChart from "./EChart.svelte";

  let { samples }: { samples: ChartSamplePayload[] } = $props();
  const option = $derived(equityChartOption(samples));
</script>

<EChart {option} label="Executable paper equity" class="equity-echart" />
