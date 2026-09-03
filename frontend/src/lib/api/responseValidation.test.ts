import { describe, expect, it, vi } from 'vitest';

import runtimeContract from '$lib/runtimeContract.fixture.json';
import catalogContract from '$lib/catalog/catalogContract.fixture.json';
import {
  BOOLEAN_CONSTANT,
  EQUAL_COMPARISON,
  graphFieldHandle,
  ON_WALLET_TRADE_TRIGGER,
  TEST_GRAPH,
  THRESHOLD_BUY_GRAPH
} from '$lib/catalog/nodeGraphTestFixtures';
import { client } from './generated/client.gen';
import {
  createBotApiV1BotsPost,
  readRunEventsApiV1RunsRunIdEventsGet
} from './generated/sdk.gen';
import {
  configureApiResponseValidation,
  validateControlPlaneResponse
} from './responseValidation';

const RUN_ID = '00000000-0000-4000-8000-000000000001';
const BOT_ID = '00000000-0000-4000-8000-000000000002';
const CREATED_AT = '2026-09-02T00:00:00Z';
const PAPER_CONFIG = {
  name: 'Winner',
  paper_portfolio_usdc: '1000',
  max_order_size: '10',
  max_slippage_pct: '0.01',
  paper_latency_ms: 0,
  paper_latency_jitter_ms: 0,
  event_max_age_ms: 5000,
  data_trades_budget_per_10s: 1,
  stream_rules: []
};
const DEFINITION = {
  definition_id: 'winner',
  display_name: 'Winner',
  description: 'Trades a resolved market.',
  label: catalogContract.botDefinitionLabel.STANDARD,
  input_schema: {},
  market_selection: catalogContract.selectionMode.USER_CONFIGURED,
  wallet_selection: catalogContract.selectionMode.ABSENT
};

