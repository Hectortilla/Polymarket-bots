import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { tick } from 'svelte';

import type { ChartSamplePayload } from '$lib/api/generated';

const echartsMocks = vi.hoisted(() => {
  const instances: Array<{
    setOption: ReturnType<typeof vi.fn>;
    resize: ReturnType<typeof vi.fn>;
    dispose: ReturnType<typeof vi.fn>;
  }> = [];
  return {
    instances,
    init: vi.fn(() => {
      const chart = {
        setOption: vi.fn(),
        resize: vi.fn(),
        dispose: vi.fn()
      };
      instances.push(chart);
      return chart;
    })
  };
});

vi.mock('./echarts', () => ({ init: echartsMocks.init }));

import DashboardCharts from './DashboardCharts.svelte';
import { DASHBOARD_KEY, SIDE, VALUATION_STATUS } from './contracts';

class FakeResizeObserver {
  static instances: FakeResizeObserver[] = [];
  observe = vi.fn();
  disconnect = vi.fn();

  constructor(readonly callback: ResizeObserverCallback) {
    FakeResizeObserver.instances.push(this);
  }

  trigger(width: number, height = 520): void {
    this.callback([
      { contentRect: { width, height } }
    ] as ResizeObserverEntry[], this as never);
  }
}

class FakeIntersectionObserver {
  static current: FakeIntersectionObserver;
  observe = vi.fn();
  disconnect = vi.fn();

  constructor(readonly callback: IntersectionObserverCallback) {
    FakeIntersectionObserver.current = this;
  }

  trigger(isIntersecting: boolean): void {
    this.callback([{ isIntersecting }] as IntersectionObserverEntry[], this as never);
  }
}

const animationFrames = new Map<number, FrameRequestCallback>();
let nextAnimationFrame = 1;

