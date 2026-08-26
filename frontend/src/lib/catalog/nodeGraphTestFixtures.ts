import type {
  BotDefinitionDescriptor,
  GraphBrokerActionDescriptor,
  GraphComparisonDescriptor,
  GraphConstantDescriptor,
  GraphNodeCatalog,
  GraphTriggerDescriptor,
  NodeGraph
} from '$lib/api/generated';
import graphNodeCatalog from './graphNodeCatalog.fixture.json';
import thresholdBuyGraph from '../../../../tests/fixtures/control_plane/threshold_buy_graph.json';
import { SELECTION_MODE, WIDGET_KIND, WIDGET_SCHEMA_KEY } from './schema';
import { GRAPH_NODE_TYPE } from './nodeGraph';

export const TEST_GRAPH_CATALOG = graphNodeCatalog as GraphNodeCatalog;

function requireDescriptor<T>(
  descriptors: T[],
  matches: (descriptor: T) => boolean,
  description: string
): T {
  const descriptor = descriptors.find(matches);
  if (!descriptor) throw new Error(`Missing graph catalog fixture: ${description}`);
  return descriptor;
}

export const ON_START_TRIGGER: GraphTriggerDescriptor = requireDescriptor(
  TEST_GRAPH_CATALOG.triggers,
  (descriptor) => descriptor.hook_name === 'on_start',
  'on_start trigger'
);
export const ON_BOOK_TRIGGER: GraphTriggerDescriptor = requireDescriptor(
  TEST_GRAPH_CATALOG.triggers,
  (descriptor) => descriptor.hook_name === 'on_book',
  'on_book trigger'
);
export const ON_WALLET_TRADE_TRIGGER: GraphTriggerDescriptor = requireDescriptor(
  TEST_GRAPH_CATALOG.triggers,
  (descriptor) => descriptor.hook_name === 'on_wallet_trade',
  'on_wallet_trade trigger'
);
export const DECIMAL_CONSTANT: GraphConstantDescriptor = requireDescriptor(
  TEST_GRAPH_CATALOG.constants,
  (descriptor) => descriptor.scalar_type === 'decimal',
  'decimal constant'
);
export const BOOLEAN_CONSTANT: GraphConstantDescriptor = requireDescriptor(
  TEST_GRAPH_CATALOG.constants,
  (descriptor) => descriptor.scalar_type === 'boolean',
  'boolean constant'
);
export const LESS_THAN_OR_EQUAL: GraphComparisonDescriptor = requireDescriptor(
  TEST_GRAPH_CATALOG.comparisons,
  (descriptor) => descriptor.operator === 'less_than_or_equal',
  'less-than-or-equal comparison'
);
export const EQUAL_COMPARISON: GraphComparisonDescriptor = requireDescriptor(
  TEST_GRAPH_CATALOG.comparisons,
  (descriptor) => descriptor.operator === 'equal',
  'equal comparison'
);
export const BUY_ACTION: GraphBrokerActionDescriptor = requireDescriptor(
  TEST_GRAPH_CATALOG.broker_actions,
  (descriptor) => descriptor.action === 'submit_buy',
  'buy action'
);

export const TEST_GRAPH: NodeGraph = {
  nodes: [
    {
      id: 'on-book-trigger',
      type: GRAPH_NODE_TYPE.trigger,
      position: { x: 80, y: 80 },
      data: { hook_name: 'on_book' }
    }
  ],
  edges: []
};

export const THRESHOLD_BUY_GRAPH = thresholdBuyGraph as NodeGraph;

export function graphDescriptor(
  graph: NodeGraph = TEST_GRAPH,
  definitionId = 'node-based-test'
): BotDefinitionDescriptor {
  return {
    definition_id: definitionId,
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
          [WIDGET_SCHEMA_KEY]: WIDGET_KIND.nodeGraph
        }
      }
    }
  };
}
