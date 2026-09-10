import { describe, expect, it } from "vitest";
import { priceChartTooltip } from "./appearance";

describe("price chart tooltip", () => {
  it("omits missing values, retains zero prices, and renders external labels as text", () => {
    const tooltip = priceChartTooltip((value) => value.toFixed(3));
    if (typeof tooltip.formatter !== "function") throw new Error("Expected a tooltip formatter");
    const entry = {
      componentType: "series",
      componentSubType: "line",
      componentIndex: 0,
      dataIndex: 0,
      name: "",
      data: null,
      $vars: [],
      seriesName: '<img src=x onerror="alert(1)">',
      color: "#57d3ff",
    };
    const result = tooltip.formatter(
      [
        { ...entry, value: [1_000, null] },
        { ...entry, value: [1_000, 0] },
      ],
      "ticket",
      () => {},
    ) as HTMLElement;

    expect(result.querySelectorAll(".chart-tooltip-row")).toHaveLength(1);
    expect(result.querySelector("img")).toBeNull();
    expect(result.textContent).toContain(entry.seriesName);
    expect(result.querySelector("strong")?.textContent).toBe("0.000");
    expect(tooltip.formatter([{ ...entry, value: [1_000, null] }], "ticket", () => {})).toBe("");
  });
});