afterEach(() => {
  cleanup();
  FakeResizeObserver.instances = [];
  echartsMocks.instances.length = 0;
  animationFrames.clear();
  nextAnimationFrame = 1;
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe('dashboard controls and layout', () => {
  it('exposes matching buttons and keyboard navigation', async () => {
    installBrowserObservers();
    const view = render(DashboardCharts, {
      samples: [],
      walletTimelinePoints: []
    });

    expect(screen.getByRole('button', { name: /v · view/i })).toBeTruthy();
    const closer = view.container.querySelector<HTMLButtonElement>(
      `button[title="Keyboard: ${DASHBOARD_KEY.closer}"]`
    );
    const wider = view.container.querySelector<HTMLButtonElement>(
      `button[title="Keyboard: ${DASHBOARD_KEY.wider}"]`
    );
    if (!closer || !wider) throw new Error('zoom controls not rendered');
    for (let index = 0; index < 3; index += 1) await fireEvent.click(closer);
    expect(closer.disabled).toBe(true);
    expect(wider.disabled).toBe(false);
    for (let index = 0; index < 6; index += 1) await fireEvent.click(wider);
    expect(wider.disabled).toBe(true);
    await fireEvent.keyDown(window, { key: DASHBOARD_KEY.view });
    expect(screen.getByRole('heading', { name: 'Followed-wallet activity' })).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: /r · reset/i }));
    expect(screen.getByRole<HTMLButtonElement>('button', { name: /r · reset/i }).disabled).toBe(true);
  });

  it('stacks the market and executable-equity charts', async () => {
    installBrowserObservers();
    const view = render(DashboardCharts, {
      samples: [],
      walletTimelinePoints: [{
        source_key: 'wallet:trade',
        wallet: '0x0000000000000000000000000000000000000001',
        trade_timestamp_ms: 1_000,
        side: SIDE.buy,
        notional: '1',
        market_label: 'market',
        accepted: true
      }]
    });
    FakeIntersectionObserver.current.trigger(true);
    await tick();
    const grid = view.container.querySelector('.dashboard-grid');

    expect(grid?.getAttribute('data-layout')).toBe('stacked');
  });

  it('presents durable samples as history for a terminal run', async () => {
    installBrowserObservers();
    const view = render(DashboardCharts, {
      samples: [chartSample(1_000, '100')],
      walletTimelinePoints: [],
      terminal: true
    });
    FakeIntersectionObserver.current.trigger(true);
    await tick();

    expect(view.container.textContent).toContain('Run history');
    expect(view.container.textContent).not.toContain('Live dashboard');
    expect(echartsMocks.instances).toHaveLength(2);
  });

  it('keeps configured wallets visible before their first trade', async () => {
    installBrowserObservers();
    const view = render(DashboardCharts, {
      samples: [],
      walletTimelinePoints: [],
      configuredWallets: Array.from({ length: 7 }, (_, index) => `wallet-${index}`)
    });
    FakeIntersectionObserver.current.trigger(true);
    await tick();

    const viewButton = view.container.querySelector<HTMLButtonElement>(
      `button[title="Keyboard: ${DASHBOARD_KEY.view}"]`
    );
    if (!viewButton) throw new Error('view control not rendered');
    await fireEvent.click(viewButton);

    const nextButton = view.container.querySelector<HTMLButtonElement>(
      `button[title="Keyboard: ${DASHBOARD_KEY.nextWalletPage}"]`
    );
    const previousButton = view.container.querySelector<HTMLButtonElement>(
      `button[title="Keyboard: ${DASHBOARD_KEY.previousWalletPage}"]`
    );
    if (!nextButton || !previousButton) throw new Error('wallet controls not rendered');
    expect(nextButton.disabled).toBe(false);
    await fireEvent.click(nextButton);
    expect(nextButton.disabled).toBe(true);
    expect(previousButton.disabled).toBe(false);
    await fireEvent.click(previousButton);
    expect(previousButton.disabled).toBe(true);

    expect(
      view.container.querySelector('[aria-label="Followed-wallet trade timeline"]')
    ).toBeTruthy();
    expect(view.container.textContent).not.toContain(
      'No followed wallets configured or detected.'
    );
  });

  it('freezes chart options offscreen and catches up once on re-entry', async () => {
    installBrowserObservers();
    const first = chartSample(1_000, '100');
    const second = chartSample(1_250, '101');
    const view = render(DashboardCharts, {
      samples: [first],
      walletTimelinePoints: []
    });

    expect(echartsMocks.instances).toHaveLength(0);
    FakeIntersectionObserver.current.trigger(true);
    await tick();
    expect(echartsMocks.instances).toHaveLength(2);
    const visibleUpdateCounts = echartsMocks.instances.map(
      ({ setOption }) => setOption.mock.calls.length
    );

    FakeIntersectionObserver.current.trigger(false);
    await tick();
    await view.rerender({
      samples: [first, second],
      walletTimelinePoints: []
    });
    expect(echartsMocks.instances.map(
      ({ setOption }) => setOption.mock.calls.length
    )).toEqual(visibleUpdateCounts);

    FakeIntersectionObserver.current.trigger(true);
    await tick();
    expect(echartsMocks.instances.map(
      ({ setOption }) => setOption.mock.calls.length
    )).toEqual(visibleUpdateCounts.map((count) => count + 1));
  });
});

function installBrowserObservers(): void {
  vi.stubGlobal('ResizeObserver', FakeResizeObserver);
  vi.stubGlobal('IntersectionObserver', FakeIntersectionObserver);
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    const frameId = nextAnimationFrame;
    nextAnimationFrame += 1;
    animationFrames.set(frameId, callback);
    return frameId;
  });
  vi.stubGlobal('cancelAnimationFrame', (frameId: number) => {
    animationFrames.delete(frameId);
  });
}

function chartSample(sampledAtMs: number, equity: string): ChartSamplePayload {
  return {
    sampled_at_ms: sampledAtMs,
    markets: [{
      token_id: 'token',
      label: 'Market',
      value: '0.5',
      status: VALUATION_STATUS.fresh,
      markers: []
    }],
    equity: { value: equity, status: VALUATION_STATUS.fresh }
  };
}
