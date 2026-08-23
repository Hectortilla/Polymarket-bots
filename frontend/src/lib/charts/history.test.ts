import { describe, expect, it } from 'vitest';

import type { DurableEvent } from '$lib/api/generated';
import { EVENT_KIND, requirePersistedDurableEvents } from '$lib/runs/durableEvents';
import { LIVE_EVENT_KIND, type LiveRunEvent } from '$lib/runs/events';
import { SIDE, VALUATION_STATUS } from './contracts';
import {
  MAX_CHART_HISTORY_POINTS,
  emptyDashboardHistory,
  mergeDurableEvents,
  mergeLiveEvent,
  mergeLiveEvents
} from './history';

const RUN_ID = '00000000-0000-0000-0000-000000000001';

describe('dashboard history', () => {
  it('bounds loaded durable samples and continues with live frames', () => {
    const durable = Array.from(
      { length: MAX_CHART_HISTORY_POINTS + 2 },
      (_, index) => chartEvent(index + 1)
    );
    let history = mergeDurableEvents(
      emptyDashboardHistory(),
      requirePersistedDurableEvents(durable, RUN_ID)
    );

    expect(history.samples).toHaveLength(MAX_CHART_HISTORY_POINTS);
    expect(history.samples[0].sampled_at_ms).toBe(3_000);

    history = mergeLiveEvent(history, {
      kind: LIVE_EVENT_KIND.equity,
      run_id: RUN_ID,
      occurred_at: '2026-08-23T00:00:00Z',
      payload: {
        sampled_at_ms: 1_000_000,
        point: { value: '125.5', status: VALUATION_STATUS.fresh }
      }
    } as LiveRunEvent);

    expect(history.samples).toHaveLength(MAX_CHART_HISTORY_POINTS);
    expect(history.samples.at(-1)?.equity.value).toBe('125.5');
  });

  it('hydrates canonical wallet points and terminal health from durable events', () => {
    const wallet = '0x0000000000000000000000000000000000000001';
    const events = requirePersistedDurableEvents([
      {
        id: 1,
        kind: EVENT_KIND.walletTimeline,
        run_id: RUN_ID,
        occurred_at: '2026-08-23T00:00:00Z',
        payload: {
          trade: {
            wallet,
            condition_id: 'condition',
            token_id: 'token',
            side: SIDE.buy,
            size: '3',
            price: '0.2',
            source_id: 'source',
            trade_timestamp_ms: 1,
            observed_at_ms: 1
          },
          outcome: { accepted: true, skip_reason: null },
          point: {
            source_key: `${wallet}\0source`,
            wallet,
            trade_timestamp_ms: 1,
            side: SIDE.buy,
            notional: '0.6',
            market_label: 'Market · Up',
            accepted: true
          }
        }
      },
      {
        id: 2,
        kind: EVENT_KIND.streamHealth,
        run_id: RUN_ID,
        occurred_at: '2026-08-23T00:00:01Z',
        payload: {
          queue_depth: 1,
          peak_queue_depth: 2,
          book_dispatch_lag_ms: 3,
          book_stale: true,
          book_received_count: 4,
          book_coalesced_count: 1
        }
      }
    ], RUN_ID);

    const history = mergeDurableEvents(emptyDashboardHistory(), events);

    expect(history.walletTimelinePoints).toEqual([{
      source_key: `${wallet}\0source`,
      wallet,
      trade_timestamp_ms: 1,
      side: SIDE.buy,
      notional: '0.6',
      market_label: 'Market · Up',
      accepted: true
    }]);
    expect(history.streamHealth).toEqual(events[1].payload);
  });

  it('merges every live dashboard branch and upserts wallet sources', () => {
    let history = emptyDashboardHistory();
    history = mergeLiveEvent(history, {
      kind: LIVE_EVENT_KIND.market,
      run_id: RUN_ID,
      occurred_at: '2026-08-23T00:00:00Z',
      payload: {
        sampled_at_ms: 1,
        points: [{
          token_id: 'token', label: 'Market', value: '0.5',
          status: VALUATION_STATUS.fresh, markers: [SIDE.buy]
        }]
      }
    });
    history = mergeLiveEvent(history, {
      kind: LIVE_EVENT_KIND.equity,
      run_id: RUN_ID,
      occurred_at: '2026-08-23T00:00:00Z',
      payload: {
        sampled_at_ms: 1,
        point: { value: '101', status: VALUATION_STATUS.fresh }
      }
    });
    for (const notional of ['1', '2']) {
      history = mergeLiveEvent(history, {
        kind: LIVE_EVENT_KIND.wallet,
        run_id: RUN_ID,
        occurred_at: '2026-08-23T00:00:00Z',
        payload: {
          sampled_at_ms: 1,
          points: [{
            source_key: 'wallet\0source', wallet: 'wallet',
            trade_timestamp_ms: 1, side: SIDE.buy, notional,
            market_label: 'Market', accepted: true
          }]
        }
      });
    }
    history = mergeLiveEvent(history, {
      kind: LIVE_EVENT_KIND.streamHealth,
      run_id: RUN_ID,
      occurred_at: '2026-08-23T00:00:00Z',
      payload: {
        queue_depth: 1, peak_queue_depth: 2, book_dispatch_lag_ms: 3,
        book_stale: false, book_received_count: 4, book_coalesced_count: 1
      }
    });

    expect(history.samples[0]).toMatchObject({
      markets: [{ token_id: 'token' }],
      equity: { value: '101' }
    });
    expect(history.walletTimelinePoints).toHaveLength(1);
    expect(history.walletTimelinePoints[0].notional).toBe('2');
    expect(history.streamHealth?.queue_depth).toBe(1);
  });

  it('combines same-timestamp chart variants before committing the sample', () => {
    const history = mergeLiveEvents(emptyDashboardHistory(), [
      {
        kind: LIVE_EVENT_KIND.market,
        run_id: RUN_ID,
        occurred_at: '2026-08-23T00:00:00Z',
        payload: {
          sampled_at_ms: 1,
          points: [{
            token_id: 'token', label: 'Market', value: '0.5',
            status: VALUATION_STATUS.fresh, markers: [SIDE.buy]
          }]
        }
      },
      {
        kind: LIVE_EVENT_KIND.equity,
        run_id: RUN_ID,
        occurred_at: '2026-08-23T00:00:00Z',
        payload: {
          sampled_at_ms: 1,
          point: { value: '101', status: VALUATION_STATUS.fresh }
        }
      },
      {
        kind: LIVE_EVENT_KIND.wallet,
        run_id: RUN_ID,
        occurred_at: '2026-08-23T00:00:00Z',
        payload: {
          sampled_at_ms: 1,
          points: [{
            source_key: 'wallet\0source', wallet: 'wallet',
            trade_timestamp_ms: 1, side: SIDE.buy, notional: '2',
            market_label: 'Market', accepted: true
          }]
        }
      }
    ]);

    expect(history.samples).toEqual([{
      sampled_at_ms: 1,
      markets: [expect.objectContaining({ token_id: 'token' })],
      equity: { value: '101', status: VALUATION_STATUS.fresh }
    }]);
    expect(history.walletTimelinePoints).toHaveLength(1);
  });

  it('preserves chart allocations for empty wallet and health-only frames', () => {
    const initial = mergeLiveEvent(emptyDashboardHistory(), {
      kind: LIVE_EVENT_KIND.equity,
      run_id: RUN_ID,
      occurred_at: '2026-08-23T00:00:00Z',
      payload: {
        sampled_at_ms: 1,
        point: { value: '100', status: VALUATION_STATUS.fresh }
      }
    });
    const emptyWallet = mergeLiveEvent(initial, {
      kind: LIVE_EVENT_KIND.wallet,
      run_id: RUN_ID,
      occurred_at: '2026-08-23T00:00:00Z',
      payload: { sampled_at_ms: 1, points: [] }
    });

    expect(emptyWallet).toBe(initial);
    const withHealth = mergeLiveEvent(emptyWallet, {
      kind: LIVE_EVENT_KIND.streamHealth,
      run_id: RUN_ID,
      occurred_at: '2026-08-23T00:00:00Z',
      payload: {
        queue_depth: 1, peak_queue_depth: 2, book_dispatch_lag_ms: 3,
        book_stale: false, book_received_count: 4, book_coalesced_count: 1
      }
    });
    expect(withHealth.samples).toBe(initial.samples);
    expect(withHealth.walletTimelinePoints).toBe(initial.walletTimelinePoints);
  });
});

function chartEvent(index: number): DurableEvent {
  return {
    id: index,
    kind: EVENT_KIND.chartSample,
    run_id: RUN_ID,
    occurred_at: '2026-08-23T00:00:00Z',
    payload: {
      sampled_at_ms: index * 1_000,
      markets: [],
      equity: { value: String(index), status: VALUATION_STATUS.fresh }
    }
  };
}