describe('control-plane response validation', () => {
  it('accepts a valid run response', async () => {
    await expect(validateControlPlaneResponse({
      id: RUN_ID,
      bot_id: BOT_ID,
      definition_id: 'winner',
      created_at: CREATED_AT,
      status: runtimeContract.runStatus.values.RUNNING,
      config: PAPER_CONFIG
    })).resolves.toBeUndefined();
  });

  it('accepts every REST response family and installs the client validator', async () => {
    const graphRevision = {
      id: RUN_ID,
      bot_id: BOT_ID,
      revision: 1,
      created_at: CREATED_AT,
      graph: THRESHOLD_BUY_GRAPH
    };
    const bot = {
      id: BOT_ID,
      definition_id: 'winner',
      created_at: CREATED_AT,
      updated_at: CREATED_AT,
      config: PAPER_CONFIG,
      latest_graph_revision: graphRevision
    };
    const template = {
      id: RUN_ID,
      name: 'Starter',
      created_at: CREATED_AT,
      updated_at: CREATED_AT,
      graph: TEST_GRAPH
    };
    const eventPage = {
      events: [{
        id: runtimeContract.durableEventIds.firstEventId,
        kind: runtimeContract.eventKind.RUN_LIFECYCLE,
        run_id: RUN_ID,
        occurred_at: CREATED_AT,
        payload: { status: runtimeContract.runStatus.values.RUNNING }
      }],
      next_before_event_id: null
    };
    const liveEvent = {
      kind: runtimeContract.liveEventKind.STREAM_HEALTH,
      run_id: RUN_ID,
      occurred_at: CREATED_AT,
      payload: {
        queue_depth: 0,
        peak_queue_depth: 1,
        book_dispatch_lag_ms: null,
        book_stale: false,
        book_received_count: 2,
        book_coalesced_count: 0
      }
    };

    for (const response of [
      DEFINITION,
      bot,
      template,
      graphRevision,
      eventPage,
      liveEvent,
      { status: runtimeContract.healthStatus },
      [DEFINITION, bot, template]
    ]) {
      await expect(validateControlPlaneResponse(response)).resolves.toBeUndefined();
    }

    const setConfig = vi.spyOn(client, 'setConfig');
    configureApiResponseValidation();
    expect(setConfig).toHaveBeenCalledWith({
      responseValidator: validateControlPlaneResponse
    });
  });

  it('enforces the exact generated operation response and JSON transport', async () => {
    configureApiResponseValidation();
    const request = {
      body: { definition_id: 'winner', inputs: {} },
      baseUrl: 'http://control-plane.test',
      throwOnError: true as const
    };
    await expect(createBotApiV1BotsPost({
      ...request,
      fetch: async () => new Response(JSON.stringify({ status: 'ok' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      })
    })).rejects.toThrow('failed operation validation');
    await expect(createBotApiV1BotsPost({
      ...request,
      fetch: async () => new Response('not json', {
        status: 200,
        headers: { 'Content-Type': 'text/plain' }
      })
    })).rejects.toThrow('must use application/json');
    await expect(createBotApiV1BotsPost({
      ...request,
      fetch: async () => new Response('', {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      })
    })).rejects.toThrow('must not be empty');

    const wrongRunPage = {
      events: [{
        id: runtimeContract.durableEventIds.firstEventId,
        kind: runtimeContract.eventKind.RUN_LIFECYCLE,
        run_id: BOT_ID,
        occurred_at: CREATED_AT,
        payload: { status: runtimeContract.runStatus.values.RUNNING }
      }],
      next_before_event_id: runtimeContract.durableEventIds.firstEventId
    };
    await expect(readRunEventsApiV1RunsRunIdEventsGet({
      path: { run_id: RUN_ID },
      baseUrl: 'http://control-plane.test',
      throwOnError: true,
      fetch: async () => new Response(JSON.stringify(wrongRunPage), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      })
    })).rejects.toThrow('failed operation validation');
  });

  it('rejects malformed data before generated types are trusted', async () => {
    await expect(validateControlPlaneResponse({
      id: RUN_ID,
      status: 'running'
    })).rejects.toThrow('failed runtime validation');
    await expect(validateControlPlaneResponse({
      id: RUN_ID,
      name: 'Broken graph',
      created_at: CREATED_AT,
      updated_at: CREATED_AT,
      graph: {
        nodes: [{
          id: 'trigger',
          type: catalogContract.graphNodeType.TRIGGER,
          position: { x: 0, y: 0 },
          data: {}
        }]
      }
    })).rejects.toThrow('failed runtime validation');
    await expect(validateControlPlaneResponse({
      id: RUN_ID,
      name: 'x'.repeat(catalogContract.graphTemplate.maximumNameLength + 1),
      created_at: CREATED_AT,
      updated_at: CREATED_AT,
      graph: TEST_GRAPH
    })).rejects.toThrow('failed runtime validation');
    await expect(validateControlPlaneResponse([{ definition_id: '' }]))
      .rejects.toThrow('failed runtime validation');
    await expect(validateControlPlaneResponse({
      id: RUN_ID,
      bot_id: BOT_ID,
      definition_id: 'winner',
      created_at: CREATED_AT,
      status: runtimeContract.runStatus.values.RUNNING,
      config: {
        ...PAPER_CONFIG,
        data_trades_budget_per_10s:
          runtimeContract.config.maximumDataTradesBudget + 1
      }
    })).rejects.toThrow('failed runtime validation');
    await expect(validateControlPlaneResponse({
      ...DEFINITION,
      graph_catalog: {
        ...catalogContract.graphNodeCatalog,
        comparisons: [
          ...catalogContract.graphNodeCatalog.comparisons,
          catalogContract.graphNodeCatalog.comparisons[0]
        ]
      }
    })).rejects.toThrow('failed runtime validation');
    const triggerWithPayload = catalogContract.graphNodeCatalog.triggers.find(
      (trigger) => trigger.payload && trigger.payload.fields.length > 0
    );
    if (!triggerWithPayload?.payload) {
      throw new Error('generated graph catalog requires a payload field fixture');
    }
    const fieldWithoutValueSchema = {
      ...triggerWithPayload.payload.fields[0],
      value_schema: undefined
    };
    await expect(validateControlPlaneResponse({
      ...DEFINITION,
      graph_catalog: {
        ...catalogContract.graphNodeCatalog,
        triggers: [{
          ...triggerWithPayload,
          payload: {
            ...triggerWithPayload.payload,
            fields: [fieldWithoutValueSchema]
          }
        }]
      }
    })).rejects.toThrow('failed runtime validation');
    await expect(validateControlPlaneResponse({
      ...DEFINITION,
      graph_catalog: {
        ...catalogContract.graphNodeCatalog,
        triggers: [{
          ...triggerWithPayload,
          payload: {
            ...triggerWithPayload.payload,
            fields: [{
              ...triggerWithPayload.payload.fields[0],
              path: { segments: ['invalid segment'] }
            }]
          }
        }]
      }
    })).rejects.toThrow('failed runtime validation');
    await expect(validateControlPlaneResponse({
      id: BOT_ID,
      definition_id: 'winner',
      created_at: CREATED_AT,
      updated_at: CREATED_AT,
      config: PAPER_CONFIG,
      latest_graph_revision: {
        id: RUN_ID,
        bot_id: BOT_ID,
        revision: 1,
        created_at: CREATED_AT,
        graph: { ...TEST_GRAPH, edges: [{ id: 'incomplete' }] }
      }
    })).rejects.toThrow('failed runtime validation');
    await expect(validateControlPlaneResponse({
      events: [{
        id: runtimeContract.durableEventIds.firstCursor,
        kind: runtimeContract.eventKind.RUN_LIFECYCLE,
        run_id: RUN_ID,
        occurred_at: CREATED_AT,
        payload: { status: runtimeContract.runStatus.values.RUNNING }
      }],
      next_before_event_id: null
    })).rejects.toThrow('failed runtime validation');

    for (const streamRule of [
      {
        relation: runtimeContract.streamRelation.FILTERED,
        market_slugs: ['market']
      },
      { relation: runtimeContract.streamRelation.INDEPENDENT },
      {
        relation: runtimeContract.streamRelation.INDEPENDENT,
        wallet_addresses: ['not-a-wallet']
      }
    ]) {
      await expect(validateControlPlaneResponse({
        id: RUN_ID,
        bot_id: BOT_ID,
        definition_id: 'winner',
        created_at: CREATED_AT,
        status: runtimeContract.runStatus.values.RUNNING,
        config: { ...PAPER_CONFIG, stream_rules: [streamRule] }
      })).rejects.toThrow('failed runtime validation');
    }

    for (const invalidOptionalField of [
      { bot_graph_revision_id: 'not-a-uuid' },
      { graph_revision: 0 },
      { started_at: 'not-a-date' },
      { ended_at: 42 },
      { heartbeat_at: 'not-a-date' },
      { failure_detail: 42 },
      { latest_equity: 'not-a-decimal' }
    ]) {
      await expect(validateControlPlaneResponse({
        id: RUN_ID,
        bot_id: BOT_ID,
        definition_id: 'winner',
        created_at: CREATED_AT,
        status: runtimeContract.runStatus.values.RUNNING,
        config: PAPER_CONFIG,
        ...invalidOptionalField
      })).rejects.toThrow('failed runtime validation');
    }

    const template = {
      id: RUN_ID,
      name: 'Malformed graph',
      created_at: CREATED_AT,
      updated_at: CREATED_AT
    };
    for (const graph of [
      {
        ...TEST_GRAPH,
        nodes: [{
          ...TEST_GRAPH.nodes[0],
          id: 'n'.repeat(catalogContract.nodeGraph.maximumIdentifierLength + 1)
        }]
      },
      {
        ...TEST_GRAPH,
        nodes: [{
          ...TEST_GRAPH.nodes[0],
          position: { x: catalogContract.nodeGraph.coordinateLimit + 1, y: 0 }
        }]
      },
      {
        ...TEST_GRAPH,
        nodes: [{
          ...TEST_GRAPH.nodes[0],
          data: { hook_name: 'invalid hook' }
        }]
      }
    ]) {
      await expect(validateControlPlaneResponse({ ...template, graph }))
        .rejects.toThrow('failed runtime validation');
    }

    const cyclicGraph = {
      nodes: [
        {
          id: 'boolean-constant',
          type: catalogContract.graphNodeType.CONSTANT,
          position: { x: 0, y: 0 },
          data: {
            scalar_type: BOOLEAN_CONSTANT.scalar_type,
            value: BOOLEAN_CONSTANT.default_value
          }
        },
        ...['comparison-a', 'comparison-b'].map((id, index) => ({
          id,
          type: catalogContract.graphNodeType.COMPARISON,
          position: { x: 100 + index * 100, y: 0 },
          data: { operator: EQUAL_COMPARISON.operator }
        }))
      ],
      edges: [
        {
          id: 'a-to-b', source: 'comparison-a',
          source_handle: EQUAL_COMPARISON.output.handle_id,
          target: 'comparison-b', target_handle: EQUAL_COMPARISON.inputs[0].handle_id
        },
        {
          id: 'b-to-a', source: 'comparison-b',
          source_handle: EQUAL_COMPARISON.output.handle_id,
          target: 'comparison-a', target_handle: EQUAL_COMPARISON.inputs[0].handle_id
        },
        ...['comparison-a', 'comparison-b'].map((target, index) => ({
          id: `constant-to-${index}`,
          source: 'boolean-constant',
          source_handle: BOOLEAN_CONSTANT.output.handle_id,
          target,
          target_handle: EQUAL_COMPARISON.inputs[1].handle_id
        }))
      ]
    };
    const thresholdEdges = THRESHOLD_BUY_GRAPH.edges ?? [];
    const missingRequiredInputGraph = {
      ...THRESHOLD_BUY_GRAPH,
      edges: thresholdEdges.filter((edge) => edge.id !== 'constant-size')
    };
    const crossTriggerGraph = {
      ...THRESHOLD_BUY_GRAPH,
      nodes: [
        ...THRESHOLD_BUY_GRAPH.nodes,
        {
          id: 'wallet-trigger',
          type: catalogContract.graphNodeType.TRIGGER,
          position: { x: 0, y: 400 },
          data: { hook_name: ON_WALLET_TRADE_TRIGGER.hook_name }
        }
      ],
      edges: thresholdEdges.map((edge) => edge.id === 'book-price'
        ? {
            ...edge,
            source: 'wallet-trigger',
            source_handle: graphFieldHandle(ON_WALLET_TRADE_TRIGGER, 'price')
          }
        : edge)
    };
    for (const graph of [cyclicGraph, missingRequiredInputGraph, crossTriggerGraph]) {
      await expect(validateControlPlaneResponse({ ...template, graph }))
        .rejects.toThrow('failed runtime validation');
    }
  });
});
