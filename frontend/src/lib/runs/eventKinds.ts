import type { LiveRunEvent } from '$lib/api/generated';

export const LIVE_EVENT_KIND = {
  market: 'chart.market',
  equity: 'chart.equity',
  wallet: 'chart.wallet',
  streamHealth: 'stream.health.live'
} as const satisfies Record<string, NonNullable<LiveRunEvent['kind']>>;
