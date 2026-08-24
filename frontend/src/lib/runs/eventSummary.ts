import {
  EVENT_KIND,
  type PersistedDurableEvent
} from './durableEvents';
import { runStatusLabel } from './status';

export function eventSummary(event: PersistedDurableEvent): string {
  switch (event.kind) {
    case EVENT_KIND.runLifecycle:
      return `Run ${runStatusLabel(event.payload.status)}`;
    case EVENT_KIND.runBootstrap:
      return `${event.payload.phase}: ${event.payload.completed}/${event.payload.total}`;
    case EVENT_KIND.botActivity:
      return event.payload.message;
    case EVENT_KIND.brokerOrder:
      return `${event.payload.order.side} ${event.payload.order.size} / ${event.payload.order.token_id}`;
    case EVENT_KIND.brokerFill:
      return fillSummary(event.payload.fill);
    case EVENT_KIND.brokerFailure:
      return event.payload.error;
    case EVENT_KIND.marketSettlement:
      return `${event.payload.settlement.resolution.market_slug} / ${event.payload.settlement.resolution.winning_outcome}`;
    case EVENT_KIND.portfolioSnapshot:
      return `Cash ${event.payload.cash_usdc} USDC`;
    case EVENT_KIND.walletTimeline:
      return `${event.payload.trade.side} ${event.payload.trade.size} / ${event.payload.trade.wallet}`;
    case EVENT_KIND.streamHealth:
      return `Queue ${event.payload.queue_depth} / ${event.payload.book_received_count} books`;
    case EVENT_KIND.runFailure:
      return event.payload.error;
    case EVENT_KIND.chartSample:
      return event.payload.equity.value === null
        ? `Equity ${event.payload.equity.status}`
        : `Equity ${event.payload.equity.value} USDC / ${event.payload.equity.status}`;
  }
}

function fillSummary(
  fill: Extract<PersistedDurableEvent, { kind: 'broker.fill' }>['payload']['fill']
): string {
  const rejection = [fill.reject_reason, fill.reject_message]
    .filter((detail): detail is string => Boolean(detail))
    .join(': ');
  return `${fill.status} / ${fill.filled_size} filled${rejection ? ` / ${rejection}` : ''}`;
}
