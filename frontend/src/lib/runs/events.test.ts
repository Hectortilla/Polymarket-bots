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
  it('continues from the durable cursor and drops duplicate or malformed events', () => {
    vi.stubGlobal('EventSource', FakeEventSource);
    const onEvent = vi.fn();
    const close = openRunEventStream(RUN_ID, 4, onEvent);
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
    source.onmessage?.(new MessageEvent('message', { data: '{broken' }));

    expect(source.url).toBe(
      `/api/v1/runs/${RUN_ID}/events/stream?after_event_id=4`
    );
    expect(onEvent).toHaveBeenCalledOnce();
    close();
    expect(source.close).toHaveBeenCalledOnce();
  });

  it('normalizes the generated starting lifecycle default at ingress', () => {
    vi.stubGlobal('EventSource', FakeEventSource);
    const onEvent = vi.fn();
    openRunEventStream(RUN_ID, INITIAL_EVENT_CURSOR, onEvent);
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

    expect(onEvent).toHaveBeenCalledWith(
      expect.objectContaining({
        payload: expect.objectContaining({ status: INITIAL_RUN_STATUS })
      })
    );
  });
});
