import runtimeContract from "$lib/runtimeContract.fixture.json";
import { EVENT_KIND, type PersistedDurableEvent } from "./durableEvents";

export function eventLabel(event: PersistedDurableEvent): string {
  switch (event.kind) {
    case EVENT_KIND.runLifecycle:
      return "Run status";
    case EVENT_KIND.runFailure:
      return "Run error";
    case EVENT_KIND.brokerFailure:
      return "Order error";
    case EVENT_KIND.brokerFill:
      return "Order result";
    case EVENT_KIND.marketSettlement:
      return "Settlement";
    case EVENT_KIND.botActivity:
      if (event.payload.severity === runtimeContract.activitySeverity.WARNING) return "Warning";
      if (event.payload.severity === runtimeContract.activitySeverity.ERROR) return "Error";
      return "Bot activity";
    case EVENT_KIND.runBootstrap:
      return "Startup progress";
    case EVENT_KIND.brokerOrder:
      return "Order submitted";
    case EVENT_KIND.portfolioSnapshot:
      return "Portfolio update";
    case EVENT_KIND.walletTimeline:
      return "Followed wallet trade";
    case EVENT_KIND.streamHealth:
      return "Stream health";
    case EVENT_KIND.chartSample:
      return "Chart update";
  }
}
