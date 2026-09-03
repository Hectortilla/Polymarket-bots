import { client } from './generated/client.gen';
import runtimeContract from '$lib/runtimeContract.fixture.json';
import catalogContract from '$lib/catalog/catalogContract.fixture.json';
import { GRAPH_NODE_TYPE } from '$lib/catalog/graphContracts';
import { nodeGraphContractIsValid } from '$lib/catalog/runtimeGraphValidation';
import {
  isPersistedEventId,
  persistedDurableEvent,
  persistedEventPage
} from '$lib/runs/durableEvents';
import { liveRunEvent } from '$lib/runs/events';
import {
  isDecimal,
  isFiniteDateTime,
  isNonemptyString,
  isNonnegativeDecimal,
  isNonnegativeInteger,
  isOneOf,
  isPositiveDecimal,
  isRecord
} from '$lib/valueGuards';
import { isWalletAddress } from '$lib/wallets';

const RUN_STATUSES = Object.values(runtimeContract.runStatus.values);
const VALUATION_STATUSES = Object.values(runtimeContract.valuationStatus);
const STREAM_RELATIONS = Object.values(runtimeContract.streamRelation);
const SELECTION_MODES = Object.values(catalogContract.selectionMode);
const DEFINITION_LABELS = Object.values(catalogContract.botDefinitionLabel);
const GRAPH_SCALAR_TYPES = Object.values(catalogContract.graphScalarType);
const GRAPH_COMPARISON_OPERATORS = Object.values(
  catalogContract.graphComparisonOperator
);
const GRAPH_BROKER_ACTIONS = Object.values(catalogContract.graphBrokerAction);
let responseInterceptorConfigured = false;

export function configureApiResponseValidation(): void {
  if (!responseInterceptorConfigured) {
    client.interceptors.response.use(validateOperationResponse);
    responseInterceptorConfigured = true;
  }
  client.setConfig({ responseValidator: validateControlPlaneResponse });
}

export async function validateControlPlaneResponse(data: unknown): Promise<void> {
  const valid = Array.isArray(data)
    ? data.every(isListItem)
    : isRecord(data) && isObjectResponse(data);
  if (!valid) throw new Error('Control-plane response failed runtime validation');
}

function isListItem(value: unknown): boolean {
  return isRecord(value) && (
    isDefinition(value)
    || isBot(value)
    || isRun(value)
    || isGraphTemplate(value)
  );
}

function isObjectResponse(value: Record<string, unknown>): boolean {
  return isDefinition(value)
    || isRun(value)
    || isBot(value)
    || isGraphTemplate(value)
    || isGraphRevision(value)
    || isEventPage(value)
    || isRunEvent(value)
    || isHealthResponse(value);
}

function isDefinition(value: Record<string, unknown>): boolean {
  return isNonemptyString(value.definition_id)
    && isNonemptyString(value.display_name)
    && isNonemptyString(value.description)
    && isOneOf(value.label, DEFINITION_LABELS)
    && isRecord(value.input_schema)
    && isOneOf(value.market_selection, SELECTION_MODES)
    && isOneOf(value.wallet_selection, SELECTION_MODES)
    && (value.graph_catalog === undefined
      || value.graph_catalog === null
      || isGraphCatalog(value.graph_catalog))
    && (value.starter_graph === undefined
      || value.starter_graph === null
      || isNodeGraph(value.starter_graph));
}

function isBot(value: Record<string, unknown>): boolean {
  return isUuid(value.id)
    && isNonemptyString(value.definition_id)
    && isFiniteDateTime(value.created_at)
    && isFiniteDateTime(value.updated_at)
    && isRecord(value.config)
    && isPaperConfig(value.config)
    && (value.latest_graph_revision === null
      || value.latest_graph_revision === undefined
      || isGraphRevision(value.latest_graph_revision));
}

