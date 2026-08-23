import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { DurableEvent, RunRead } from '$lib/api/generated';
import {
  readRunApiV1RunsRunIdGet,
  readRunEventsApiV1RunsRunIdEventsGet
} from '$lib/api/generated';
import { EVENT_KIND } from './durableEvents';
import { loadAndContinueRunDetail, loadOlderRunEvents } from './hydrate';

vi.mock('$lib/api/generated', async (importOriginal) => {
  const original = await importOriginal<typeof import('$lib/api/generated')>();
  return {
    ...original,
    readRunApiV1RunsRunIdGet: vi.fn(),
    readRunEventsApiV1RunsRunIdEventsGet: vi.fn()
  };
});

const RUN: RunRead = {
  id: 'aaaaaaaa-0000-0000-0000-000000000001',
  definition_id: 'test-definition',
  definition_version: 1,
  config: {
    name: 'Hydrated run',
    stream_rules: [],
    data_trades_budget_per_10s: 180,
    max_order_size: '10',
    max_slippage_pct: '0.02',
    paper_latency_ms: 250,
    paper_latency_jitter_ms: 100,
    event_max_age_ms: 5000,
    paper_portfolio_usdc: '1000'
  },
  status: 'running',
  created_at: '2026-08-23T00:00:00Z'
};

const EVENT: DurableEvent = {
  id: 7,
  kind: EVENT_KIND.runLifecycle,
  run_id: RUN.id,
  occurred_at: '2026-08-23T00:00:01Z',
  payload: { status: 'running' }
};

describe('run reload', () => {
  beforeEach(() => vi.clearAllMocks());

  it('hydrates ordinary HTTP state before opening SSE from the durable cursor', async () => {
    vi.mocked(readRunApiV1RunsRunIdGet).mockResolvedValue({ data: RUN } as never);
    vi.mocked(readRunEventsApiV1RunsRunIdEventsGet).mockResolvedValue({
      data: { events: [EVENT], next_before_event_id: 7 }
    } as never);
    const calls: string[] = [];
    const openStream = vi.fn(() => {
      calls.push('stream');
      return () => {};
    });

    await loadAndContinueRunDetail(
      RUN.id.toUpperCase(),
      (hydration) => {
        calls.push('hydrated');
        expect(hydration.run).toEqual(RUN);
        expect(hydration.events).toEqual([EVENT]);
        expect(hydration.nextBeforeEventId).toBe(7);
      },
      vi.fn(),
      openStream
    );

    expect(calls).toEqual(['hydrated', 'stream']);
    expect(openStream).toHaveBeenCalledWith(RUN.id, 7, expect.any(Function));
    expect(readRunEventsApiV1RunsRunIdEventsGet).toHaveBeenCalledWith({
      path: { run_id: RUN.id },
      throwOnError: true
    });
  });

  it('does not open SSE when the hydrated run is terminal', async () => {
    vi.mocked(readRunApiV1RunsRunIdGet).mockResolvedValue({
      data: { ...RUN, status: 'stopped' }
    } as never);
    vi.mocked(readRunEventsApiV1RunsRunIdEventsGet).mockResolvedValue({
      data: { events: [EVENT], next_before_event_id: null }
    } as never);
    const openStream = vi.fn();

    const close = await loadAndContinueRunDetail(
      RUN.id,
      vi.fn(),
      vi.fn(),
      openStream
    );

    expect(openStream).not.toHaveBeenCalled();
    expect(close()).toBeUndefined();
  });

  it('does not open SSE past a terminal event committed during hydration', async () => {
    vi.mocked(readRunApiV1RunsRunIdGet).mockResolvedValue({ data: RUN } as never);
    vi.mocked(readRunEventsApiV1RunsRunIdEventsGet).mockResolvedValue({
      data: {
        events: [{ ...EVENT, payload: { status: 'stopped' } }],
        next_before_event_id: null
      }
    } as never);
    const openStream = vi.fn();

    await loadAndContinueRunDetail(RUN.id, vi.fn(), vi.fn(), openStream);

    expect(openStream).not.toHaveBeenCalled();
  });

  it('loads only the older page selected by the server cursor', async () => {
    const olderEvent = { ...EVENT, id: 3 };
    vi.mocked(readRunEventsApiV1RunsRunIdEventsGet).mockResolvedValue({
      data: { events: [olderEvent], next_before_event_id: null }
    } as never);

    const page = await loadOlderRunEvents(RUN.id, 7);

    expect(page).toEqual({ events: [olderEvent], nextBeforeEventId: null });
    expect(readRunEventsApiV1RunsRunIdEventsGet).toHaveBeenCalledWith({
      path: { run_id: RUN.id },
      query: { before_event_id: 7 },
      throwOnError: true
    });

    vi.mocked(readRunEventsApiV1RunsRunIdEventsGet).mockResolvedValue({
      data: { events: [olderEvent], next_before_event_id: 4 }
    } as never);
    await expect(loadOlderRunEvents(RUN.id, 7)).rejects.toThrow(
      'Invalid run event page cursor'
    );
  });
});
