import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { NodeGraph } from '$lib/api/generated';
import NodeGraphInput from './NodeGraphInput.svelte';
import { ADD_NODE_LABEL } from './NodePalette.svelte';
import { GRAPH_NODE_TYPE } from './graphContracts';
import {
  BUY_ACTION,
  DECIMAL_CONSTANT,
  EQUAL_COMPARISON,
  ON_BOOK_TRIGGER,
  TEST_GRAPH,
  TEST_GRAPH_CATALOG
} from './nodeGraphTestFixtures';

class FlowResizeObserver implements ResizeObserver {
  constructor(private readonly callback: ResizeObserverCallback) {}

  observe(target: Element): void {
    this.callback([{
      target,
      contentRect: { width: 100, height: 50 }
    } as ResizeObserverEntry], this);
  }

  disconnect(): void {}
  unobserve(): void {}
}

afterEach(() => {
  cleanup();
  Reflect.deleteProperty(document, 'elementFromPoint');
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('node graph editor', () => {
  it('constructs real Flow nodes and remounts the emitted graph', async () => {
    vi.stubGlobal('ResizeObserver', FlowResizeObserver);
    vi.stubGlobal('DOMMatrixReadOnly', class {
      readonly m22 = 1;
    });
    vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(100);
    vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(50);
    const onchange = vi.fn<(graph: NodeGraph) => void>();
    const view = render(NodeGraphInput, {
      initialGraph: TEST_GRAPH,
      graphCatalog: TEST_GRAPH_CATALOG,
      onchange,
      labelledby: 'editor-label'
    });

    for (const name of [
      DECIMAL_CONSTANT.display_name,
      'Comparison',
      BUY_ACTION.display_name
    ]) {
      await fireEvent.click(screen.getByRole('button', { name: ADD_NODE_LABEL }));
      await fireEvent.click(screen.getByRole('button', { name: `Add ${name}` }));
    }
    await waitFor(() => {
      expect(onchange).toHaveBeenLastCalledWith(
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              data: { hook_name: ON_BOOK_TRIGGER.hook_name }
            }),
            expect.objectContaining({
              data: {
                scalar_type: DECIMAL_CONSTANT.scalar_type,
                value: DECIMAL_CONSTANT.default_value
              }
            }),
            expect.objectContaining({
              data: { operator: EQUAL_COMPARISON.operator }
            }),
            expect.objectContaining({ data: { action: BUY_ACTION.action } })
          ])
        })
      );
    });

    const emittedGraph = onchange.mock.calls.at(-1)?.[0];
    if (!emittedGraph) throw new Error('editor did not emit its constructed graph');
    const constantNode = emittedGraph.nodes.find(
      (node) => node.type === GRAPH_NODE_TYPE.constant
    );
    const comparisonNode = emittedGraph.nodes.find(
      (node) => node.type === GRAPH_NODE_TYPE.comparison
    );
    if (!constantNode || !comparisonNode) {
      throw new Error('editor did not construct connectable nodes');
    }
    const sourceHandle = document.querySelector<HTMLElement>(
      `[data-nodeid="${constantNode.id}"]`
      + `[data-handleid="${DECIMAL_CONSTANT.output.handle_id}"]`
    );
    const targetHandle = document.querySelector<HTMLElement>(
      `[data-nodeid="${comparisonNode.id}"]`
      + `[data-handleid="${EQUAL_COMPARISON.inputs[0].handle_id}"]`
    );
    if (!sourceHandle || !targetHandle) {
      throw new Error('editor did not render connectable handles');
    }
    Object.defineProperty(document, 'elementFromPoint', {
      configurable: true,
      value: () => targetHandle
    });
    await fireEvent.mouseDown(sourceHandle, {
      button: 0, buttons: 1, clientX: 10, clientY: 10
    });
    await fireEvent.mouseMove(document, {
      buttons: 1, clientX: 20, clientY: 20
    });
    await fireEvent.mouseUp(document, {
      button: 0, buttons: 0, clientX: 20, clientY: 20
    });
    await waitFor(() => {
      expect(onchange).toHaveBeenLastCalledWith(
        expect.objectContaining({
          edges: [expect.objectContaining({
            source: constantNode.id,
            source_handle: DECIMAL_CONSTANT.output.handle_id,
            target: comparisonNode.id,
            target_handle: EQUAL_COMPARISON.inputs[0].handle_id
          })]
        })
      );
    });

    const connectedGraph = onchange.mock.calls.at(-1)?.[0];
    if (!connectedGraph) throw new Error('editor did not emit its connected graph');
    view.unmount();
    render(NodeGraphInput, {
      initialGraph: connectedGraph,
      graphCatalog: TEST_GRAPH_CATALOG,
      onchange: vi.fn(),
      labelledby: 'editor-label'
    });
    expect(screen.getByLabelText(`${BUY_ACTION.display_name} broker action node`))
      .toBeTruthy();
    expect(screen.getByLabelText(
      `${EQUAL_COMPARISON.display_name} comparison node`
    )).toBeTruthy();
    expect(document.querySelector('.graph-summary')?.textContent)
      .toContain('1 connection');
  });
});
