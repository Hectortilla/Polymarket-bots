import runtimeContract from "$lib/runtimeContract.fixture.json";
import { isNonemptyString, isNonnegativeInteger } from "$lib/valueGuards";
import { isPositiveDecimal, isNonnegativeDecimal } from "$lib/decimalGuards";
import { isNodeGraph } from "./graph";
import { isStreamRule } from "./streamRules";

export function isPaperConfig(value: Record<string, unknown>): boolean {
  return (
    (value.graph === null || value.graph === undefined || isNodeGraph(value.graph)) &&
    isNonemptyString(value.name) &&
    isPositiveDecimal(value.paper_portfolio_usdc) &&
    isPositiveDecimal(value.max_order_size) &&
    isNonnegativeDecimal(value.max_slippage_pct) &&
    isNonnegativeInteger(value.paper_latency_ms) &&
    isNonnegativeInteger(value.paper_latency_jitter_ms) &&
    isNonnegativeInteger(value.event_max_age_ms) &&
    isNonnegativeInteger(value.data_trades_budget_per_10s) &&
    value.data_trades_budget_per_10s >= runtimeContract.config.minimumDataTradesBudget &&
    value.data_trades_budget_per_10s <= runtimeContract.config.maximumDataTradesBudget &&
    Array.isArray(value.stream_rules) &&
    value.stream_rules.every(isStreamRule)
  );
}
