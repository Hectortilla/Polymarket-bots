import { afterEach, describe, expect, it, vi } from 'vitest';

import type { BotMode, PersistedDurableEvent } from '$lib/api/generated';
import { SIDE, VALUATION_STATUS } from '$lib/charts/contracts';
import runtimeContract from '$lib/runtimeContract.fixture.json';
import {
  EVENT_KIND,
  INITIAL_EVENT_CURSOR,
  persistedDurableEvent
} from './durableEvents';
import { LIVE_EVENT_KIND, openRunEventStream, runEventStreamUrl } from './events';
import { INITIAL_RUN_STATUS, RUN_STATUS } from './status';

const RUN_ID = '00000000-0000-0000-0000-000000000001';

class FakeEventSource {
  static current: FakeEventSource;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  close = vi.fn();

  constructor(readonly url: string) {
    FakeEventSource.current = this;
  }
}

afterEach(() => vi.unstubAllGlobals());

describe('run EventSource adapter', () => {
  it('continues from the cursor, filters invalid events, and closes at terminal', () => {
    vi.stubGlobal('EventSource', FakeEventSource);
    const onDurableEvent = vi.fn();
    const close = openRunEventStream(RUN_ID, 4, onDurableEvent, vi.fn());
    const source = FakeEventSource.current;
    const event: PersistedDurableEvent = {
      id: 5,
      kind: EVENT_KIND.runLifecycle,
      run_id: RUN_ID,
      occurred_at: '2026-08-23T00:00:00Z',
      payload: { status: RUN_STATUS.RUNNING }
    };

    source.onmessage?.(new MessageEvent('message', { data: JSON.stringify(event) }));
    source.onmessage?.(new MessageEvent('message', { data: JSON.stringify(event) }));
    source.onmessage?.(
      new MessageEvent('message', {
        data: JSON.stringify({ ...event, id: 0 })
      })
    );
    source.onmessage?.(
      new MessageEvent('message', {
        data: JSON.stringify({ ...event, id: 6, payload: { status: 'bogus' } })
      })
    );
    source.onmessage?.(
      new MessageEvent('message', {
        data: JSON.stringify({
          ...event,
          id: 6,
          kind: EVENT_KIND.walletTimeline,
          payload: {
            point: {
              source_key: `wallet${runtimeContract.walletSourceKeySeparator}source`,
              wallet: 'wallet', trade_timestamp_ms: 1,
              side: SIDE.buy, notional: '1',
              market_label: 'Market', accepted: true
            }
          }
        })
      })
    );
    for (const id of [-1, 1.5, null]) {
      source.onmessage?.(
        new MessageEvent('message', {
          data: JSON.stringify({ ...event, id })
        })
      );
    }
    source.onmessage?.(
      new MessageEvent('message', {
        data: JSON.stringify({ ...event, id: 6, run_id: 'another-run' })
      })
    );
    source.onmessage?.(
      new MessageEvent('message', {
        data: JSON.stringify({
          ...event,
          id: 6,
          kind: EVENT_KIND.chartSample,
          payload: { sampled_at_ms: 1, markets: 'invalid', equity: null }
        })
      })
    );
    source.onmessage?.(new MessageEvent('message', { data: '{broken' }));

    expect(source.url).toBe(runEventStreamUrl(RUN_ID, 4));
    expect(onDurableEvent).toHaveBeenCalledOnce();
    expect(source.close).not.toHaveBeenCalled();
    source.onmessage?.(
      new MessageEvent('message', {
        data: JSON.stringify({
          ...event,
          id: 7,
          payload: { status: RUN_STATUS.STOPPED }
        })
      })
    );
    expect(source.close).toHaveBeenCalledOnce();
    close();
    expect(source.close).toHaveBeenCalledTimes(2);
  });

  it('normalizes the generated starting lifecycle default at ingress', () => {
    vi.stubGlobal('EventSource', FakeEventSource);
    const onDurableEvent = vi.fn();
    openRunEventStream(RUN_ID, INITIAL_EVENT_CURSOR, onDurableEvent, vi.fn());
    const event: PersistedDurableEvent = {
      id: 1,
      kind: EVENT_KIND.runLifecycle,
      run_id: RUN_ID,
      occurred_at: '2026-08-23T00:00:00Z',
      payload: {
        name: 'Starting run',
        mode: runtimeContract.botMode.PAPER as BotMode,
        initial_cash_usdc: '1000'
      }
    };

    FakeEventSource.current.onmessage?.(
      new MessageEvent('message', { data: JSON.stringify(event) })
    );

    expect(onDurableEvent).toHaveBeenCalledWith(
      expect.objectContaining({
        payload: expect.objectContaining({ status: INITIAL_RUN_STATUS })
      })
    );
  });

  it('accepts every live variant and rejects malformed live payloads', () => {
    vi.stubGlobal('EventSource', FakeEventSource);
    const onLiveEvent = vi.fn();
    openRunEventStream(RUN_ID, INITIAL_EVENT_CURSOR, vi.fn(), onLiveEvent);
    const base = {
      run_id: RUN_ID,
      occurred_at: '2026-08-23T00:00:00Z'
    };
    const events = [
      {
        ...base,
        kind: LIVE_EVENT_KIND.market,
        payload: {
          sampled_at_ms: 1,
          points: [{
            token_id: 'token', label: 'Market', value: '0.5',
            status: VALUATION_STATUS.fresh, markers: [SIDE.buy]
          }]
        }
      },
      {
        ...base,
        kind: LIVE_EVENT_KIND.equity,
        payload: {
          sampled_at_ms: 1,
          point: { value: '100', status: VALUATION_STATUS.fresh }
        }
      },
      {
        ...base,
        kind: LIVE_EVENT_KIND.wallet,
        payload: {
          sampled_at_ms: 1,
          points: [{
            source_key: `wallet${runtimeContract.walletSourceKeySeparator}source`,
            wallet: 'wallet', trade_timestamp_ms: 1,
            side: SIDE.sell, notional: '2',
            market_label: 'Market', accepted: null
          }]
        }
      },
      {
        ...base,
        kind: LIVE_EVENT_KIND.streamHealth,
        payload: {
          queue_depth: 0, peak_queue_depth: 1, book_dispatch_lag_ms: null,
          book_stale: false, book_received_count: 2, book_coalesced_count: 0
        }
      }
    ];
    for (const event of events) emit(event);

    emit({
      ...events[0],
      payload: {
        sampled_at_ms: 2,
        points: [{
          token_id: 'token', label: 'Market', value: '0.5',
          status: VALUATION_STATUS.unavailable, markers: []
        }]
      }
    });
    emit({ ...events[1], id: 4 });
    emit({
      ...events[1],
      payload: {
        sampled_at_ms: 2,
        point: { value: '0x10', status: VALUATION_STATUS.fresh }
      }
    });
    emit({
      ...events[2],
      payload: { sampled_at_ms: 2, points: [{ notional: '-1' }] }
    });
    emit({
      ...events[3],
      payload: { ...events[3].payload, queue_depth: -1 }
    });

    expect(onLiveEvent).toHaveBeenCalledTimes(4);
    expect(onLiveEvent.mock.calls.map(([event]) => event.kind)).toEqual(
      events.map(({ kind }) => kind)
    );
  });

  it('validates every durable financial-history payload at ingress', () => {
    const order = {
      token_id: 'token',
      side: SIDE.buy,
      price: '0.5',
      size: '2'
    };
    const portfolio = {
      cash_usdc: '100',
      positions: [
        { token_id: 'open-token', size: '2', average_entry_price: '0.5' },
        { token_id: 'closed-token', size: '0', average_entry_price: null }
      ],
      cumulative_fees_usdc: '0'
    };
    const fillPayload = {
      order,
      fill: {
        order_id: 'order', token_id: 'token', side: SIDE.buy,
        status: runtimeContract.orderStatus.FILLED,
        requested_size: '2', filled_size: '2', average_price: '0.5',
        fee_usdc: '0', received_at_ms: 1,
        reject_reason: null, reject_message: null
      },
      portfolio: null,
      latency_ms: 0
    };
    const settlementPayload = {
      settlement: {
        resolution: {
          condition_id: 'condition', market_slug: 'market',
          token_ids: ['yes-token', 'no-token'],
          winning_token_id: 'yes-token', winning_outcome: 'Yes',
          resolved_at_ms: 1, source: 'test'
        },
        paper_positions: [{
          owner: 'paper', token_id: 'yes-token', size: '2',
          payout_per_token: '1', cash_payout_usdc: '2', realized_pnl_usdc: '1'
        }],
        followed_wallet_positions: [{
          owner: 'wallet', token_id: 'no-token', size: '1',
          payout_per_token: '0', cash_payout_usdc: '0', realized_pnl_usdc: null
        }],
        settled_at_ms: 1
      },
      portfolio
    };
    const walletTrade = {
      wallet: '0x0000000000000000000000000000000000000001',
      condition_id: 'condition',
      token_id: 'a-very-long-token-id',
      side: SIDE.buy,
      size: '2',
      price: '0.5',
      source_id: 'source',
      trade_timestamp_ms: 1,
      observed_at_ms: 1,
      kind: runtimeContract.walletTradeKind.TRADE,
      market_slug: 'market',
      outcome: 'Yes'
    };
    const walletTimelinePayload = {
      trade: walletTrade,
      outcome: { accepted: true, skip_reason: null },
      point: {
        source_key: `${walletTrade.wallet}${runtimeContract.walletSourceKeySeparator}source`,
        wallet: walletTrade.wallet,
        trade_timestamp_ms: 1,
        side: SIDE.buy,
        notional: '1.00',
        market_label: `market${runtimeContract.dashboard.walletMarketLabelPolicy.partSeparator}Yes`,
        accepted: true
      }
    };
    const validPayloads = [
      {
        kind: EVENT_KIND.runBootstrap,
        payload: {
          phase: runtimeContract.bootstrapPhase.MARKETS,
          completed: 1,
          total: 2
        }
      },
      {
        kind: EVENT_KIND.botActivity,
        payload: {
          message: 'Watching market',
          severity: runtimeContract.activitySeverity.INFO
        }
      },
      { kind: EVENT_KIND.brokerOrder, payload: { order } },
      { kind: EVENT_KIND.brokerFill, payload: fillPayload },
      {
        kind: EVENT_KIND.brokerFailure,
        payload: { order, error: 'Broker unavailable' }
      },
      { kind: EVENT_KIND.marketSettlement, payload: settlementPayload },
      { kind: EVENT_KIND.walletTimeline, payload: walletTimelinePayload },
      { kind: EVENT_KIND.portfolioSnapshot, payload: portfolio },
      { kind: EVENT_KIND.runFailure, payload: { error: 'Run failed' } }
    ];

    validPayloads.forEach(({ kind, payload }, index) => {
      expect(persistedDurableEvent({
        id: index + 1,
        kind,
        run_id: RUN_ID,
        occurred_at: '2026-08-23T00:00:00Z',
        payload
      }, RUN_ID)).not.toBeNull();
    });

    const validFillStates = [
      {
        status: runtimeContract.orderStatus.REJECTED,
        token_id: '',
        filled_size: '0',
        average_price: null,
        reject_reason: runtimeContract.fillRejectReason.BAD_SIZE,
        reject_message: 'Order size is below the market minimum'
      },
      {
        status: runtimeContract.orderStatus.PARTIAL,
        token_id: 'token',
        filled_size: '1',
        average_price: '0.5',
        reject_reason: null,
        reject_message: null
      },
      ...[
        runtimeContract.orderStatus.ACCEPTED,
        runtimeContract.orderStatus.CANCELED
      ].map((status) => ({
        status,
        token_id: 'token',
        filled_size: '0',
        average_price: null,
        reject_reason: null,
        reject_message: null
      }))
    ];
    validFillStates.forEach((fill, index) => {
      expect(persistedDurableEvent({
        id: index + 100,
        kind: EVENT_KIND.brokerFill,
        run_id: RUN_ID,
        occurred_at: '2026-08-23T00:00:00Z',
        payload: {
          ...fillPayload,
          fill: { ...fillPayload.fill, ...fill }
        }
      }, RUN_ID)).not.toBeNull();
    });

    const malformedPayloads = [
      { kind: EVENT_KIND.runBootstrap, payload: {
        phase: runtimeContract.bootstrapPhase.MARKETS, completed: 3, total: 2
      } },
      { kind: EVENT_KIND.botActivity, payload: {
        message: 'Watching market', severity: 'invalid'
      } },
      { kind: EVENT_KIND.brokerOrder, payload: {
        order: { ...order, price: '0' }
      } },
      { kind: EVENT_KIND.brokerFill, payload: {
        ...fillPayload,
        fill: { ...fillPayload.fill, token_id: '' }
      } },
      { kind: EVENT_KIND.brokerFailure, payload: { order, error: '' } },
      { kind: EVENT_KIND.marketSettlement, payload: {
        ...settlementPayload,
        settlement: {
          ...settlementPayload.settlement,
          resolution: {
            ...settlementPayload.settlement.resolution,
            token_ids: ['same-token', 'same-token']
          }
        }
      } },
      { kind: EVENT_KIND.marketSettlement, payload: {
        ...settlementPayload,
        settlement: {
          ...settlementPayload.settlement,
          paper_positions: [{
            ...settlementPayload.settlement.paper_positions[0],
            payout_per_token: '2'
          }]
        }
      } },
      { kind: EVENT_KIND.walletTimeline, payload: {
        ...walletTimelinePayload,
        point: { ...walletTimelinePayload.point, notional: '999' }
      } },
      { kind: EVENT_KIND.portfolioSnapshot, payload: {
        ...portfolio, cumulative_fees_usdc: '-1'
      } },
      { kind: EVENT_KIND.portfolioSnapshot, payload: {
        ...portfolio,
        positions: [{ token_id: 'open-token', size: '2', average_entry_price: '0' }]
      } },
      { kind: EVENT_KIND.runFailure, payload: { error: '' } }
    ];
    malformedPayloads.forEach(({ kind, payload }, index) => {
      expect(persistedDurableEvent({
        id: index + 20,
        kind,
        run_id: RUN_ID,
        occurred_at: '2026-08-23T00:00:00Z',
        payload
      }, RUN_ID)).toBeNull();
    });
  });
});

function emit(event: object): void {
  FakeEventSource.current.onmessage?.(
    new MessageEvent('message', { data: JSON.stringify(event) })
  );
}
