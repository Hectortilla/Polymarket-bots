import { RESOURCE_LIMIT_CASES, RESOURCE_LIMIT_DETAIL } from '$lib/limits/testFixtures';
import { lookupMarkets, searchMarkets, type MarketSuggestion } from '$lib/api/generated';
import { MARKET_SELECTOR_COPY } from '$lib/catalog/copy';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import catalogContract from './catalogContract.fixture.json';
import MarketSelector from './MarketSelector.svelte';

vi.mock('$lib/api/generated', () => ({ searchMarkets: vi.fn(), lookupMarkets: vi.fn() }));

const market: MarketSuggestion = {
  slug: 'bitcoin-above-100k',
  condition_id: 'bitcoin-condition',
  question: 'Will Bitcoin reach $100,000?',
  event_title: 'Bitcoin in September',
  end_date: '2026-09-30T00:00:00Z',
  is_open_for_trading: true,
};

function results(markets = [market], hasMore = false) {
  return { data: { markets, has_more: hasMore } } as Awaited<
    ReturnType<typeof searchMarkets<true>>
  >;
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(searchMarkets).mockResolvedValue(results());
  vi.mocked(lookupMarkets).mockResolvedValue({ data: [] } as unknown as Awaited<
    ReturnType<typeof lookupMarkets>
  >);
});
afterEach(cleanup);

async function search(query = 'Bitcoin') {
  const input = screen.getByRole('combobox');
  await fireEvent.focus(input);
  await fireEvent.input(input, { target: { value: query } });
  return input;
}

