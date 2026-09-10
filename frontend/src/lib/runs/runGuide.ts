import type { RunStatus, StreamHealthPayload } from "$lib/api/generated";
import { RUN_STATUS } from "$lib/runs/status";

export const RUN_GUIDE_COPY = {
  BOOK_REPORTED: "Last report includes book input without a stale flag",
  BOOK_UNAVAILABLE: "Book data unavailable or stale",
  LOADED_ORDERS: "Loaded orders",
  LOADED_FILLS: "Loaded fill outcomes",
  HEADING: "Reading this paper run",
  QUEUED: "Queued: waiting for worker capacity. You can cancel this run before it starts.",
  STARTING: "Starting: loading the configured inputs. Orders are not guaranteed during startup.",
  STOPPING: "Stopping: wait for the final status before starting another run.",
  STOPPED: "Stopped: inspect the retained results below. Continuing requires a new explicit Run action.",
  FAILED:
    "This run failed or was interrupted. Read its failure detail, check the saved settings, and start a new run only when ready.",
  RECONNECTING:
    "The browser is reconnecting. Displayed results may be behind; wait for reconnection or reload to recover retained history.",
  UNAVAILABLE:
    "Market data is stale or has not been reported. No orders here does not prove that strategy conditions are unmet. Check stream health before continuing.",
  WAITING:
    "No orders in the loaded history. The latest report shows book input received without a stale flag; the example may be waiting for its conditions.",
  ACTIONS:
    "Orders appear in the loaded history. Compare each order with its fill or rejection; an order request alone does not mean a fill.",
  BALANCES:
    "Paper cash, positions, fees and equity are simulated. Equity can be unavailable when a position cannot be valued; unavailable is not zero.",
  EVENTS:
    "Progress shows orders, fills, and available skipped/rejected-action reasons. A disabled condition can produce no action or progress entry. Loaded counts cover the visible history window.",
} as const;

export function runGuidance(
  status: RunStatus,
  health: StreamHealthPayload | null,
  reconnecting: boolean,
  loadedOrderCount: number,
): string {
  if (status === RUN_STATUS.FAILED || status === RUN_STATUS.INTERRUPTED) return RUN_GUIDE_COPY.FAILED;
  if (status === RUN_STATUS.STOPPED) return RUN_GUIDE_COPY.STOPPED;
  if (status === RUN_STATUS.STOP_REQUESTED || status === RUN_STATUS.STOPPING) return RUN_GUIDE_COPY.STOPPING;
  if (reconnecting) return RUN_GUIDE_COPY.RECONNECTING;
  if (status === RUN_STATUS.QUEUED) return RUN_GUIDE_COPY.QUEUED;
  if (status === RUN_STATUS.STARTING) return RUN_GUIDE_COPY.STARTING;
  if (!hasReportedUsableBook(health)) return RUN_GUIDE_COPY.UNAVAILABLE;
  return loadedOrderCount === 0 ? RUN_GUIDE_COPY.WAITING : RUN_GUIDE_COPY.ACTIONS;
}

export function hasReportedUsableBook(health: StreamHealthPayload | null): boolean {
  return (
    health !== null && !health.book_stale && health.book_received_count > 0 && health.book_dispatch_lag_ms !== null
  );
}
