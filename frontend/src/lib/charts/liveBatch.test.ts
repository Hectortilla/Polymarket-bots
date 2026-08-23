import { describe, expect, it, vi } from 'vitest';

import type { LiveRunEvent } from '$lib/runs/events';
import { LIVE_EVENT_KIND } from '$lib/runs/eventKinds';
import { VALUATION_STATUS } from './contracts';
import { createLiveDashboardBatcher } from './liveBatch';

describe('live dashboard batching', () => {
  it('flushes all events received during one animation frame once', () => {
    const flush = vi.fn();
    const frames = new Map<number, FrameRequestCallback>();
    const schedule = vi.fn((callback: FrameRequestCallback) => {
      frames.set(1, callback);
      return 1;
    });
    const batcher = createLiveDashboardBatcher(flush, schedule, vi.fn());
    const events = [marketEvent(1), marketEvent(2), marketEvent(3)];

    for (const event of events) batcher.push(event);

    expect(schedule).toHaveBeenCalledOnce();
    expect(flush).not.toHaveBeenCalled();
    frames.get(1)?.(0);
    expect(flush).toHaveBeenCalledOnce();
    expect(flush).toHaveBeenCalledWith(events);
  });

  it('cancels and drops a pending batch on disposal', () => {
    const cancel = vi.fn();
    const flush = vi.fn();
    const batcher = createLiveDashboardBatcher(flush, () => 7, cancel);

    batcher.push(marketEvent(1));
    batcher.dispose();

    expect(cancel).toHaveBeenCalledWith(7);
    expect(flush).not.toHaveBeenCalled();
  });
});

function marketEvent(sampledAtMs: number): LiveRunEvent {
  return {
    kind: LIVE_EVENT_KIND.market,
    run_id: '00000000-0000-0000-0000-000000000001',
    occurred_at: '2026-08-23T00:00:00Z',
    payload: {
      sampled_at_ms: sampledAtMs,
      points: [{
        token_id: 'token',
        label: 'Market',
        value: '0.5',
        status: VALUATION_STATUS.fresh,
        markers: []
      }]
    }
  };
}
