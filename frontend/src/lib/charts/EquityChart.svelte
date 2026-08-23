<script module lang="ts">
  import type { ChartSamplePayload } from '$lib/api/generated';
  import {
    VALUATION_STATUS,
    type AvailableValuationStatus
  } from './contracts';
  import type { EChartsCoreOption } from './echarts';

  export function equityChartOption(samples: ChartSamplePayload[]): EChartsCoreOption {
    const data = (status: AvailableValuationStatus) => samples.map((sample) => [
      sample.sampled_at_ms,
      sample.equity.status === status && sample.equity.value !== null
        ? Number(sample.equity.value)
        : null
    ]);
    return {
      animation: false,
      grid: { left: 56, right: 16, top: 16, bottom: 28 },
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'time', axisLabel: { color: '#7e8781' } },
      yAxis: { type: 'value', scale: true, axisLabel: { color: '#7e8781' } },
      series: [
        { id: 'equity:fresh', name: 'Executable equity', type: 'line', showSymbol: false, lineStyle: { color: '#72df98' }, data: data(VALUATION_STATUS.fresh) },
        { id: 'equity:stale', name: 'Stale estimate', type: 'line', showSymbol: false, lineStyle: { color: '#72df98', opacity: 0.3 }, data: data(VALUATION_STATUS.stale) }
      ]
    };
  }
</script>

<script lang="ts">
  import EChart from './EChart.svelte';

  let { samples }: { samples: ChartSamplePayload[] } = $props();
  const option = $derived(equityChartOption(samples));
</script>

<EChart {option} label="Executable paper equity" class="equity-echart" />
