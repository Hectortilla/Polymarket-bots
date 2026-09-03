import type {
  LiveEquityChartEvent,
  LiveMarketChartEvent,
  LiveRunEvent,
  LiveStreamHealthEvent,
  LiveWalletChartEvent,
  PersistedDurableEvent
} from '$lib/api/generated';
import runtimeContract from '$lib/runtimeContract.fixture.json';

type DottedLowercase<Value extends string> =
  Value extends `${infer Head}_${infer Tail}`
    ? `${Lowercase<Head>}.${DottedLowercase<Tail>}`
    : Lowercase<Value>;
type EventKindContract = {
  [Key in keyof typeof runtimeContract.eventKind]: Extract<
    PersistedDurableEvent['kind'],
    DottedLowercase<Key>
  >;
};

const eventKindContract = runtimeContract.eventKind as EventKindContract;

export const EVENT_KIND = {
  runLifecycle: eventKindContract.RUN_LIFECYCLE,
  runBootstrap: eventKindContract.RUN_BOOTSTRAP,
  botActivity: eventKindContract.BOT_ACTIVITY,
  brokerOrder: eventKindContract.BROKER_ORDER,
  brokerFill: eventKindContract.BROKER_FILL,
  brokerFailure: eventKindContract.BROKER_FAILURE,
  marketSettlement: eventKindContract.MARKET_SETTLEMENT,
  portfolioSnapshot: eventKindContract.PORTFOLIO_SNAPSHOT,
  walletTimeline: eventKindContract.WALLET_TIMELINE,
  streamHealth: eventKindContract.STREAM_HEALTH,
  runFailure: eventKindContract.RUN_FAILURE,
  chartSample: eventKindContract.CHART_SAMPLE
} as const satisfies Record<string, PersistedDurableEvent['kind']>;

export const LIVE_EVENT_KIND = {
  market: runtimeContract.liveEventKind.CHART_MARKET as NonNullable<LiveMarketChartEvent['kind']>,
  equity: runtimeContract.liveEventKind.CHART_EQUITY as NonNullable<LiveEquityChartEvent['kind']>,
  wallet: runtimeContract.liveEventKind.CHART_WALLET as NonNullable<LiveWalletChartEvent['kind']>,
  streamHealth: runtimeContract.liveEventKind.STREAM_HEALTH as NonNullable<LiveStreamHealthEvent['kind']>
} as const satisfies Record<string, NonNullable<LiveRunEvent['kind']>>;
