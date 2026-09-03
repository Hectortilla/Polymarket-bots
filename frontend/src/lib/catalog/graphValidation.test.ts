import { describe, expect, it } from 'vitest';

import type { NodeGraph } from '$lib/api/generated';
import { GRAPH_NODE_TYPE, GRAPH_SCALAR_TYPE } from './graphContracts';
import { GRAPH_VALIDATION_COPY, graphValidationIssues } from './graphValidation';

const GRAPH = {
  nodes: [
    {
      id: 'trigger-on-book',
      type: GRAPH_NODE_TYPE.trigger,
      position: { x: 0, y: 0 },
      data: { hook_name: 'on_book' }
    },
    {
      id: 'constant-decimal',
      type: GRAPH_NODE_TYPE.constant,
      position: { x: 200, y: 0 },
      data: { scalar_type: GRAPH_SCALAR_TYPE.decimal, value: '1.0' }
    }
  ],
  edges: []
} satisfies NodeGraph;

describe('graph validation presentation', () => {
  it('locates node field errors in the visual graph', () => {
    const issues = graphValidationIssues(
      {
        detail: [
          {
            loc: ['body', 'graph', 'nodes', 1, 'constant', 'data', 'decimal', 'value'],
            msg: 'Value error, decimal graph constants must be finite decimal strings',
            type: 'value_error'
          }
        ]
      },
      GRAPH
    );

    expect(issues).toEqual([
      {
        location: 'Node 2: Decimal constant, Value',
        message: 'Decimal graph constants must be finite decimal strings.'
      }
    ]);
  });

  it('keeps model-level topology failures attached to the graph', () => {
    const issues = graphValidationIssues(
      {
        detail: [
          {
            loc: ['body', 'graph'],
            msg: 'Value error, graph input cardinality is invalid',
            type: 'value_error'
          }
        ]
      },
      GRAPH
    );

    expect(issues[0]).toEqual({
      location: GRAPH_VALIDATION_COPY.STRUCTURE,
      message: 'Graph input cardinality is invalid.'
    });
  });
});
