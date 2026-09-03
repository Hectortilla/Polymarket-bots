<script module lang="ts">
  import Decimal from 'decimal.js';
  import type { WalletChartPointPayload } from '$lib/api/generated';
  import { SIDE } from './contracts';
  import type { EChartsCoreOption } from './echarts';
  import { walletBucketIndex, walletNotionalTier } from './walletBuckets';

  type Bucket = { timestampMs: number; laneIndex: number; notional: Decimal; sides: Set<WalletChartPointPayload['side']>; skipped: boolean };
  const WALLET_LABEL_MAX_LENGTH = 12;

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
        endMs,
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
    return [5, 9, 13][walletNotionalTier(notional, maximumNotional) - 1];
  }

  function walletBucketColor(sides: Set<WalletChartPointPayload['side']>): string {
    if (sides.size > 1) return '#f6c453';
    return sides.has(SIDE.buy) ? '#72df98' : '#ff847c';
  }
</script>

<script lang="ts">
  import { onMount } from 'svelte';
  import EChart from './EChart.svelte';
  import { DASHBOARD_KEY } from './contracts';
  import { DASHBOARD_COPY } from './copy';

  const WALLET_LANES_PER_PAGE = 6;

  let {
    points,
    configuredWallets = [],
    startMs,
    endMs
  }: {
    points: WalletChartPointPayload[];
    configuredWallets?: string[];
    startMs: number;
    endMs: number;
  } = $props();
  let walletPage = $state(0);
  const lanes = $derived([
    ...new Set([...configuredWallets, ...points.map(({ wallet }) => wallet)])
  ]);
  const maximumWalletPage = $derived(
    Math.max(0, Math.ceil(lanes.length / WALLET_LANES_PER_PAGE) - 1)
  );
  const visibleLanes = $derived(
    lanes.slice(
      walletPage * WALLET_LANES_PER_PAGE,
      (walletPage + 1) * WALLET_LANES_PER_PAGE
    )
  );
  const option = $derived(
    walletChartOption(points, visibleLanes, startMs, endMs)
  );

  $effect(() => {
    walletPage = Math.min(walletPage, maximumWalletPage);
  });

  onMount(() => {
    const keydown = (event: KeyboardEvent) => {
      if (
        event.target instanceof HTMLInputElement
        || event.target instanceof HTMLTextAreaElement
      ) return;
      changeWalletPage(event.key.toLowerCase());
    };
    window.addEventListener('keydown', keydown);
    return () => window.removeEventListener('keydown', keydown);
  });

  function changeWalletPage(key: string): void {
    if (key === DASHBOARD_KEY.nextWalletPage) {
      walletPage = Math.min(maximumWalletPage, walletPage + 1);
    } else if (key === DASHBOARD_KEY.previousWalletPage) {
      walletPage = Math.max(0, walletPage - 1);
    }
  }
</script>

{#if visibleLanes.length}
  <div class="dashboard-controls" aria-label={DASHBOARD_COPY.WALLET_CONTROLS_ARIA_LABEL}>
    <button onclick={() => changeWalletPage(DASHBOARD_KEY.previousWalletPage)} disabled={walletPage === 0} title={`Keyboard: ${DASHBOARD_KEY.previousWalletPage}`}>{DASHBOARD_KEY.previousWalletPage} · {DASHBOARD_COPY.WALLET_CONTROL_PREVIOUS}</button>
    <button onclick={() => changeWalletPage(DASHBOARD_KEY.nextWalletPage)} disabled={walletPage === maximumWalletPage} title={`Keyboard: ${DASHBOARD_KEY.nextWalletPage}`}>{DASHBOARD_KEY.nextWalletPage} · {DASHBOARD_COPY.WALLET_CONTROL_NEXT}</button>
  </div>
  <EChart {option} label={DASHBOARD_COPY.WALLET_TIMELINE_ARIA_LABEL} />
{:else}
  <p class="chart-empty">{DASHBOARD_COPY.NO_WALLETS}</p>
{/if}
