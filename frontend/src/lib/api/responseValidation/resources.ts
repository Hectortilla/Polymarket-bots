import { isArrayOf, isOptionalNullable, isUuid } from '$lib/valueGuards';

import runtimeContract from '$lib/runtimeContract.fixture.json';

import catalogContract from '$lib/catalog/catalogContract.fixture.json';

import { isFiniteDateTime, isNonemptyString, isNonnegativeInteger, isOneOf, isRecord } from '$lib/valueGuards';
import { isDecimal, isNonnegativeDecimal, isPositiveDecimal } from '$lib/decimalGuards';

import { isWalletAddress } from '$lib/wallets';

import { isGraphCatalog, isNodeGraph } from '$lib/api/responseValidation/graph';

const RUN_STATUSES = Object.values(runtimeContract.runStatus.values);

const VALUATION_STATUSES = Object.values(runtimeContract.valuationStatus);

const STREAM_RELATIONS = Object.values(runtimeContract.streamRelation);

const SELECTION_MODES = Object.values(catalogContract.selectionMode);

const DEFINITION_LABELS = Object.values(catalogContract.botDefinitionLabel);

export function isMarketSuggestion(value: Record<string, unknown>): boolean {
  return (
    isNonemptyString(value.slug) &&
    isNonemptyString(value.condition_id) &&
    isNonemptyString(value.question) &&
    (value.event_title === null || isNonemptyString(value.event_title)) &&
    (value.end_date === null || isFiniteDateTime(value.end_date)) &&
    typeof value.is_open_for_trading === 'boolean'
  );
}

export function isMarketSearchResults(value: Record<string, unknown>): boolean {
  return (
    Array.isArray(value.markets) &&
    isArrayOf(value.markets, isMarketSuggestion) &&
    value.markets.length <= catalogContract.marketSearch.maximumLimit &&
    value.markets.every((market) => market.is_open_for_trading === true) &&
    typeof value.has_more === 'boolean'
  );
}

export function isDefinition(value: Record<string, unknown>): boolean {
  return (
    isNonemptyString(value.definition_id) &&
    isNonemptyString(value.display_name) &&
    isNonemptyString(value.description) &&
    isOneOf(value.label, DEFINITION_LABELS) &&
    isRecord(value.input_schema) &&
    isOneOf(value.market_selection, SELECTION_MODES) &&
    isOneOf(value.wallet_selection, SELECTION_MODES) &&
    (value.graph_catalog === undefined ||
      value.graph_catalog === null ||
      isGraphCatalog(value.graph_catalog)) &&
    (value.graph_examples === undefined ||
      isArrayOf(
        value.graph_examples,
        (example) =>
          isNonemptyString(example.name) &&
          isNonemptyString(example.description) &&
          isNodeGraph(example.graph),
      )) &&
    (value.starter_graph === undefined ||
      value.starter_graph === null ||
      isNodeGraph(value.starter_graph))
  );
}

export function isBot(value: Record<string, unknown>): boolean {
  return (
    isUuid(value.id) &&
    isNonemptyString(value.definition_id) &&
    isFiniteDateTime(value.created_at) &&
    isFiniteDateTime(value.updated_at) &&
    isRecord(value.config) &&
    isPaperConfig(value.config) &&
    (value.latest_graph_revision === null ||
      value.latest_graph_revision === undefined ||
      isGraphRevision(value.latest_graph_revision))
  );
}

export function isRun(value: Record<string, unknown>): boolean {
  return (
    isUuid(value.id) &&
    isUuid(value.bot_id) &&
    isNonemptyString(value.definition_id) &&
    isFiniteDateTime(value.created_at) &&
    isOneOf(value.status, RUN_STATUSES) &&
    isRecord(value.config) &&
    isPaperConfig(value.config) &&
    isOptionalNullable(value.bot_graph_revision_id, isUuid) &&
    isOptionalNullable(
      value.graph_revision,
      (revision) =>
        isNonnegativeInteger(revision) && revision >= runtimeContract.minimumGraphRevisionNumber,
    ) &&
    isOptionalNullable(value.started_at, isFiniteDateTime) &&
    isOptionalNullable(value.ended_at, isFiniteDateTime) &&
    isOptionalNullable(value.heartbeat_at, isFiniteDateTime) &&
    isOptionalNullable(value.failure_detail, (detail) => typeof detail === 'string') &&
    isOptionalNullable(value.latest_runtime_failure, (detail) => typeof detail === 'string') &&
    isOptionalNullable(value.latest_equity, isDecimal) &&
    (value.equity_status === null ||
      value.equity_status === undefined ||
      isOneOf(value.equity_status, VALUATION_STATUSES)) &&
    (value.graph === null || value.graph === undefined || isNodeGraph(value.graph))
  );
}

export function isGraphTemplate(value: Record<string, unknown>): boolean {
  return (
    isUuid(value.id) &&
    isNonemptyString(value.name) &&
    value.name.length <= catalogContract.graphTemplate.maximumNameLength &&
    isFiniteDateTime(value.created_at) &&
    isFiniteDateTime(value.updated_at) &&
    isNodeGraph(value.graph)
  );
}

export function isGraphRevision(value: unknown): boolean {
  return (
    isRecord(value) &&
    isUuid(value.id) &&
    isUuid(value.bot_id) &&
    isNonnegativeInteger(value.revision) &&
    value.revision >= runtimeContract.minimumGraphRevisionNumber &&
    isFiniteDateTime(value.created_at) &&
    isNodeGraph(value.graph)
  );
}

export function isHealthResponse(value: Record<string, unknown>): boolean {
  return value.status === runtimeContract.healthStatus;
}

function isPaperConfig(value: Record<string, unknown>): boolean {
  return (
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

function isStreamRule(value: unknown): boolean {
  if (
    !isRecord(value) ||
    !isOneOf(value.relation, STREAM_RELATIONS) ||
    !isOptionalStringArray(value.market_slugs) ||
    !isOptionalWalletArray(value.wallet_addresses)
  )
    return false;
  const selectorGroupCount =
    Number(hasSelectors(value.market_slugs)) + Number(hasSelectors(value.wallet_addresses));
  const relation = value.relation as keyof typeof runtimeContract.streamRule.minimumSelectorGroups;
  return selectorGroupCount >= runtimeContract.streamRule.minimumSelectorGroups[relation];
}

function isOptionalStringArray(value: unknown): boolean {
  return value === undefined || (Array.isArray(value) && value.every(isNonemptyString));
}

function isOptionalWalletArray(value: unknown): boolean {
  return value === undefined || (Array.isArray(value) && value.every(isWalletAddress));
}

function hasSelectors(value: unknown): boolean {
  return Array.isArray(value) && value.length > 0;
}
