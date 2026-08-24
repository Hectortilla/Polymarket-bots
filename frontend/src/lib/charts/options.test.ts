import { describe, expect, it } from 'vitest';

import type {
  ChartSamplePayload,
  Side,
  WalletChartPointPayload
} from '$lib/api/generated';
import {
  SIDE,
  VALUATION_STATUS,
  type AvailableValuationStatus
} from './contracts';
import { equityChartOption } from './EquityChart.svelte';
import { marketChartOption } from './MarketChart.svelte';
import { walletChartOption } from './WalletChart.svelte';
import walletBucketParity from '../../../../contracts/dashboard-wallet-bucket-parity.json';

describe('dashboard option builders', () => {
  it('keeps market stale spans and fill markers separate', () => {
    const option = marketChartOption([
      sample(1_000, '0.5', VALUATION_STATUS.fresh, [SIDE.buy]),
      sample(2_000, '0.5', VALUATION_STATUS.stale, [])
    ]);
    const series = option.series as Array<{ data: unknown[] }>;

    expect(series).toHaveLength(3);
    expect(series[0].data).toEqual([[1_000, 0.5], [2_000, null]]);
    expect(series[1].data).toEqual([[1_000, null], [2_000, 0.5]]);
    expect(series[2].data).toHaveLength(1);
  });

  it('keeps recent market history when the final sample has no active market', () => {
    const option = marketChartOption([
      sample(1_000, '0.5', VALUATION_STATUS.fresh, []),
      {
        sampled_at_ms: 2_000,
        markets: [],
        equity: { value: '100', status: VALUATION_STATUS.fresh }
      }
    ]);
    const series = option.series as Array<{ data: unknown[] }>;

    expect(series).toHaveLength(3);
    expect(series[0].data).toEqual([[1_000, 0.5], [2_000, null]]);
  });

  it('separates fresh and stale executable equity', () => {
    const option = equityChartOption([
      sample(1_000, '100', VALUATION_STATUS.fresh, []),
      sample(2_000, '100', VALUATION_STATUS.stale, [])
    ]);
    const series = option.series as Array<{ data: unknown[] }>;

    expect(series[0].data).toEqual([[1_000, 100], [2_000, null]]);
    expect(series[1].data).toEqual([[1_000, null], [2_000, 100]]);
  });

  it('buckets wallet sides, relative notional, and skipped opacity', () => {
    const wallet = '0x0000000000000000000000000000000000000001';
    const points: WalletChartPointPayload[] = [
      walletPoint(wallet, 'one', SIDE.buy, '1', false),
      walletPoint(wallet, 'two', SIDE.sell, '2', false)
    ];
    const option = walletChartOption(points, [wallet], 1_000, 2_000);
    const series = option.series as Array<{
      data: Array<{ symbolSize: number; itemStyle: { color: string; opacity: number } }>;
    }>;

    expect(series[0].data[0].symbolSize).toBe(13);
    expect(series[0].data[0].itemStyle.color).toBe('#f6c453');
    expect(series[0].data[0].itemStyle.opacity).toBe(0.32);
  });

  it('rejects a non-increasing wallet timeline range', () => {
    expect(() => walletChartOption([], [], 1_000, 1_000)).toThrow(
      'wallet chart range must increase'
    );
  });

  it('matches the shared terminal/browser wallet-bucket scenario', () => {
    const points: WalletChartPointPayload[] = walletBucketParity.points.map(
      (point) => ({
        ...point,
        side: point.side as Side,
        market_label: 'Market'
      })
    );
    const option = walletChartOption(
      points,
      walletBucketParity.lanes,
      walletBucketParity.start_ms,
      walletBucketParity.end_ms
    );
    const series = option.series as Array<{
      data: Array<{
        value: [number, number, number];
        symbolSize: number;
        itemStyle: { color: string; opacity: number };
      }>;
    }>;

    expect(series[0].data.map(({ value, symbolSize, itemStyle }) => ({
      time: value[0],
      notional: value[2],
      size: symbolSize,
      color: itemStyle.color,
      opacity: itemStyle.opacity
    }))).toEqual(walletBucketParity.web_expected);
  });

  it('keeps exact decimal notional tiers at their shared boundary', () => {
    const boundary = walletBucketParity.decimal_boundary;
    const points: WalletChartPointPayload[] = boundary.points.map((point) => ({
      ...point,
      side: point.side as Side,
      market_label: 'Market'
    }));
    const option = walletChartOption(
      points,
      boundary.lanes,
      walletBucketParity.start_ms,
      walletBucketParity.end_ms
    );
    const series = option.series as Array<{
      data: Array<{ symbolSize: number }>;
    }>;

    expect(series[0].data.map(({ symbolSize }) => symbolSize)).toEqual(
      boundary.sizes
    );
  });
});

function sample(
  sampledAtMs: number,
  value: string,
  status: AvailableValuationStatus,
  markers: Side[]
): ChartSamplePayload {
  return {
    sampled_at_ms: sampledAtMs,
    markets: [{ token_id: 'token', label: 'Market · Up', value, status, markers }],
    equity: { value, status }
  };
}

function walletPoint(
  wallet: string,
  sourceKey: string,
  side: Side,
  notional: string,
  accepted: boolean
): WalletChartPointPayload {
  return {
    source_key: sourceKey,
    wallet,
    trade_timestamp_ms: 1_100,
    side,
    notional,
    market_label: 'Market · Up',
    accepted
  };
}
