<script module lang="ts">
  import Decimal from 'decimal.js';
  import type { WalletChartPointPayload } from '$lib/api/generated';
  import {
    SIDE,
    WALLET_LABEL_MAX_LENGTH,
    WALLET_NOTIONAL_TIER_COUNT
  } from './contracts';
  import type { EChartsCoreOption } from './echarts';

  type Bucket = { timestampMs: number; laneIndex: number; notional: Decimal; sides: Set<WalletChartPointPayload['side']>; skipped: boolean };

  export function walletChartOption(
    points: WalletChartPointPayload[],
    lanes: string[],
    startMs: number,
    endMs: number
  ): EChartsCoreOption {
    if (endMs <= startMs) throw new Error('wallet chart range must increase');
    return buildWalletChartOption(points, lanes, startMs, endMs);
  }

  function buildWalletChartOption(
    points: WalletChartPointPayload[],
    lanes: string[],
    startMs: number,
    endMs: number
  ): EChartsCoreOption {
    const columns = 60;
    const spanMs = endMs - startMs;
    const buckets = new Map<string, Bucket>();
    for (const point of points) {
      const laneIndex = lanes.indexOf(point.wallet);
      if (laneIndex < 0 || point.trade_timestamp_ms < startMs || point.trade_timestamp_ms > endMs) continue;
      const column = walletBucketIndex(
        point.trade_timestamp_ms,
        startMs,
        spanMs,
        columns
      );
      const key = `${laneIndex}:${column}`;
      const bucket = buckets.get(key) ?? {
        timestampMs: startMs + column * spanMs / columns,
        laneIndex,
        notional: new Decimal(0),
        sides: new Set(),
        skipped: true
      };
      bucket.notional = bucket.notional.plus(point.notional);
      bucket.sides.add(point.side);
      bucket.skipped &&= point.accepted === false;
      buckets.set(key, bucket);
    }
    const maximumNotional = [...buckets.values()].reduce(
      (current, bucket) => Decimal.max(current, bucket.notional),
      new Decimal(0)
    );
    return {
      animation: false,
      grid: { left: 116, right: 16, top: 16, bottom: 28 },
      tooltip: { trigger: 'item' },
      xAxis: { type: 'time', min: startMs, max: endMs, axisLabel: { color: '#7e8781' } },
      yAxis: {
        type: 'category',
        data: lanes.map(shortWallet),
        axisLabel: { color: '#b8bfbb', fontFamily: 'monospace' }
      },
      series: [{
        id: 'wallet:activity',
        name: 'Wallet activity',
        type: 'scatter',
        data: [...buckets.values()].map((bucket) => ({
          value: [bucket.timestampMs, bucket.laneIndex, bucket.notional.toNumber()],
          symbolSize: walletSymbolSize(bucket.notional, maximumNotional),
          itemStyle: {
            color: walletBucketColor(bucket.sides),
            opacity: bucket.skipped ? 0.32 : 1
          }
        }))
      }]
    };
  }

  function shortWallet(wallet: string): string {
    return wallet.length <= WALLET_LABEL_MAX_LENGTH
      ? wallet
      : `${wallet.slice(0, 6)}…${wallet.slice(-4)}`;
  }

  function walletSymbolSize(notional: Decimal, maximumNotional: Decimal): number {
    const weightedNotional = notional.times(WALLET_NOTIONAL_TIER_COUNT);
    if (weightedNotional.lte(maximumNotional)) return 5;
    return weightedNotional.lte(
      maximumNotional.times(WALLET_NOTIONAL_TIER_COUNT - 1)
    ) ? 9 : 13;
  }

  function walletBucketIndex(
    timestampMs: number,
    startMs: number,
    spanMs: number,
    columns: number
  ): number {
    return Math.min(
      columns - 1,
      Math.floor((timestampMs - startMs) * columns / spanMs)
    );
  }

  function walletBucketColor(sides: Set<WalletChartPointPayload['side']>): string {
    if (sides.size > 1) return '#f6c453';
    return sides.has(SIDE.buy) ? '#72df98' : '#ff847c';
  }
</script>

<script lang="ts">
  import EChart from './EChart.svelte';

  let {
    points,
    lanes,
    startMs,
    endMs
  }: {
    points: WalletChartPointPayload[];
    lanes: string[];
    startMs: number;
    endMs: number;
  } = $props();
  const option = $derived(walletChartOption(points, lanes, startMs, endMs));
</script>

<EChart {option} label="Followed-wallet trade timeline" />
