import type { LiveRunEvent } from '$lib/runs/events';

type ScheduleFrame = (callback: FrameRequestCallback) => number;
type CancelFrame = (frameId: number) => void;

export type LiveDashboardBatcher = {
  push: (event: LiveRunEvent) => void;
  dispose: () => void;
};

export function createLiveDashboardBatcher(
  flush: (events: LiveRunEvent[]) => void,
  scheduleFrame: ScheduleFrame = requestAnimationFrame,
  cancelFrame: CancelFrame = cancelAnimationFrame
): LiveDashboardBatcher {
  let pending: LiveRunEvent[] = [];
  let frameId: number | null = null;

  return {
    push(event) {
      pending.push(event);
      frameId ??= scheduleFrame(() => {
        frameId = null;
        const events = pending;
        pending = [];
        flush(events);
      });
    },
    dispose() {
      if (frameId !== null) cancelFrame(frameId);
      frameId = null;
      pending = [];
    }
  };
}
