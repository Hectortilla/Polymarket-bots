import { fireEvent, render } from "@testing-library/svelte";
import { afterEach, expect, it, vi } from "vitest";
import type { ChartSamplePayload } from "$lib/api/generated";
import { SIDE } from "$lib/sides";
import { VALUATION_STATUS } from "./contracts";
import MarketChart from "./MarketChart.svelte";

const mocks = vi.hoisted(() => ({ setOption: vi.fn() }));
vi.mock("./echarts", () => ({
  init: () => ({ setOption: mocks.setOption, resize: vi.fn(), dispose: vi.fn() }),
}));

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

it("preserves market visibility across sample updates and toggles it back on", async () => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
  const sample: ChartSamplePayload = {
    sampled_at_ms: 1_000,
    equity: { value: "100", status: VALUATION_STATUS.fresh },
    markets: [
      { token_id: "token", label: "Market Yes", value: "0.5", status: VALUATION_STATUS.fresh, markers: [SIDE.buy] },
    ],
  };
  const view = render(MarketChart, { samples: [sample] });
  const toggle = view.getByRole("button", { name: "Market Yes" });
  expect(toggle).toHaveAttribute("aria-pressed", "true");
  await fireEvent.click(toggle);
  expect(toggle).toHaveAttribute("aria-pressed", "false");
  expect(mocks.setOption.mock.lastCall?.[0].series).toHaveLength(0);
  await view.rerender({ samples: [sample, { ...sample, sampled_at_ms: 2_000 }] });
  expect(mocks.setOption.mock.lastCall?.[0].series).toHaveLength(0);
  await fireEvent.click(toggle);
  expect(toggle).toHaveAttribute("aria-pressed", "true");
  expect(mocks.setOption.mock.lastCall?.[0].series).toHaveLength(3);
});
