import { ALLOWANCE_COPY } from './copy';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, expect, it, vi } from 'vitest';
import runtimeContract from '$lib/runtimeContract.fixture.json';
import { isAccountUsage } from './validation';

const mocks = vi.hoisted(() => ({ read: vi.fn() }));
vi.mock('$lib/api/generated', () => ({ readUsage: mocks.read }));
import AccountUsage from './AccountUsage.svelte';

const usage = { policy: runtimeContract.resourcePolicy, active_runs: 1, queued_runs: 2, saved_bots: 3, saved_templates: 4, retained_runs: 5 };
afterEach(() => { cleanup(); vi.resetAllMocks(); });

it('shows private usage and refreshes after capacity changes', async () => {
  mocks.read.mockResolvedValueOnce({ data: usage }).mockResolvedValueOnce({ data: { ...usage, queued_runs: 0 } });
  render(AccountUsage);
  expect(await screen.findByText(new RegExp(`${usage.queued_runs} / ${usage.policy.queued_runs} queued`))).toBeTruthy();
  await fireEvent.click(screen.getByRole('button', { name: ALLOWANCE_COPY.REFRESH }));
  await waitFor(() => expect(screen.getByText(new RegExp(`0 / ${usage.policy.queued_runs} queued`))).toBeTruthy());
});

it('shows unavailable usage instead of inventing free capacity', async () => {
  mocks.read.mockRejectedValue(new Error('unavailable'));
  render(AccountUsage);
  expect(await screen.findByText(ALLOWANCE_COPY.UNAVAILABLE)).toBeTruthy();
});

it('rejects missing or malformed policy and usage at the client boundary', () => {
  expect(isAccountUsage(usage)).toBe(true);
  expect(isAccountUsage({ ...usage, policy: {} })).toBe(false);
  expect(isAccountUsage({ ...usage, active_runs: -1 })).toBe(false);
  expect(isAccountUsage({ ...usage, queued_runs: '0' })).toBe(false);
});
