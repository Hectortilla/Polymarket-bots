import Decimal from "decimal.js";

import { isOutcomePrice } from "$lib/outcomePrices";

import { isSide } from "$lib/sides";

import runtimeContract from "$lib/runtimeContract.fixture.json";

import { isNonemptyString, isNonnegativeInteger, isNullableString, isOneOf, isRecord } from "$lib/valueGuards";
import { isDecimal, isNonnegativeDecimal, isPositiveDecimal } from "$lib/decimalGuards";

import { isPortfolioSnapshot } from "$lib/runs/eventPayloads/portfolio";

const FILL_REJECT_REASONS = Object.values(runtimeContract.fillRejectReason);

const ORDER_STATUSES = Object.values(runtimeContract.orderStatus);

export function isOrderRequest(order: Record<string, unknown>): boolean {
  return (
    isNonemptyString(order.token_id) &&
    isSide(order.side) &&
    isOutcomePrice(order.price) &&
    isPositiveDecimal(order.size) &&
    isNullableString(order.market_slug) &&
    isNullableString(order.condition_id) &&
    isNullableString(order.reason) &&
    isValidSourceId(order.source_id)
  );
}

export function isBrokerFillPayload(payload: Record<string, unknown>): boolean {
  return (
    isRecord(payload.order) &&
    isOrderRequest(payload.order) &&
    isRecord(payload.fill) &&
    isFill(payload.fill) &&
    (payload.portfolio === null || (isRecord(payload.portfolio) && isPortfolioSnapshot(payload.portfolio))) &&
    isNonnegativeInteger(payload.latency_ms)
  );
}

function isValidSourceId(value: unknown): boolean {
  return (
    value === null || value === undefined || (isNonemptyString(value) && !value.includes("\n") && !value.includes("\r"))
  );
}

function isFill(fill: Record<string, unknown>): boolean {
  if (
    !isNonemptyString(fill.order_id) ||
    typeof fill.token_id !== "string" ||
    !isSide(fill.side) ||
    !isOneOf(fill.status, ORDER_STATUSES) ||
    !isDecimal(fill.requested_size) ||
    !isNonnegativeDecimal(fill.filled_size) ||
    !isNonnegativeDecimal(fill.fee_usdc) ||
    !isNonnegativeInteger(fill.received_at_ms)
  )
    return false;

  const requestedSize = new Decimal(fill.requested_size);
  const filledSize = new Decimal(fill.filled_size);
  const policy = runtimeContract.fillStatusPolicy[fill.status as keyof typeof runtimeContract.fillStatusPolicy];
  if (policy.requiresRejectDetails) {
    return (
      filledSize.isZero() &&
      fill.average_price === null &&
      new Decimal(fill.fee_usdc).isZero() &&
      isOneOf(fill.reject_reason, FILL_REJECT_REASONS) &&
      isNonemptyString(fill.reject_message)
    );
  }
  const minimumExclusiveSize = new Decimal(runtimeContract.fillExecution.minimumExclusiveSize);
  if (
    !isNonemptyString(fill.token_id) ||
    !requestedSize.gt(minimumExclusiveSize) ||
    filledSize.gt(requestedSize) ||
    (fill.reject_reason !== null && fill.reject_reason !== undefined) ||
    (fill.reject_message !== null && fill.reject_message !== undefined)
  )
    return false;
  if (policy.execution === runtimeContract.fillExecutionConstraint.NONE) {
    return filledSize.isZero() && fill.average_price === null && new Decimal(fill.fee_usdc).isZero();
  }
  if (!isOutcomePrice(fill.average_price) || !filledSize.gt(minimumExclusiveSize)) return false;
  return policy.execution === runtimeContract.fillExecutionConstraint.EXACT_REQUEST
    ? filledSize.eq(requestedSize)
    : policy.execution === runtimeContract.fillExecutionConstraint.BELOW_REQUEST && filledSize.lt(requestedSize);
}
