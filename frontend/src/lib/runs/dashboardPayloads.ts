import Decimal from 'decimal.js';
import type { DispatchSkipReason } from '$lib/api/generated';
import {
  MAX_CHART_TOKENS,
  MAX_WALLET_TIMELINE_EVENTS,
  SIDE,
  VALUATION_STATUS
} from '$lib/charts/contracts';

const DECIMAL_PATTERN = /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$/;
const DISPATCH_SKIP_REASONS = new Set<DispatchSkipReason>([
  'market_metadata_missing',
  'market_not_tracked',
  'market_resolved',
  'wallet_not_tracked',
  'book_stale',
  'book_future_dated',
  'bad_book_level',
  'book_crossed',
  'wallet_trade_invalid',
  'wallet_trade_future_dated',
  'wallet_trade_stale',
  'duplicate_source_event'
]);

type ValidWalletTrade = Record<string, unknown> & {
  wallet: string;
  source_id: string;
  trade_timestamp_ms: number;
  observed_at_ms: number;
  price: string;
  size: string;
};

export function isChartSamplePayload(payload: Record<string, unknown>): boolean {
  return isNonnegativeInteger(payload.sampled_at_ms)
    && Array.isArray(payload.markets)
    && payload.markets.length <= MAX_CHART_TOKENS
    && payload.markets.every(isMarketPoint)
    && isEquityPoint(payload.equity);
}

export function isMarketChartPayload(payload: Record<string, unknown>): boolean {
  return isNonnegativeInteger(payload.sampled_at_ms)
    && Array.isArray(payload.points)
    && payload.points.length <= MAX_CHART_TOKENS
    && payload.points.every(isMarketPoint);
}

export function isEquityChartPayload(payload: Record<string, unknown>): boolean {
  return isNonnegativeInteger(payload.sampled_at_ms)
    && isEquityPoint(payload.point);
}

export function isWalletChartPayload(payload: Record<string, unknown>): boolean {
  return isNonnegativeInteger(payload.sampled_at_ms)
    && Array.isArray(payload.points)
    && payload.points.length <= MAX_WALLET_TIMELINE_EVENTS
    && payload.points.every(isWalletChartPoint);
}

export function isWalletTimelinePayload(payload: Record<string, unknown>): boolean {
  if (!isRecord(payload.trade) || !isWalletChartPoint(payload.point)) return false;
  const trade = payload.trade;
  const point = payload.point;
  if (!isWalletTrade(trade)) return false;
  if (payload.outcome !== null && !isDispatchOutcome(payload.outcome)) return false;
  const accepted = payload.outcome === null ? null : payload.outcome.accepted;
  return point.source_key === `${trade.wallet.toLowerCase()}\0${trade.source_id}`
    && point.wallet === trade.wallet.toLowerCase()
    && point.trade_timestamp_ms === trade.trade_timestamp_ms
    && point.side === trade.side
    && new Decimal(point.notional as string).eq(
      new Decimal(trade.price as string).times(trade.size as string)
    )
    && point.accepted === accepted;
}

export function isStreamHealthPayload(payload: Record<string, unknown>): boolean {
  return isNonnegativeInteger(payload.queue_depth)
    && isNonnegativeInteger(payload.peak_queue_depth)
    && (payload.book_dispatch_lag_ms === null
      || isNonnegativeInteger(payload.book_dispatch_lag_ms))
    && typeof payload.book_stale === 'boolean'
    && isNonnegativeInteger(payload.book_received_count)
    && isNonnegativeInteger(payload.book_coalesced_count);
}

function isMarketPoint(value: unknown): boolean {
  return isRecord(value)
    && isNonemptyString(value.token_id)
    && isNonemptyString(value.label)
    && isChartValueStatus(value.value, value.status)
    && Array.isArray(value.markers)
    && value.markers.every(isSide);
}

function isEquityPoint(value: unknown): boolean {
  return isRecord(value) && isChartValueStatus(value.value, value.status);
}

function isWalletChartPoint(value: unknown): value is Record<string, unknown> {
  return isRecord(value)
    && isNonemptyString(value.source_key)
    && isNonemptyString(value.wallet)
    && isNonnegativeInteger(value.trade_timestamp_ms)
    && isSide(value.side)
    && isNonnegativeDecimal(value.notional)
    && isNonemptyString(value.market_label)
    && (value.accepted === null || typeof value.accepted === 'boolean');
}

function isWalletTrade(
  trade: Record<string, unknown>
): trade is ValidWalletTrade {
  return /^0x[0-9a-f]{40}$/i.test(String(trade.wallet))
    && isNonemptyString(trade.condition_id)
    && isNonemptyString(trade.token_id)
    && isSide(trade.side)
    && isPositiveDecimal(trade.size)
    && isOutcomePrice(trade.price)
    && isNonemptyString(trade.source_id)
    && !trade.source_id.includes('\0')
    && isNonnegativeInteger(trade.trade_timestamp_ms)
    && isNonnegativeInteger(trade.observed_at_ms)
    && trade.observed_at_ms >= trade.trade_timestamp_ms;
}

function isDispatchOutcome(value: unknown): value is Record<string, unknown> & { accepted: boolean } {
  if (!isRecord(value) || typeof value.accepted !== 'boolean') return false;
  return value.accepted
    ? value.skip_reason === null || value.skip_reason === undefined
    : DISPATCH_SKIP_REASONS.has(value.skip_reason as DispatchSkipReason);
}

function isChartValueStatus(value: unknown, status: unknown): boolean {
  if (status === VALUATION_STATUS.unavailable) return value === null;
  return (status === VALUATION_STATUS.fresh || status === VALUATION_STATUS.stale)
    && isDecimal(value);
}

function isSide(value: unknown): boolean {
  return value === SIDE.buy || value === SIDE.sell;
}

function isDecimal(value: unknown): value is string {
  if (typeof value !== 'string' || !DECIMAL_PATTERN.test(value)) return false;
  return new Decimal(value).isFinite();
}

function isNonnegativeDecimal(value: unknown): boolean {
  return isDecimal(value) && new Decimal(value as string).gte(0);
}

export function isPositiveDecimal(value: unknown): boolean {
  return isDecimal(value) && new Decimal(value as string).gt(0);
}

function isOutcomePrice(value: unknown): boolean {
  return isDecimal(value) && new Decimal(value as string).gte(0)
    && new Decimal(value as string).lte(1);
}

function isNonemptyString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0;
}

export function isNonnegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}
