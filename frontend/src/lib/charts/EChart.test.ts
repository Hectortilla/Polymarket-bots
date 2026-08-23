import { render } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import EChart from './EChart.svelte';

const mocks = vi.hoisted(() => {
  const chart = {
    setOption: vi.fn(),
    resize: vi.fn(),
    dispose: vi.fn()
  };
  return { chart, init: vi.fn(() => chart) };
});

vi.mock('./echarts', () => ({ init: mocks.init }));

class FakeResizeObserver {
  static current: FakeResizeObserver;
  observe = vi.fn();
  disconnect = vi.fn();

  constructor(readonly callback: ResizeObserverCallback) {
    FakeResizeObserver.current = this;
  }

  trigger(width: number, height: number): void {
    this.callback([
      { contentRect: { width, height } }
    ] as ResizeObserverEntry[], this as never);
  }
}

const frames = new Map<number, FrameRequestCallback>();
let nextFrameId = 1;

afterEach(() => {
  frames.clear();
  nextFrameId = 1;
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe('EChart lifecycle', () => {
  it('updates incrementally and coalesces resize work', async () => {
    vi.stubGlobal('ResizeObserver', FakeResizeObserver);
    const requestFrame = vi.fn((callback: FrameRequestCallback) => {
      const frameId = nextFrameId;
      nextFrameId += 1;
      frames.set(frameId, callback);
      return frameId;
    });
    const cancelFrame = vi.fn((frameId: number) => frames.delete(frameId));
    vi.stubGlobal('requestAnimationFrame', requestFrame);
    vi.stubGlobal('cancelAnimationFrame', cancelFrame);
    const first = { series: [] };
    const view = render(EChart, { option: first, label: 'Test chart' });
    const updateOptions = {
      notMerge: false,
      lazyUpdate: true,
      replaceMerge: ['series'],
      silent: true
    };

    expect(mocks.init).toHaveBeenCalledWith(
      expect.any(HTMLDivElement),
      undefined,
      { renderer: 'canvas', useDirtyRect: true }
    );
    expect(mocks.chart.setOption).toHaveBeenCalledWith(first, updateOptions);

    FakeResizeObserver.current.trigger(800, 500);
    FakeResizeObserver.current.trigger(700, 500);
    expect(requestFrame).toHaveBeenCalledOnce();
    expect(mocks.chart.resize).not.toHaveBeenCalled();
    frames.get(1)?.(0);
    expect(mocks.chart.resize).toHaveBeenCalledOnce();
    FakeResizeObserver.current.trigger(700, 500);
    expect(requestFrame).toHaveBeenCalledOnce();

    const second = { series: [{ type: 'line', data: [1] }] };
    await view.rerender({ option: second, label: 'Test chart' });
    expect(mocks.chart.setOption).toHaveBeenLastCalledWith(second, updateOptions);

    FakeResizeObserver.current.trigger(600, 500);
    view.unmount();
    expect(cancelFrame).toHaveBeenCalledWith(2);
    expect(mocks.chart.dispose).toHaveBeenCalledOnce();
    expect(FakeResizeObserver.current.disconnect).toHaveBeenCalledOnce();
  });
});
