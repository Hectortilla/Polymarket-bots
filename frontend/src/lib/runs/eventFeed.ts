import runtimeContract from "$lib/runtimeContract.fixture.json";
import { EVENT_KIND, type PersistedDurableEvent } from "./durableEvents";

export function isUserFacingEvent(event: PersistedDurableEvent): boolean {
  switch (event.kind) {
    case EVENT_KIND.runLifecycle:
    case EVENT_KIND.runFailure:
    case EVENT_KIND.brokerFailure:
      return true;
    case EVENT_KIND.brokerFill:
      return event.payload.fill.status !== runtimeContract.orderStatus.ACCEPTED;
    case EVENT_KIND.marketSettlement:
      return event.payload.settlement.paper_positions.length > 0;
    case EVENT_KIND.botActivity:
      return (
        event.payload.severity === runtimeContract.activitySeverity.WARNING ||
        event.payload.severity === runtimeContract.activitySeverity.ERROR
      );
    case EVENT_KIND.runBootstrap:
    case EVENT_KIND.brokerOrder:
    case EVENT_KIND.portfolioSnapshot:
    case EVENT_KIND.walletTimeline:
    case EVENT_KIND.streamHealth:
    case EVENT_KIND.chartSample:
      return false;
  }
}

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
