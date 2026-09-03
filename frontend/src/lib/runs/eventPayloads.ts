import Decimal from 'decimal.js';
import type { PersistedDurableEvent } from '$lib/api/generated';
import { SIDE } from '$lib/charts/contracts';
import { isOutcomePayout, isOutcomePrice } from '$lib/outcomePrices';
import { isSide } from '$lib/sides';
import runtimeContract from '$lib/runtimeContract.fixture.json';
import {
  isDecimal,
  isInteger,
  isNonemptyString,
  isNonnegativeDecimal,
  isNonnegativeInteger,
  isNullableString,
  isOneOf,
  isPositiveDecimal,
  isRecord
} from '$lib/valueGuards';
import {
  isChartSamplePayload,
  isStreamHealthPayload,
  isWalletTimelinePayload
} from './dashboardPayloads';
import { EVENT_KIND } from './eventKinds';
import { INITIAL_RUN_STATUS, isRunStatus } from './status';

const ACTIVITY_SEVERITIES = Object.values(runtimeContract.activitySeverity);
const BOOTSTRAP_PHASES = Object.values(runtimeContract.bootstrapPhase);
const FILL_REJECT_REASONS = Object.values(runtimeContract.fillRejectReason);
const ORDER_STATUSES = Object.values(runtimeContract.orderStatus);
const WALLET_TRADE_KINDS = Object.values(runtimeContract.walletTradeKind);

export function isDurableEventPayload(
  kind: PersistedDurableEvent['kind'],
  payload: Record<string, unknown>
): boolean {
  switch (kind) {
    case EVENT_KIND.runLifecycle:
      return isLifecyclePayload(payload);
    case EVENT_KIND.runBootstrap:
      return isBootstrapPayload(payload);
    case EVENT_KIND.botActivity:
      return isActivityPayload(payload);
    case EVENT_KIND.brokerOrder:
      return isRecord(payload.order) && isOrderRequest(payload.order);
    case EVENT_KIND.brokerFill:
      return isBrokerFillPayload(payload);
    case EVENT_KIND.brokerFailure:
      return isRecord(payload.order)
        && isOrderRequest(payload.order)
        && isNonemptyString(payload.error);
    case EVENT_KIND.marketSettlement:
      return isMarketSettlementPayload(payload);
    case EVENT_KIND.portfolioSnapshot:
      return isPortfolioSnapshot(payload);
    case EVENT_KIND.walletTimeline:
      return isWalletTimelinePayload(payload) && isWalletTradeKind(payload);
    case EVENT_KIND.streamHealth:
      return isStreamHealthPayload(payload);
    case EVENT_KIND.runFailure:
      return isNonemptyString(payload.error);
    case EVENT_KIND.chartSample:
      return isChartSamplePayload(payload);
    default:
      return kind satisfies never;
  }
}

function isLifecyclePayload(payload: Record<string, unknown>): boolean {
  const hasStartedFields = payload.name !== undefined
    || payload.mode !== undefined
    || payload.initial_cash_usdc !== undefined;
  if (!hasStartedFields) return isRunStatus(payload.status);
  return (payload.status === undefined || payload.status === INITIAL_RUN_STATUS)
    && isNonemptyString(payload.name)
    && isOneOf(payload.mode, Object.values(runtimeContract.botMode))
    && isPositiveDecimal(payload.initial_cash_usdc);
}

function isBootstrapPayload(payload: Record<string, unknown>): boolean {
  if (!isOneOf(payload.phase, BOOTSTRAP_PHASES)
    || !isInteger(payload.completed)
    || !isInteger(payload.total)) return false;
  const policy = runtimeContract.bootstrapProgress;
  return payload.completed >= policy.minimum
    && payload.total >= policy.minimum
    && (policy.completedMayExceedTotal || payload.completed <= payload.total);
}

function isActivityPayload(payload: Record<string, unknown>): boolean {
  return isNonemptyString(payload.message)
    && isOneOf(payload.severity, ACTIVITY_SEVERITIES);
}

function isOrderRequest(order: Record<string, unknown>): boolean {
  return isNonemptyString(order.token_id)
    && isSide(order.side)
    && isOutcomePrice(order.price)
    && isPositiveDecimal(order.size)
    && isNullableString(order.market_slug)
    && isNullableString(order.condition_id)
    && isNullableString(order.reason)
    && isValidSourceId(order.source_id);
}

function isValidSourceId(value: unknown): boolean {
  return value === null || value === undefined || (
    isNonemptyString(value) && !value.includes('\n') && !value.includes('\r')
  );
}

function isBrokerFillPayload(payload: Record<string, unknown>): boolean {
  return isRecord(payload.order)
    && isOrderRequest(payload.order)
    && isRecord(payload.fill)
    && isFill(payload.fill)
    && (payload.portfolio === null || (
      isRecord(payload.portfolio) && isPortfolioSnapshot(payload.portfolio)
    ))
    && isNonnegativeInteger(payload.latency_ms);
}

