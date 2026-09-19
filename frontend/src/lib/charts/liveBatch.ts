import type { LiveRunEvent } from "$lib/api/generated";

import { isNewerLiveEvent, type LiveIdentity } from "$lib/runs/events/live";

type ScheduleFrame = (callback: FrameRequestCallback) => number;
type CancelFrame = (frameId: number) => void;
export type LiveDashboardBatcher = { push(event: LiveRunEvent): void; dispose(): void };

export function createLiveDashboardBatcher(
  flush: (events: LiveRunEvent[]) => void,
  scheduleFrame: ScheduleFrame = requestAnimationFrame,
  cancelFrame: CancelFrame = cancelAnimationFrame,
): LiveDashboardBatcher {
  let pending: LiveRunEvent | null = null;
  let frameId: number | null = null;
  let disposed = false;
  let identity: LiveIdentity = [0, 0];
  return {
    push(event) {
      if (disposed || !isNewerLiveEvent(event, identity)) return;
      identity = [event.generation, event.sequence];
      pending = event;
      frameId ??= scheduleFrame(() => {
        frameId = null;
        const snapshot = pending;
        pending = null;
        if (!disposed && snapshot !== null) flush([snapshot]);
      });
    },
    dispose() {
      disposed = true;
      if (frameId !== null) cancelFrame(frameId);
      frameId = null;
      pending = null;
    },
  };
}