function isRun(value: Record<string, unknown>): boolean {
  return isUuid(value.id)
    && isUuid(value.bot_id)
    && isNonemptyString(value.definition_id)
    && isFiniteDateTime(value.created_at)
    && isOneOf(value.status, RUN_STATUSES)
    && isRecord(value.config)
    && isPaperConfig(value.config)
    && isOptionalNullable(value.bot_graph_revision_id, isUuid)
    && isOptionalNullable(
      value.graph_revision,
      (revision) => isNonnegativeInteger(revision)
        && revision >= runtimeContract.minimumGraphRevisionNumber
    )
    && isOptionalNullable(value.started_at, isFiniteDateTime)
    && isOptionalNullable(value.ended_at, isFiniteDateTime)
    && isOptionalNullable(value.heartbeat_at, isFiniteDateTime)
    && isOptionalNullable(value.failure_detail, (detail) => typeof detail === 'string')
    && isOptionalNullable(value.latest_equity, isDecimal)
    && (value.equity_status === null
      || value.equity_status === undefined
      || isOneOf(value.equity_status, VALUATION_STATUSES))
    && (value.graph === null || value.graph === undefined || isNodeGraph(value.graph));
}

function isGraphTemplate(value: Record<string, unknown>): boolean {
  return isUuid(value.id)
    && isNonemptyString(value.name)
    && value.name.length <= catalogContract.graphTemplate.maximumNameLength
    && isFiniteDateTime(value.created_at)
    && isFiniteDateTime(value.updated_at)
    && isNodeGraph(value.graph);
}

function isGraphRevision(value: unknown): boolean {
  return isRecord(value)
    && isUuid(value.id)
    && isUuid(value.bot_id)
    && isNonnegativeInteger(value.revision)
    && value.revision >= runtimeContract.minimumGraphRevisionNumber
    && isFiniteDateTime(value.created_at)
    && isNodeGraph(value.graph);
}

function isPaperConfig(value: Record<string, unknown>): boolean {
  return isNonemptyString(value.name)
    && isPositiveDecimal(value.paper_portfolio_usdc)
    && isPositiveDecimal(value.max_order_size)
    && isNonnegativeDecimal(value.max_slippage_pct)
    && isNonnegativeInteger(value.paper_latency_ms)
    && isNonnegativeInteger(value.paper_latency_jitter_ms)
    && isNonnegativeInteger(value.event_max_age_ms)
    && isNonnegativeInteger(value.data_trades_budget_per_10s)
    && value.data_trades_budget_per_10s
      >= runtimeContract.config.minimumDataTradesBudget
    && value.data_trades_budget_per_10s <= runtimeContract.config.maximumDataTradesBudget
    && Array.isArray(value.stream_rules)
    && value.stream_rules.every(isStreamRule);
}

function isNodeGraph(value: unknown): boolean {
  if (!isRecord(value)
    || !Array.isArray(value.nodes)
    || value.nodes.length < catalogContract.nodeGraph.minimumNodes) {
    return false;
  }
  if (!value.nodes.every(isGraphNode)) return false;
  const edgesAreValid = value.edges === undefined || (
    Array.isArray(value.edges)
    && value.edges.every((edge) => isRecord(edge)
      && isGraphEdgeIdentifier(edge.id)
      && isGraphIdentifier(edge.source)
      && isGraphIdentifier(edge.source_handle)
      && isGraphIdentifier(edge.target)
      && isGraphIdentifier(edge.target_handle))
  );
  return edgesAreValid && nodeGraphContractIsValid(value as unknown as import('$lib/api/generated').NodeGraph);
}

function isGraphNode(node: unknown): boolean {
  if (!isRecord(node)
    || !isGraphIdentifier(node.id)
    || !Object.values(GRAPH_NODE_TYPE).includes(node.type as never)
    || !isRecord(node.position)
    || !isGraphCoordinate(node.position.x)
    || !isGraphCoordinate(node.position.y)
    || !isRecord(node.data)) return false;
  switch (node.type) {
    case GRAPH_NODE_TYPE.trigger:
      return isGraphHookName(node.data.hook_name);
    case GRAPH_NODE_TYPE.constant:
      return isConstantNodeData(node.data);
    case GRAPH_NODE_TYPE.comparison:
      return isOneOf(node.data.operator, GRAPH_COMPARISON_OPERATORS);
    case GRAPH_NODE_TYPE.brokerAction:
      return isOneOf(node.data.action, GRAPH_BROKER_ACTIONS);
    default:
      return false;
  }
}