function isFill(fill: Record<string, unknown>): boolean {
  if (!isNonemptyString(fill.order_id)
    || typeof fill.token_id !== 'string'
    || !isSide(fill.side)
    || !isOneOf(fill.status, ORDER_STATUSES)
    || !isDecimal(fill.requested_size)
    || !isNonnegativeDecimal(fill.filled_size)
    || !isNonnegativeDecimal(fill.fee_usdc)
    || !isNonnegativeInteger(fill.received_at_ms)) return false;

  const requestedSize = new Decimal(fill.requested_size);
  const filledSize = new Decimal(fill.filled_size);
  const policy = runtimeContract.fillStatusPolicy[
    fill.status as keyof typeof runtimeContract.fillStatusPolicy
  ];
  if (policy.requiresRejectDetails) {
    return filledSize.isZero()
      && fill.average_price === null
      && new Decimal(fill.fee_usdc).isZero()
      && isOneOf(fill.reject_reason, FILL_REJECT_REASONS)
      && isNonemptyString(fill.reject_message);
  }
  const minimumExclusiveSize = new Decimal(
    runtimeContract.fillExecution.minimumExclusiveSize
  );
  if (!isNonemptyString(fill.token_id)
    || !requestedSize.gt(minimumExclusiveSize)
    || filledSize.gt(requestedSize)
    || fill.reject_reason !== null && fill.reject_reason !== undefined
    || fill.reject_message !== null && fill.reject_message !== undefined) return false;
  if (policy.execution === runtimeContract.fillExecutionConstraint.NONE) {
    return filledSize.isZero() && fill.average_price === null;
  }
  if (!isOutcomePrice(fill.average_price)
    || !filledSize.gt(minimumExclusiveSize)) return false;
  return policy.execution === runtimeContract.fillExecutionConstraint.EXACT_REQUEST
    ? filledSize.eq(requestedSize)
    : policy.execution === runtimeContract.fillExecutionConstraint.BELOW_REQUEST
      && filledSize.lt(requestedSize);
}

function isPortfolioSnapshot(snapshot: Record<string, unknown>): boolean {
  const policy = runtimeContract.portfolio;
  if (!isDecimal(snapshot.cash_usdc)
    || !isDecimal(snapshot.cumulative_fees_usdc)
    || new Decimal(snapshot.cumulative_fees_usdc).lt(policy.minimumCumulativeFees)
    || !Array.isArray(snapshot.positions)) return false;
  const tokenIds = new Set<string>();
  return snapshot.positions.every((position) => {
    if (!isRecord(position)
      || !isNonemptyString(position.token_id)
      || !isDecimal(position.size)
      || new Decimal(position.size).lt(policy.minimumPositionSize)
      || (policy.tokenIdsMustBeUnique && tokenIds.has(position.token_id))) return false;
    tokenIds.add(position.token_id);
    const size = new Decimal(position.size);
    if (size.isZero() && policy.emptyPositionRequiresNullPrice) {
      return position.average_entry_price === null;
    }
    return isOutcomePrice(position.average_entry_price);
  });
}

function isMarketSettlementPayload(payload: Record<string, unknown>): boolean {
  return isRecord(payload.settlement)
    && isMarketSettlement(payload.settlement)
    && isRecord(payload.portfolio)
    && isPortfolioSnapshot(payload.portfolio);
}

function isMarketSettlement(settlement: Record<string, unknown>): boolean {
  return isRecord(settlement.resolution)
    && isMarketResolution(settlement.resolution)
    && Array.isArray(settlement.paper_positions)
    && settlement.paper_positions.every(isSettledPosition)
    && Array.isArray(settlement.followed_wallet_positions)
    && settlement.followed_wallet_positions.every(isSettledPosition)
    && isNonnegativeInteger(settlement.settled_at_ms);
}

function isMarketResolution(resolution: Record<string, unknown>): boolean {
  return isNonemptyString(resolution.condition_id)
    && isNonemptyString(resolution.market_slug)
    && Array.isArray(resolution.token_ids)
    && resolution.token_ids.length === runtimeContract.marketResolution.tokenCount
    && resolution.token_ids.every(isNonemptyString)
    && new Set(resolution.token_ids).size === resolution.token_ids.length
    && isNonemptyString(resolution.winning_token_id)
    && resolution.token_ids.includes(resolution.winning_token_id)
    && isNonemptyString(resolution.winning_outcome)
    && isNonnegativeInteger(resolution.resolved_at_ms)
    && isNonemptyString(resolution.source);
}

function isSettledPosition(value: unknown): boolean {
  return isRecord(value)
    && isNonemptyString(value.owner)
    && isNonemptyString(value.token_id)
    && isDecimal(value.size)
    && isOutcomePayout(value.payout_per_token)
    && isDecimal(value.cash_payout_usdc)
    && (value.realized_pnl_usdc === null
      || value.realized_pnl_usdc === undefined
      || isDecimal(value.realized_pnl_usdc));
}

function isWalletTradeKind(payload: Record<string, unknown>): boolean {
  return isRecord(payload.trade)
    && (payload.trade.kind === undefined
      || isOneOf(payload.trade.kind, WALLET_TRADE_KINDS));
}
