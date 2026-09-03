import type {
  GraphBrokerActionDescriptor,
  GraphComparisonDescriptor,
  GraphConstantDescriptor,
  GraphNodeCatalog,
  GraphTriggerDescriptor,
  NodeGraph
} from '$lib/api/generated';
import catalogContract from './catalogContract.fixture.json';
import thresholdBuyGraph from '../../../../tests/fixtures/control_plane/threshold_buy_graph.json';
import { GRAPH_NODE_TYPE, GRAPH_SCALAR_TYPE } from './graphContracts';

export const TEST_GRAPH_CATALOG = catalogContract.graphNodeCatalog as GraphNodeCatalog;

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
  (descriptor) => descriptor.scalar_type === GRAPH_SCALAR_TYPE.decimal,
  'decimal constant'
);
export const BOOLEAN_CONSTANT: GraphConstantDescriptor = requireDescriptor(
  TEST_GRAPH_CATALOG.constants,
  (descriptor) => descriptor.scalar_type === GRAPH_SCALAR_TYPE.boolean,
  'boolean constant'
);
export const LESS_THAN_OR_EQUAL: GraphComparisonDescriptor = requireDescriptor(
  TEST_GRAPH_CATALOG.comparisons,
  (descriptor) => descriptor.operator
    === catalogContract.graphComparisonOperator.LESS_THAN_OR_EQUAL,
  'less-than-or-equal comparison'
);
export const EQUAL_COMPARISON: GraphComparisonDescriptor = requireDescriptor(
  TEST_GRAPH_CATALOG.comparisons,
  (descriptor) => descriptor.operator
    === catalogContract.graphComparisonOperator.EQUAL,
  'equal comparison'
);
export const BUY_ACTION: GraphBrokerActionDescriptor = requireDescriptor(
  TEST_GRAPH_CATALOG.broker_actions,
  (descriptor) => descriptor.action
    === catalogContract.graphBrokerAction.SUBMIT_BUY,
  'buy action'
);
export const SELL_ACTION: GraphBrokerActionDescriptor = requireDescriptor(
  TEST_GRAPH_CATALOG.broker_actions,
  (descriptor) => descriptor.action
    === catalogContract.graphBrokerAction.SUBMIT_SELL,
  'sell action'
);

export function graphFieldHandle(
  trigger: GraphTriggerDescriptor,
  path: string
): string {
  const field = trigger.payload?.fields.find(
    (candidate) =>
      candidate.path.segments.join(catalogContract.graphFieldPathSeparator) === path
  );
  if (!field) throw new Error(`Missing graph field fixture: ${path}`);
  return field.handle_id;
}

export const TEST_GRAPH: NodeGraph = {
  nodes: [
    {
      id: 'on-book-trigger',
      type: GRAPH_NODE_TYPE.trigger,
      position: { x: 80, y: 80 },
      data: { hook_name: ON_BOOK_TRIGGER.hook_name }
    }
  ],
  edges: []
};

export const THRESHOLD_BUY_GRAPH = thresholdBuyGraph as NodeGraph;