function isConstantNodeData(data: Record<string, unknown>): boolean {
  if (!isOneOf(data.scalar_type, GRAPH_SCALAR_TYPES)) return false;
  return isScalarValue(data.scalar_type, data.value);
}

function isScalarValue(scalarType: string, value: unknown): boolean {
  switch (scalarType) {
    case catalogContract.graphScalarType.BOOLEAN:
      return typeof value === 'boolean';
    case catalogContract.graphScalarType.INTEGER:
      return typeof value === 'number' && Number.isSafeInteger(value);
    case catalogContract.graphScalarType.DECIMAL:
      return typeof value === 'string' && isFiniteDecimal(value);
    case catalogContract.graphScalarType.STRING:
      return typeof value === 'string';
    default:
      return false;
  }
}

function isStreamRule(value: unknown): boolean {
  if (!isRecord(value)
    || !isOneOf(value.relation, STREAM_RELATIONS)
    || !isOptionalStringArray(value.market_slugs)
    || !isOptionalWalletArray(value.wallet_addresses)) return false;
  const selectorGroupCount = Number(hasSelectors(value.market_slugs))
    + Number(hasSelectors(value.wallet_addresses));
  const relation = value.relation as keyof typeof runtimeContract.streamRule.minimumSelectorGroups;
  return selectorGroupCount
    >= runtimeContract.streamRule.minimumSelectorGroups[relation];
}

function isOptionalStringArray(value: unknown): boolean {
  return value === undefined || (
    Array.isArray(value) && value.every(isNonemptyString)
  );
}

function isOptionalWalletArray(value: unknown): boolean {
  return value === undefined || (
    Array.isArray(value) && value.every(isWalletAddress)
  );
}

function hasSelectors(value: unknown): boolean {
  return Array.isArray(value) && value.length > 0;
}

function isGraphIdentifier(value: unknown): value is string {
  return isTrimmedStringWithinLimit(
    value,
    catalogContract.nodeGraph.maximumIdentifierLength
  );
}

function isGraphEdgeIdentifier(value: unknown): value is string {
  return isTrimmedStringWithinLimit(
    value,
    catalogContract.nodeGraph.maximumEdgeIdentifierLength
  );
}

function isTrimmedStringWithinLimit(value: unknown, maximumLength: number): value is string {
  return typeof value === 'string'
    && value === value.trim()
    && value.length >= catalogContract.nodeGraph.minimumIdentifierLength
    && value.length <= maximumLength;
}

function isGraphHookName(value: unknown): value is string {
  return isGraphIdentifier(value)
    && new RegExp(catalogContract.nodeGraph.hookNamePattern).test(value);
}

function isGraphCoordinate(value: unknown): value is number {
  return isFiniteNumber(value)
    && Math.abs(value) <= catalogContract.nodeGraph.coordinateLimit;
}

function isGraphCatalog(value: unknown): boolean {
  if (!isRecord(value)
    || !isArrayOf(value.triggers, isTriggerDescriptor)
    || !isArrayOf(value.constants, isConstantDescriptor)
    || !isArrayOf(value.comparisons, isComparisonDescriptor)
    || !isArrayOf(value.broker_actions, isBrokerActionDescriptor)) return false;
  return hasUniqueValues(value.triggers, 'hook_name')
    && hasUniqueValues(value.constants, 'scalar_type')
    && hasUniqueValues(value.comparisons, 'operator')
    && hasUniqueValues(value.broker_actions, 'action');
}

function hasUniqueValues(
  values: unknown,
  key: string
): boolean {
  if (!Array.isArray(values) || !values.every(isRecord)) return false;
  const observed = values.map((value) => value[key]);
  return new Set(observed).size === observed.length;
}

