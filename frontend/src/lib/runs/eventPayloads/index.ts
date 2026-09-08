import type { PersistedDurableEvent } from '$lib/api/generated';

import runtimeContract from '$lib/runtimeContract.fixture.json';

import { isNonemptyString, isOneOf, isRecord } from '$lib/valueGuards';

import { isChartSamplePayload, isStreamHealthPayload, isWalletTimelinePayload } from '$lib/runs/dashboardPayloads';

import { EVENT_KIND } from '$lib/runs/eventKinds';

import {
  isActivityPayload,
  isBootstrapPayload,
  isLifecyclePayload,
} from '$lib/runs/eventPayloads/lifecycle';

import { isBrokerFillPayload, isOrderRequest } from '$lib/runs/eventPayloads/broker';

import { isMarketSettlementPayload, isPortfolioSnapshot } from '$lib/runs/eventPayloads/portfolio';

const WALLET_TRADE_KINDS = Object.values(runtimeContract.walletTradeKind);

export function isDurableEventPayload(
  kind: PersistedDurableEvent['kind'],
  payload: Record<string, unknown>,
): boolean {
  switch (kind) {
    case EVENT_KIND.runLifecycle:
      return isLifecyclePayload(payload);
    case EVENT_KIND.runBootstrap:
      return isBootstrapPayload(payload);
    case EVENT_KIND.botActivity:
      return isActivityPayload(payload);
    case EVENT_KIND.brokerOrder:
      return isRecord(payload.order) && isOrderRequest(payload.order);
    case EVENT_KIND.brokerFill:
      return isBrokerFillPayload(payload);
    case EVENT_KIND.brokerFailure:
      return (
        isRecord(payload.order) && isOrderRequest(payload.order) && isNonemptyString(payload.error)
      );
    case EVENT_KIND.marketSettlement:
      return isMarketSettlementPayload(payload);
    case EVENT_KIND.portfolioSnapshot:
      return isPortfolioSnapshot(payload);
    case EVENT_KIND.walletTimeline:
      return isWalletTimelinePayload(payload) && isWalletTradeKind(payload);
    case EVENT_KIND.streamHealth:
      return isStreamHealthPayload(payload);
    case EVENT_KIND.runFailure:
      return isNonemptyString(payload.error);
    case EVENT_KIND.chartSample:
      return isChartSamplePayload(payload);
    default:
      return kind satisfies never;
  }
}

function isWalletTradeKind(payload: Record<string, unknown>): boolean {
  return (
    isRecord(payload.trade) &&
    (payload.trade.kind === undefined || isOneOf(payload.trade.kind, WALLET_TRADE_KINDS))
  );
}
