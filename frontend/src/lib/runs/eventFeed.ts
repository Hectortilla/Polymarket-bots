import { RUN_EVENT_COPY } from "$lib/runs/copy";
import { RUN_COPY } from "$lib/runs/copy";
import runtimeContract from "$lib/runtimeContract.fixture.json";
import { EVENT_KIND, type PersistedDurableEvent } from "./durableEvents";

export function eventLabel(event: PersistedDurableEvent): string {
  switch (event.kind) {
    case EVENT_KIND.runLifecycle:
      return RUN_EVENT_COPY.RUN_STATUS;
    case EVENT_KIND.runFailure:
      return RUN_EVENT_COPY.RUN_ERROR;
    case EVENT_KIND.brokerFailure:
      return RUN_EVENT_COPY.ORDER_ERROR;
    case EVENT_KIND.brokerFill:
      return RUN_EVENT_COPY.ORDER_RESULT;
    case EVENT_KIND.marketSettlement:
      return RUN_EVENT_COPY.SETTLEMENT;
    case EVENT_KIND.botActivity:
      if (event.payload.severity === runtimeContract.activitySeverity.WARNING) return RUN_EVENT_COPY.WARNING;
      if (event.payload.severity === runtimeContract.activitySeverity.ERROR) return RUN_EVENT_COPY.ERROR;
      return RUN_EVENT_COPY.BOT_ACTIVITY;
    case EVENT_KIND.runBootstrap:
      return RUN_EVENT_COPY.STARTUP_PROGRESS;
    case EVENT_KIND.brokerOrder:
      return RUN_EVENT_COPY.ORDER_SUBMITTED;
    case EVENT_KIND.portfolioSnapshot:
      return RUN_EVENT_COPY.PORTFOLIO_UPDATE;
    case EVENT_KIND.walletTimeline:
      return RUN_EVENT_COPY.FOLLOWED_WALLET_TRADE;
    case EVENT_KIND.streamHealth:
      return RUN_COPY.STREAM_HEALTH;
    case EVENT_KIND.chartSample:
      return RUN_EVENT_COPY.CHART_UPDATE;
  }
}