function isTriggerDescriptor(value: Record<string, unknown>): boolean {
  const canonicalDescriptor = catalogContract.graphNodeCatalog.triggers.find(
    (descriptor) => descriptor.hook_name === value.hook_name
  );
  return canonicalDescriptor !== undefined
    && value.node_type === canonicalDescriptor.node_type
    && value.context_handle_id === canonicalDescriptor.context_handle_id
    && value.context_type_name === canonicalDescriptor.context_type_name
    && isGraphHookName(value.hook_name)
    && (value.payload === undefined
      || value.payload === null
      || isGraphPayloadDescriptor(value.payload));
}

function isGraphPayloadDescriptor(value: unknown): boolean {
  return isRecord(value)
    && isNonemptyString(value.type_name)
    && Array.isArray(value.fields)
    && value.fields.every((field) => isRecord(field)
      && isGraphIdentifier(field.handle_id)
      && isNonemptyString(field.display_name)
      && isRecord(field.path)
      && Array.isArray(field.path.segments)
      && field.path.segments.length
        >= catalogContract.nodeGraph.minimumFieldPathSegments
      && field.path.segments.every(isGraphFieldPathSegment)
      && isNonemptyString(field.value_type)
      && (field.scalar_type === null
        || isOneOf(field.scalar_type, GRAPH_SCALAR_TYPES))
      && typeof field.nullable === 'boolean'
      && typeof field.collection === 'boolean'
      && isRecord(field.value_schema));
}

function isConstantDescriptor(value: Record<string, unknown>): boolean {
  const canonicalDescriptor = catalogContract.graphNodeCatalog.constants.find(
    (descriptor) => descriptor.scalar_type === value.scalar_type
  );
  return canonicalDescriptor !== undefined
    && value.node_type === canonicalDescriptor.node_type
    && isNonemptyString(value.display_name)
    && isOneOf(value.scalar_type, GRAPH_SCALAR_TYPES)
    && isScalarValue(value.scalar_type, value.default_value)
    && isRecord(value.output)
    && isGraphOutputDescriptor(value.output);
}

function isComparisonDescriptor(value: Record<string, unknown>): boolean {
  const canonicalDescriptor = catalogContract.graphNodeCatalog.comparisons.find(
    (descriptor) => descriptor.operator === value.operator
  );
  return isNonemptyString(value.display_name)
    && isOneOf(value.operator, GRAPH_COMPARISON_OPERATORS)
    && canonicalDescriptor !== undefined
    && value.node_type === canonicalDescriptor.node_type
    && Array.isArray(value.inputs)
    && value.inputs.length === canonicalDescriptor.inputs.length
    && value.inputs.every(isGraphInputDescriptor)
    && isRecord(value.output)
    && isGraphOutputDescriptor(value.output);
}

function isBrokerActionDescriptor(value: Record<string, unknown>): boolean {
  const canonicalDescriptor = catalogContract.graphNodeCatalog.broker_actions.find(
    (descriptor) => descriptor.action === value.action
  );
  return canonicalDescriptor !== undefined
    && value.node_type === canonicalDescriptor.node_type
    && isNonemptyString(value.display_name)
    && isOneOf(value.action, GRAPH_BROKER_ACTIONS)
    && value.method_name === catalogContract.graphBrokerSubmitMethodName
    && isOneOf(value.side, Object.values(runtimeContract.side))
    && Array.isArray(value.inputs)
    && value.inputs.every(isGraphInputDescriptor);
}

function isGraphInputDescriptor(value: unknown): boolean {
  return isRecord(value)
    && isGraphIdentifier(value.handle_id)
    && isNonemptyString(value.display_name)
    && Array.isArray(value.scalar_types)
    && value.scalar_types.length
      >= catalogContract.nodeGraph.minimumInputScalarTypes
    && value.scalar_types.every((type) => isOneOf(type, GRAPH_SCALAR_TYPES))
    && typeof value.nullable === 'boolean'
    && typeof value.required === 'boolean';
}

function isGraphOutputDescriptor(value: Record<string, unknown>): boolean {
  return isGraphIdentifier(value.handle_id)
    && isNonemptyString(value.display_name)
    && isOneOf(value.scalar_type, GRAPH_SCALAR_TYPES)
    && (value.nullable === undefined || typeof value.nullable === 'boolean');
}