describe('MarketSelector', () => {
  it('debounces typing, shows metadata and selects with the keyboard', async () => {
    const onchange = vi.fn();
    render(MarketSelector, { value: [], onchange, labelId: 'markets' });
    const input = await search('B');
    expect(searchMarkets).not.toHaveBeenCalled();
    await search('Bit');
    await search('Bitcoin');
    expect(searchMarkets).not.toHaveBeenCalled();
    await screen.findByRole('option', { name: /Will Bitcoin/ });
    expect(searchMarkets).toHaveBeenCalledTimes(1);
    expect(searchMarkets).toHaveBeenCalledWith(
      expect.objectContaining({
        query: { q: 'Bitcoin', limit: catalogContract.marketSearch.defaultLimit },
      }),
    );
    expect(screen.getByText(market.event_title!)).toBeTruthy();
    await fireEvent.keyDown(input, { key: 'ArrowDown' });
    expect(input.getAttribute('aria-activedescendant')).toBeTruthy();
    await fireEvent.keyDown(input, { key: 'Enter' });
    expect(onchange).toHaveBeenCalledWith([market.slug]);
    expect((input as HTMLInputElement).value).toBe('');
    expect(input).toHaveAttribute('aria-expanded', 'false');
  });

  it('adds more markets, prevents duplicates, and removes a selection', async () => {
    const onchange = vi.fn();
    const other = { ...market, slug: 'other', question: 'Another market?' };
    vi.mocked(searchMarkets).mockResolvedValue(results([market, other]));
    vi.mocked(lookupMarkets).mockResolvedValue({ data: [market] } as Awaited<
      ReturnType<typeof lookupMarkets>
    >);
    const view = render(MarketSelector, { value: [market.slug], onchange, labelId: 'markets' });
    await search();
    const selected = await screen.findByRole('option', { name: /Will Bitcoin/ });
    expect(selected.getAttribute('aria-selected')).toBe('true');
    await fireEvent.click(selected);
    expect(onchange).not.toHaveBeenCalled();
    await fireEvent.click(screen.getByRole('option', { name: /Another market/ }));
    expect(onchange).toHaveBeenLastCalledWith([market.slug, other.slug]);
    await view.rerender({ value: [market.slug, other.slug] });
    await fireEvent.click(screen.getByRole('button', { name: `Remove ${market.question}` }));
    expect(onchange).toHaveBeenLastCalledWith([other.slug]);
  });

  it('starts at the last result when navigating upward', async () => {
    const last = { ...market, slug: 'last', question: 'Last market?' };
    vi.mocked(searchMarkets).mockResolvedValue(results([market, last]));
    const onchange = vi.fn();
    render(MarketSelector, { value: [], onchange, labelId: 'markets' });
    const input = await search();
    await screen.findByRole('option', { name: /Last market/ });
    await fireEvent.keyDown(input, { key: 'ArrowUp' });
    await fireEvent.keyDown(input, { key: 'Enter' });
    expect(onchange).toHaveBeenCalledWith([last.slug]);
  });

  it('aborts and ignores old responses after a new query', async () => {
    let completeOld!: (value: Awaited<ReturnType<typeof searchMarkets<true>>>) => void;
    vi.mocked(searchMarkets).mockImplementationOnce(
      () =>
        new Promise<Awaited<ReturnType<typeof searchMarkets<true>>>>(
          (resolve) => (completeOld = resolve),
        ),
    );
    render(MarketSelector, { value: [], onchange: vi.fn(), labelId: 'markets' });
    await search('old query');
    await waitFor(() => expect(searchMarkets).toHaveBeenCalledTimes(1));
    const signal = vi.mocked(searchMarkets).mock.calls[0][0].signal!;
    await search('new query');
    expect(signal.aborted).toBe(true);
    await screen.findByRole('option', { name: /Will Bitcoin/ });
    completeOld(results([{ ...market, slug: 'stale', question: 'Stale result' }]));
    await Promise.resolve();
    expect(screen.queryByText('Stale result')).toBeNull();
  });

  it.each(RESOURCE_LIMIT_CASES)('offers retry after a search failure and handles no matches (%s)', async (code) => {
    vi.mocked(searchMarkets)
      .mockRejectedValueOnce(code ? { code, detail: RESOURCE_LIMIT_DETAIL } : new Error('offline'))
      .mockResolvedValue(results([]));
    render(MarketSelector, { value: [], onchange: vi.fn(), labelId: 'markets' });
    await search();
    if (code) expect(await screen.findByText(RESOURCE_LIMIT_DETAIL)).toBeTruthy();
    await fireEvent.click(
      await screen.findByRole('button', { name: MARKET_SELECTOR_COPY.RETRY_SEARCH }),
    );
    expect(screen.getByRole('combobox')).toHaveFocus();
    expect(screen.getByRole('combobox')).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('combobox')).not.toHaveValue('');
    expect(await screen.findByText(MARKET_SELECTOR_COPY.NO_RESULTS)).toBeTruthy();
  });

  it('keeps unavailable saved selections visible and removable', async () => {
    vi.mocked(lookupMarkets).mockResolvedValue({
      data: [{ ...market, is_open_for_trading: false }],
    } as Awaited<ReturnType<typeof lookupMarkets>>);
    const onchange = vi.fn();
    render(MarketSelector, { value: [market.slug, 'missing'], onchange, labelId: 'markets' });
    expect(await screen.findByText(MARKET_SELECTOR_COPY.UNAVAILABLE)).toBeTruthy();
    expect(await screen.findByText(MARKET_SELECTOR_COPY.MISSING)).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: 'Remove missing' }));
    expect(onchange).toHaveBeenCalledWith([market.slug]);
  });

  it('preserves selections when lookup fails and retries hydration', async () => {
    vi.mocked(lookupMarkets)
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValue({ data: [market] } as Awaited<ReturnType<typeof lookupMarkets>>);
    const onchange = vi.fn();
    render(MarketSelector, { value: [market.slug], onchange, labelId: 'markets' });
    await fireEvent.click(
      await screen.findByRole('button', { name: MARKET_SELECTOR_COPY.RETRY_DETAILS }),
    );
    expect(await screen.findByText(market.question)).toBeTruthy();
    expect(onchange).not.toHaveBeenCalled();
  });

  it('closes on Escape and aborts in-flight requests on unmount', async () => {
    vi.mocked(searchMarkets).mockImplementation(() => new Promise<never>(() => {}));
    const view = render(MarketSelector, { value: [], onchange: vi.fn(), labelId: 'markets' });
    const input = await search();
    await waitFor(() => expect(searchMarkets).toHaveBeenCalledTimes(1));
    await fireEvent.keyDown(input, { key: 'Escape' });
    expect(input.getAttribute('aria-expanded')).toBe('false');
    const signal = vi.mocked(searchMarkets).mock.calls[0][0].signal!;
    view.unmount();
    expect(signal.aborted).toBe(true);
  });

  it('shows the refinement hint and respects the selection limit', async () => {
    vi.mocked(searchMarkets).mockResolvedValue(results([market], true));
    const view = render(MarketSelector, { value: [], onchange: vi.fn(), labelId: 'markets' });
    await search();
    expect(await screen.findByText(/More matches available/)).toBeTruthy();
    const selected = Array.from(
      { length: catalogContract.marketSearch.maximumSelections },
      (_, index) => `market-${index}`,
    );
    await view.rerender({ value: selected });
    expect((screen.getByRole('combobox') as HTMLInputElement).disabled).toBe(true);
    expect(screen.getAllByRole('button', { name: /^Remove/ })).toHaveLength(selected.length);
  });
});
