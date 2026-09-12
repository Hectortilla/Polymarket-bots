import type { NodeGraph } from "$lib/api/generated";
import { previewGraph } from "$lib/api/generated";
import { validateControlPlaneResponse } from "$lib/api/responseValidation/index";
import { GRAPH_PREVIEW_COPY, intendedOrdersLabel } from "$lib/catalog/copy";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import fixture from "./graphPreview.fixture.json";
import GraphPreview from "./GraphPreview.svelte";
import { TEST_GRAPH_CATALOG } from "./nodeGraphTestFixtures";

vi.mock("$lib/api/generated", async (importOriginal) => ({
  ...(await importOriginal<typeof import("$lib/api/generated")>()),
  previewGraph: vi.fn(),
}));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("decision preview", () => {
  it("renders real backend-shaped results and submits exact string cash", async () => {
    vi.mocked(previewGraph).mockResolvedValue({ data: fixture.response } as never);
    render(GraphPreview, {
      graph: fixture.request.graph as NodeGraph,
      catalog: TEST_GRAPH_CATALOG,
    });
    expect(
      JSON.parse((screen.getByLabelText(GRAPH_PREVIEW_COPY.SAMPLE_POSITIONS) as HTMLTextAreaElement).value),
    ).toEqual(TEST_GRAPH_CATALOG.sample_positions);
    await fireEvent.input(screen.getByLabelText(GRAPH_PREVIEW_COPY.AVAILABLE_CASH), {
      target: { value: "9007199254740993.01" },
    });
    await fireEvent.click(screen.getByRole("button", { name: GRAPH_PREVIEW_COPY.PREVIEW, hidden: true }));
    await waitFor(() => expect(previewGraph).toHaveBeenCalled());
    expect(vi.mocked(previewGraph).mock.calls[0][0].body?.portfolio?.available_cash).toBe("9007199254740993.01");
    expect(vi.mocked(previewGraph).mock.calls[0][0].body?.portfolio?.positions).toEqual(
      TEST_GRAPH_CATALOG.sample_positions,
    );
    expect(await screen.findByText(intendedOrdersLabel(1))).toBeTruthy();
    expect(screen.getAllByText(GRAPH_PREVIEW_COPY.UNAVAILABLE).length).toBeGreaterThan(0);
    await expect(validateControlPlaneResponse(fixture.response)).resolves.toBeUndefined();
  });
  it("shows invalid JSON without calling the backend", async () => {
    render(GraphPreview, {
      graph: fixture.request.graph as NodeGraph,
      catalog: TEST_GRAPH_CATALOG,
    });
    await fireEvent.input(screen.getByLabelText(GRAPH_PREVIEW_COPY.SAMPLE_EVENT), { target: { value: "{invalid" } });
    await fireEvent.click(screen.getByRole("button", { name: GRAPH_PREVIEW_COPY.PREVIEW, hidden: true }));
    expect(previewGraph).not.toHaveBeenCalled();
    expect(screen.getByRole("alert", { hidden: true })).toBeTruthy();
  });
});
