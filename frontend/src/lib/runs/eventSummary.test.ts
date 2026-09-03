import { describe, expect, it } from 'vitest';

import { SIDE } from '$lib/charts/contracts';
import runtimeContract from '$lib/runtimeContract.fixture.json';
import type { FillRejectReason, OrderStatus } from '$lib/api/generated';
import {
  EVENT_KIND,
  type PersistedDurableEvent
} from './durableEvents';
import { eventFailureDetail, eventSummary } from './eventSummary';
import { RUN_STATUS } from './status';

const RUN_ID = '00000000-0000-0000-0000-000000000001';
type BrokerFillEvent = Extract<
  PersistedDurableEvent,
  { kind: typeof EVENT_KIND.brokerFill }
>;

describe('event summary', () => {
  it('includes a fill rejection reason and message when provided', () => {
    expect(eventSummary(rejectedFill())).toBe(
      'rejected / 0 filled / bad_size: order size is below the market minimum'
    );
  });

  it('does not add an empty rejection detail to a completed fill', () => {
    const fill = rejectedFill();
    fill.payload.fill = {
      ...fill.payload.fill,
      status: runtimeContract.orderStatus.FILLED as OrderStatus,
      filled_size: '5',
      average_price: '0.5',
      reject_reason: null,
      reject_message: null
    };

    expect(eventSummary(fill)).toBe('filled / 5 filled');
  });

  it('prefers the latest runtime error and retains a distinct recorded outcome', () => {
    const firstFailure = runFailure(1, 'ValueError: first failure');
    const latestFailure = runFailure(2, 'ConnectionError: stream closed');
    const lifecycle = failedLifecycle(3);

    expect(
      eventFailureDetail(
        lifecycle,
        [firstFailure, latestFailure, lifecycle],
        'ConnectionError: paper run failed'
      )
    ).toBe(
      'ConnectionError: stream closed\nRecorded failure: ConnectionError: paper run failed'
    );
  });

  it('uses the durable run failure detail when no runtime error event is loaded', () => {
    const lifecycle = failedLifecycle(2);

    expect(
      eventFailureDetail(lifecycle, [lifecycle], 'RuntimeError: run launch failed')
    ).toBe('RuntimeError: run launch failed');
  });
});

function runFailure(
  id: number,
  error: string
): Extract<PersistedDurableEvent, { kind: typeof EVENT_KIND.runFailure }> {
  return {
    id,
    kind: EVENT_KIND.runFailure,
    run_id: RUN_ID,
    occurred_at: '2026-08-24T00:00:00Z',
    payload: { error }
  };
}

function failedLifecycle(
  id: number
): Extract<PersistedDurableEvent, { kind: typeof EVENT_KIND.runLifecycle }> {
  return {
    id,
    kind: EVENT_KIND.runLifecycle,
    run_id: RUN_ID,
    occurred_at: '2026-08-24T00:00:00Z',
    payload: { status: RUN_STATUS.FAILED }
  };
}

function rejectedFill(): BrokerFillEvent {
  return {
    id: 1,
    kind: EVENT_KIND.brokerFill,
    run_id: RUN_ID,
    occurred_at: '2026-08-24T00:00:00Z',
    payload: {
      order: {
        token_id: 'token',
        side: SIDE.buy,
        price: '0.5',
        size: '5'
      },
      fill: {
        order_id: 'order',
        token_id: 'token',
        side: SIDE.buy,
        status: runtimeContract.orderStatus.REJECTED as OrderStatus,
        requested_size: '5',
        filled_size: '0',
        average_price: null,
        fee_usdc: '0',
        received_at_ms: 1,
        reject_reason: runtimeContract.fillRejectReason.BAD_SIZE as FillRejectReason,
        reject_message: 'order size is below the market minimum'
      },
      latency_ms: 0,
      portfolio: null
    }
  };
}
