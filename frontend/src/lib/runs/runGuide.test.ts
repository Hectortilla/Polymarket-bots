import { describe, expect, it } from "vitest";
import type { StreamHealthPayload } from "$lib/api/generated";
import { RUN_STATUS } from "$lib/runs/status";
import { RUN_GUIDE_COPY, runGuidance } from "./runGuide";

const health: StreamHealthPayload = {
  queue_depth: 0,
  peak_queue_depth: 0,
  book_dispatch_lag_ms: 0,
  book_stale: false,
  book_received_count: 5,
  book_coalesced_count: 0,
};
describe("run-reading guidance", () => {
  it.each([
    [RUN_STATUS.QUEUED, RUN_GUIDE_COPY.QUEUED],
    [RUN_STATUS.STARTING, RUN_GUIDE_COPY.STARTING],
    [RUN_STATUS.STOP_REQUESTED, RUN_GUIDE_COPY.STOPPING],
    [RUN_STATUS.STOPPING, RUN_GUIDE_COPY.STOPPING],
    [RUN_STATUS.STOPPED, RUN_GUIDE_COPY.STOPPED],
    [RUN_STATUS.FAILED, RUN_GUIDE_COPY.FAILED],
    [RUN_STATUS.INTERRUPTED, RUN_GUIDE_COPY.FAILED],
  ])("explains %s", (status, copy) => expect(runGuidance(status, null, false, 0)).toBe(copy));
  it.each([
    null,
    { ...health, book_stale: true },
    { ...health, book_received_count: 0 },
    { ...health, book_dispatch_lag_ms: null },
  ])("does not infer waiting from unavailable data", (sample) => {
    expect(runGuidance(RUN_STATUS.RUNNING, sample, false, 0)).toBe(RUN_GUIDE_COPY.UNAVAILABLE);
  });
  it("distinguishes actions, waiting, and reconnecting from the same status", () => {
    expect(runGuidance(RUN_STATUS.RUNNING, health, false, 0)).toBe(RUN_GUIDE_COPY.WAITING);
    expect(runGuidance(RUN_STATUS.RUNNING, health, false, 1)).toBe(RUN_GUIDE_COPY.ACTIONS);
    expect(runGuidance(RUN_STATUS.RUNNING, health, true, 1)).toBe(RUN_GUIDE_COPY.RECONNECTING);
    expect(runGuidance(RUN_STATUS.FAILED, health, true, 1)).toBe(RUN_GUIDE_COPY.FAILED);
  });
});