function isGraphFieldPathSegment(value: unknown): value is string {
  return isGraphIdentifier(value)
    && new RegExp(catalogContract.graphFieldPathSegmentPattern).test(value);
}

function isEventPage(
  value: Record<string, unknown>,
  expectedRunId?: string
): boolean {
  if (!Array.isArray(value.events)) return false;
  if (value.next_before_event_id !== null
    && !isPersistedEventId(value.next_before_event_id)) return false;
  if (expectedRunId !== undefined) {
    return persistedEventPage(value, expectedRunId) !== null;
  }
  return value.events.every((event) => isRecord(event)
    && typeof event.run_id === 'string'
    && persistedDurableEvent(event, event.run_id) !== null);
}

function isRunEvent(value: Record<string, unknown>): boolean {
  if (!isNonemptyString(value.run_id)) return false;
  try {
    if (value.id !== undefined) {
      return persistedDurableEvent(value, value.run_id) !== null;
    }
    return liveRunEvent(value, value.run_id) !== null;
  } catch {
    return false;
  }
}

async function validateOperationResponse(
  response: Response,
  _request: Request,
  options: {
    url: string;
    method?: string;
    path?: Record<string, unknown>;
  }
): Promise<Response> {
  if (!response.ok || options.url === runtimeContract.apiPaths.runEventsStream) {
    return response;
  }
  const contentType = response.headers.get('Content-Type') ?? '';
  if (!contentType.toLowerCase().includes('application/json')) {
    throw new Error('Control-plane response must use application/json');
  }
  const body = await response.clone().text();
  if (!body) throw new Error('Control-plane response body must not be empty');
  const data: unknown = JSON.parse(body);
  if (!isExpectedOperationResponse(
    options.url,
    options.method,
    options.path,
    data
  )) {
    throw new Error('Control-plane response failed operation validation');
  }
  return response;
}

function isExpectedOperationResponse(
  url: string,
  method: string | undefined,
  path: Record<string, unknown> | undefined,
  data: unknown
): boolean {
  const paths = runtimeContract.apiPaths;
  if (url === paths.botDefinitions) return isArrayOf(data, isDefinition);
  if (url === paths.bots) {
    return method === 'GET' ? isArrayOf(data, isBot) : isRecord(data) && isBot(data);
  }
  if (url === paths.botGraphRevision || url === paths.botGraphRevisions) {
    return isRecord(data) && isGraphRevision(data);
  }
  if (url === paths.bot) return isRecord(data) && isBot(data);
  if (url === paths.botRuns) return isRecord(data) && isRun(data);
  if (url === paths.graphTemplates) {
    return method === 'GET'
      ? isArrayOf(data, isGraphTemplate)
      : isRecord(data) && isGraphTemplate(data);
  }
  if (url === paths.graphTemplate) {
    return isRecord(data) && isGraphTemplate(data);
  }
  if (url === paths.health) return isRecord(data) && isHealthResponse(data);
  if (url === paths.runs) return isArrayOf(data, isRun);
  if (url === paths.run || url === paths.runStop) {
    return isRecord(data) && isRun(data);
  }
  if (url === paths.runEvents) {
    const runId = path?.run_id;
    return typeof runId === 'string'
      && isRecord(data)
      && isEventPage(data, runId);
  }
  return false;
}

function isArrayOf(
  data: unknown,
  predicate: (value: Record<string, unknown>) => boolean
): boolean {
  return Array.isArray(data)
    && data.every((value) => isRecord(value) && predicate(value));
}

function isHealthResponse(value: Record<string, unknown>): boolean {
  return value.status === runtimeContract.healthStatus;
}

function isUuid(value: unknown): value is string {
  return typeof value === 'string'
    && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function isFiniteDecimal(value: string): boolean {
  const numeric = Number(value);
  return value.trim() !== '' && Number.isFinite(numeric);
}

function isOptionalNullable(
  value: unknown,
  predicate: (candidate: unknown) => boolean
): boolean {
  return value === undefined || value === null || predicate(value);
}
