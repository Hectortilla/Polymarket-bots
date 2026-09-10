import type { GridComponentOption, TooltipComponentOption } from "echarts/components";

export const CHART_COLORS = {
  text: "#bbc3be",
  muted: "#858f89",
  grid: "rgba(235, 244, 239, 0.08)",
  surface: "#151b17",
  border: "rgba(235, 244, 239, 0.18)",
  buy: "#72df98",
  sell: "#ff847c",
} as const;

export const CHART_FONT = '"Geist Mono Variable", monospace';

export const PRICE_CHART_GRID: GridComponentOption = {
  left: 76,
  right: 28,
  top: 36,
  bottom: 48,
  outerBounds: { left: 16, right: 16, top: 24, bottom: 20 },
};

export const TIME_AXIS = {
  type: "time",
  splitNumber: 5,
  boundaryGap: ["2%", "2%"],
  axisLine: { show: false },
  axisTick: { show: false },
  axisLabel: { color: CHART_COLORS.muted, fontFamily: CHART_FONT, fontSize: 11, margin: 16, hideOverlap: true },
  splitLine: { show: false },
} as const;

export const VALUE_AXIS = {
  type: "value",
  splitNumber: 4,
  axisLine: { show: false },
  axisTick: { show: false },
  axisLabel: { color: CHART_COLORS.muted, fontFamily: CHART_FONT, fontSize: 11, margin: 14 },
  splitLine: { lineStyle: { color: CHART_COLORS.grid } },
} as const;

export function priceChartTooltip(formatValue: (value: number) => string): TooltipComponentOption {
  return {
    trigger: "axis",
    confine: true,
    enterable: true,
    transitionDuration: 0,
    backgroundColor: CHART_COLORS.surface,
    borderColor: CHART_COLORS.border,
    borderWidth: 1,
    padding: 12,
    textStyle: { color: CHART_COLORS.text, fontFamily: CHART_FONT, fontSize: 12 },
    extraCssText: "max-width: min(360px, 80%); white-space: normal; box-shadow: none; border-radius: 6px;",
    axisPointer: {
      type: "line",
      animation: false,
      lineStyle: { color: CHART_COLORS.muted, width: 1, type: "dashed" },
    },
    formatter(params) {
      const entries = (Array.isArray(params) ? params : [params]).filter(
        (entry) => Array.isArray(entry.value) && entry.value[1] != null,
      );
      if (!entries.length) return "";
      const root = document.createElement("div");
      root.className = "chart-tooltip";
      const time = document.createElement("div");
      time.className = "chart-tooltip-time";
      time.textContent = new Date((entries[0].value as number[])[0]).toLocaleString();
      root.append(time);
      for (const entry of entries) {
        const row = document.createElement("div");
        row.className = "chart-tooltip-row";
        const swatch = document.createElement("span");
        swatch.className = "chart-tooltip-swatch";
        if (typeof entry.color === "string") swatch.style.backgroundColor = entry.color;
        const label = document.createElement("span");
        label.textContent = entry.name || entry.seriesName || "";
        const value = document.createElement("strong");
        value.textContent = formatValue((entry.value as number[])[1]);
        row.append(swatch, label, value);
        root.append(row);
      }
      return root;
    },
  };
}
