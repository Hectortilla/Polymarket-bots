import Decimal from 'decimal.js';

import { isOutcomePayout, isOutcomePrice } from '$lib/outcomePrices';

import runtimeContract from '$lib/runtimeContract.fixture.json';

import { isNonemptyString, isNonnegativeInteger, isRecord } from '$lib/valueGuards';
import { isDecimal } from '$lib/decimalGuards';

export function isPortfolioSnapshot(snapshot: Record<string, unknown>): boolean {
  const policy = runtimeContract.portfolio;
  if (
    !isDecimal(snapshot.cash_usdc) ||
    !isDecimal(snapshot.cumulative_fees_usdc) ||
    new Decimal(snapshot.cumulative_fees_usdc).lt(policy.minimumCumulativeFees) ||
    !Array.isArray(snapshot.positions)
  )
    return false;
  const tokenIds = new Set<string>();
  return snapshot.positions.every((position) => {
    if (
      !isRecord(position) ||
      !isNonemptyString(position.token_id) ||
      !isDecimal(position.size) ||
      new Decimal(position.size).lt(policy.minimumPositionSize) ||
      (policy.tokenIdsMustBeUnique && tokenIds.has(position.token_id))
    )
      return false;
    tokenIds.add(position.token_id);
    const size = new Decimal(position.size);
    if (size.isZero() && policy.emptyPositionRequiresNullPrice) {
      return position.average_entry_price === null;
    }
    return isOutcomePrice(position.average_entry_price);
  });
}

export function isMarketSettlementPayload(payload: Record<string, unknown>): boolean {
  return (
    isRecord(payload.settlement) &&
    isMarketSettlement(payload.settlement) &&
    isRecord(payload.portfolio) &&
    isPortfolioSnapshot(payload.portfolio)
  );
}

function isMarketSettlement(settlement: Record<string, unknown>): boolean {
  return (
    isRecord(settlement.resolution) &&
    isMarketResolution(settlement.resolution) &&
    Array.isArray(settlement.paper_positions) &&
    settlement.paper_positions.every(isSettledPosition) &&
    Array.isArray(settlement.followed_wallet_positions) &&
    settlement.followed_wallet_positions.every(isSettledPosition) &&
    isNonnegativeInteger(settlement.settled_at_ms)
  );
}

function isMarketResolution(resolution: Record<string, unknown>): boolean {
  return (
    isNonemptyString(resolution.condition_id) &&
    isNonemptyString(resolution.market_slug) &&
    Array.isArray(resolution.token_ids) &&
    resolution.token_ids.length === runtimeContract.marketResolution.tokenCount &&
    resolution.token_ids.every(isNonemptyString) &&
    new Set(resolution.token_ids).size === resolution.token_ids.length &&
    isNonemptyString(resolution.winning_token_id) &&
    resolution.token_ids.includes(resolution.winning_token_id) &&
    isNonemptyString(resolution.winning_outcome) &&
    isNonnegativeInteger(resolution.resolved_at_ms) &&
    isNonemptyString(resolution.source)
  );
}

function isSettledPosition(value: unknown): boolean {
  return (
    isRecord(value) &&
    isNonemptyString(value.owner) &&
    isNonemptyString(value.token_id) &&
    isDecimal(value.size) &&
    isOutcomePayout(value.payout_per_token) &&
    isDecimal(value.cash_payout_usdc) &&
    (value.realized_pnl_usdc === null ||
      value.realized_pnl_usdc === undefined ||
      isDecimal(value.realized_pnl_usdc))
  );
}
