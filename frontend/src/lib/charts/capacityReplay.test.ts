// The capacity runner points this test at bounded frames captured from real HTTP.
import { describe, expect, it, inject } from "vitest";
import type { LiveRunEvent } from "$lib/api/generated";
import { DashboardHistory } from "./history";
import { createLiveDashboardBatcher } from "./liveBatch";
import { liveRunEvent } from "$lib/runs/events/live";
import { persistedDurableEvent } from "$lib/runs/durableEvents";
import { LIVE_EVENT_KIND } from "$lib/runs/eventKinds";

declare module "vitest" {
  interface ProvidedContext {
    liveCapture: Record<string, unknown>[];
  }
}
const frames = inject("liveCapture");
describe.skipIf(frames.length === 0)("captured HTTP dashboard replay", () => {
  it("passes real frames through ingress, animation batching and dashboard merging", () => {
    expect(frames.length).toBeGreaterThan(0);
    const histories = new Map<string, DashboardHistory>();
    for (const frame of frames) {
      const run = String(frame.run_id);
      let history = histories.get(run) ?? new DashboardHistory();
      if (frame.kind === LIVE_EVENT_KIND.snapshot) {
        expect(liveRunEvent(frame, run)).not.toBeNull();
        let scheduled: FrameRequestCallback | undefined;
        const batcher = createLiveDashboardBatcher(
          (events) => {
            history = history.mergeLiveEvents(events);
          },
          (callback) => {
            scheduled = callback;
            return 1;
          },
          () => {},
        );
        batcher.push(frame as LiveRunEvent);
        scheduled?.(0);
        batcher.dispose();
      } else {
        const event = persistedDurableEvent(frame, run);
        expect(event).not.toBeNull();
        if (event) history = history.mergeDurableEvents([event]);
      }
      histories.set(run, history);
    }
    expect([...histories.values()].some((history) => history.samples.length > 0)).toBe(true);
  });
});
