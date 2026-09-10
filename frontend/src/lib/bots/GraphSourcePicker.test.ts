import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import type { GraphExample, NodeGraph } from "$lib/api/generated";
import validationContract from "$lib/catalog/graphValidationContract.fixture.json";
import { BOT_BUILDER_COPY } from "./copy";
import GraphSourcePicker from "./GraphSourcePicker.svelte";

describe("graph starting points", () => {
  it("copies the Random catalog graph into an independent draft", async () => {
    const scenario = validationContract.cases.find((item) => item.name === "Random")!;
    const example: GraphExample = {
      name: scenario.name,
      description: "Debug paper buys and sells.",
      graph: scenario.graph as NodeGraph,
    };
    const onselect = vi.fn();
    render(GraphSourcePicker, {
      bots: [],
      starterGraph: { nodes: [] },
      examples: [example],
      onselect,
    });
    expect(screen.getByRole("option", { name: example.name })).toBeInTheDocument();
    await fireEvent.change(screen.getByLabelText("Starting point"), {
      target: { value: "example-0" },
    });
    expect(screen.getByText(example.description)).toBeInTheDocument();
    expect(onselect).not.toHaveBeenCalled();
    await fireEvent.click(screen.getByRole("button", { name: BOT_BUILDER_COPY.COPY_GRAPH }));
    expect(onselect).toHaveBeenCalledWith(example.graph, example.name);
    expect(onselect.mock.calls[0][0]).not.toBe(example.graph);
    expect(onselect.mock.calls[0][0].nodes).not.toBe(example.graph.nodes);
  });
});
