import { afterEach, describe, expect, it, vi } from 'vitest';

import type { DurableEvent } from '$lib/api/generated';
import { EVENT_KIND, INITIAL_EVENT_CURSOR } from './durableEvents';
import { openRunEventStream } from './events';
import { INITIAL_RUN_STATUS } from './status';

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
    const event: DurableEvent = {
      id: 5,
      kind: EVENT_KIND.runLifecycle,
      run_id: RUN_ID,
      occurred_at: '2026-08-23T00:00:00Z',
      payload: { status: 'running' }
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
              source_key: 'wallet\0source', wallet: 'wallet',
              trade_timestamp_ms: 1, side: 'BUY', notional: '1',
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

    expect(source.url).toBe(
      `/api/v1/runs/${RUN_ID}/events/stream?after_event_id=4`
    );
    expect(onDurableEvent).toHaveBeenCalledOnce();
    expect(source.close).not.toHaveBeenCalled();
    source.onmessage?.(
      new MessageEvent('message', {
        data: JSON.stringify({ ...event, id: 7, payload: { status: 'stopped' } })
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
    const event: DurableEvent = {
      id: 1,
      kind: EVENT_KIND.runLifecycle,
      run_id: RUN_ID,
      occurred_at: '2026-08-23T00:00:00Z',
      payload: {
        name: 'Starting run',
        mode: 'paper',
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
    openRunEventStream(RUN_ID, 0, vi.fn(), onLiveEvent);
    const base = {
      run_id: RUN_ID,
      occurred_at: '2026-08-23T00:00:00Z'
    };
    const events = [
      {
        ...base,
        kind: 'chart.market',
        payload: {
          sampled_at_ms: 1,
          points: [{
            token_id: 'token', label: 'Market', value: '0.5',
            status: 'fresh', markers: ['BUY']
          }]
        }
      },
      {
        ...base,
        kind: 'chart.equity',
        payload: { sampled_at_ms: 1, point: { value: '100', status: 'fresh' } }
      },
      {
        ...base,
        kind: 'chart.wallet',
        payload: {
          sampled_at_ms: 1,
          points: [{
            source_key: 'wallet\0source', wallet: 'wallet',
            trade_timestamp_ms: 1, side: 'SELL', notional: '2',
            market_label: 'Market', accepted: null
          }]
        }
      },
      {
        ...base,
        kind: 'stream.health.live',
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
          status: 'unavailable', markers: []
        }]
      }
    });
    emit({ ...events[1], id: 4 });
    emit({
      ...events[1],
      payload: { sampled_at_ms: 2, point: { value: '0x10', status: 'fresh' } }
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
});

function emit(event: object): void {
  FakeEventSource.current.onmessage?.(
    new MessageEvent('message', { data: JSON.stringify(event) })
  );
}
