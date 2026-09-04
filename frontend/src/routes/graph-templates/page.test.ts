import { cleanup, render, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ goto: vi.fn() }));

vi.mock('$app/navigation', () => ({ goto: mocks.goto }));

import Page from './+page.svelte';

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('retired graph-template route', () => {
  it('opens the unified bot builder', async () => {
    render(Page);

    await waitFor(() => {
      expect(mocks.goto).toHaveBeenCalledWith('/bots/new', {
        replaceState: true
      });
    });
  });
});
