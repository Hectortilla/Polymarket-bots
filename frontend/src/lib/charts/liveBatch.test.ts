import { describe, expect, it, vi } from "vitest";

import type { LiveRunEvent } from "$lib/api/generated";
import { LIVE_EVENT_KIND } from "$lib/runs/eventKinds";
import { VALUATION_STATUS } from "./contracts";
import { createLiveDashboardBatcher } from "./liveBatch";

describe("live dashboard batching", () => {
  it("flushes only the newest snapshot in an animation frame", () => {
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
    expect(flush).toHaveBeenCalledWith([events[2]]);
  });

  it("cancels and drops a pending batch on disposal", () => {
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
    kind: LIVE_EVENT_KIND.snapshot,
    run_id: "00000000-0000-0000-0000-000000000001",
    occurred_at: "2026-08-23T00:00:00Z",
    generation: 1,
    sequence: sampledAtMs,
    sampled_at_ms: sampledAtMs,
    markets: [],
    equity: { value: "100", status: VALUATION_STATUS.fresh },
  };
}
