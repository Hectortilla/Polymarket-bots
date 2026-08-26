import type {
  BotDefinitionDescriptor,
  GraphFieldDescriptor,
  GraphNodeCatalog,
  GraphTriggerDescriptor,
  NodeGraph
} from '$lib/api/generated';
import { SELECTION_MODE, WIDGET_KIND, WIDGET_SCHEMA_KEY } from './schema';

const BIDS_FIELD: GraphFieldDescriptor = {
  path: { segments: ['bids'] },
  handle_id: 'field:bids',
  display_name: 'BookSnapshot.bids',
  value_type: 'BookLevel',
  nullable: false,
  collection: true,
  value_schema: { type: 'array' }
};

const ASKS_FIELD: GraphFieldDescriptor = {
  path: { segments: ['asks'] },
  handle_id: 'field:asks',
  display_name: 'BookSnapshot.asks',
  value_type: 'BookLevel',
  nullable: false,
  collection: true,
  value_schema: { type: 'array' }
};

const SIZE_FIELD: GraphFieldDescriptor = {
  path: { segments: ['size'] },
  handle_id: 'field:size',
  display_name: 'WalletTradeEvent.size',
  value_type: 'Decimal',
  nullable: false,
  collection: false,
  value_schema: { type: 'string' }
};

export const ON_START_TRIGGER: GraphTriggerDescriptor = {
  hook_name: 'on_start',
  context_handle_id: 'context',
  context_type_name: 'BotContext',
  payload: null
};

export const ON_BOOK_TRIGGER: GraphTriggerDescriptor = {
  hook_name: 'on_book',
  context_handle_id: 'context',
  context_type_name: 'BotContext',
  payload: {
    type_name: 'BookSnapshot',
    fields: [BIDS_FIELD, ASKS_FIELD]
  }
};

export const ON_WALLET_TRADE_TRIGGER: GraphTriggerDescriptor = {
  hook_name: 'on_wallet_trade',
  context_handle_id: 'context',
  context_type_name: 'BotContext',
  payload: {
    type_name: 'WalletTradeEvent',
    fields: [SIZE_FIELD]
  }
};

export const TEST_GRAPH_CATALOG: GraphNodeCatalog = {
  node_type: 'trigger',
  triggers: [ON_START_TRIGGER, ON_BOOK_TRIGGER, ON_WALLET_TRADE_TRIGGER]
};

export const TEST_GRAPH: NodeGraph = {
  schema_version: 1,
  nodes: [
    {
      id: 'on-book-trigger',
      type: 'trigger',
      position: { x: 80, y: 80 },
      data: {
        hook_name: 'on_book',
        selected_output_paths: [{ segments: ['bids'] }]
      }
    }
  ],
  edges: []
};

export function graphDescriptor(
  graph: NodeGraph = TEST_GRAPH,
  definitionId = 'node-based-test'
): BotDefinitionDescriptor {
  return {
    definition_id: definitionId,
    version: 1,
    display_name: 'Node based test',
    description: 'Test definition',
    label: 'non_trading',
    market_selection: SELECTION_MODE.userConfigured,
    wallet_selection: SELECTION_MODE.absent,
    graph_catalog: TEST_GRAPH_CATALOG,
    input_schema: {
      type: 'object',
      additionalProperties: false,
      required: ['name', 'market_slugs', 'graph'],
      properties: {
        name: { type: 'string', minLength: 1 },
        market_slugs: {
          type: 'array',
          minItems: 1,
          items: { type: 'string' },
          [WIDGET_SCHEMA_KEY]: WIDGET_KIND.marketSlugs
        },
        graph: {
          type: 'object',
          default: graph,
          required: ['schema_version', 'nodes', 'edges'],
          properties: {
            schema_version: { const: 1 },
            nodes: { type: 'array', minItems: 1 },
            edges: { type: 'array', maxItems: 0 }
          },
          additionalProperties: false,
          [WIDGET_SCHEMA_KEY]: WIDGET_KIND.nodeGraph
        }
      }
    }
  };
}
