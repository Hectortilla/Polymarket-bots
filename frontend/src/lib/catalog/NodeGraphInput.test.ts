import { GRAPH_SCALAR_TYPE } from './graphContracts';
import { GRAPH_FIELD_COPY } from '$lib/catalog/copy';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { NodeGraph } from '$lib/api/generated';
import NodeGraphInput from './NodeGraphInput.svelte';
import { ADD_NODE_LABEL } from './NodePalette.svelte';
import { GRAPH_NODE_TYPE } from './graphContracts';
import parityContract from './graphValidationContract.fixture.json';
import {
  BUY_ACTION,
  EQUAL_COMPARISON,
  NUMBER_CONSTANT,
  ON_BOOK_TRIGGER,
  TEST_GRAPH,
  TEST_GRAPH_CATALOG,
  THRESHOLD_BUY_GRAPH,
} from './nodeGraphTestFixtures';

class FlowResizeObserver implements ResizeObserver {
  constructor(private readonly callback: ResizeObserverCallback) {}

  observe(target: Element): void {
    this.callback(
      [
        {
          target,
          contentRect: { width: 100, height: 50 },
        } as ResizeObserverEntry,
      ],
      this,
    );
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
    stubFlowBrowserApis();
    const onchange = vi.fn<(graph: NodeGraph) => void>();
    const view = render(NodeGraphInput, {
      initialGraph: TEST_GRAPH,
      graphCatalog: TEST_GRAPH_CATALOG,
      onchange,
      labelledby: 'editor-label',
    });

    for (const name of [NUMBER_CONSTANT.display_name, 'Comparison', BUY_ACTION.display_name]) {
      await fireEvent.click(screen.getByRole('button', { name: ADD_NODE_LABEL }));
      await fireEvent.input(screen.getByRole('searchbox'), { target: { value: name } });
      await fireEvent.click(screen.getByRole('button', { name: `Add ${name}` }));
    }
    await waitFor(() => {
      expect(onchange).toHaveBeenLastCalledWith(
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              data: { hook_name: ON_BOOK_TRIGGER.hook_name },
            }),
            expect.objectContaining({
              data: {
                scalar_type: NUMBER_CONSTANT.scalar_type,
                value: NUMBER_CONSTANT.default_value,
              },
            }),
            expect.objectContaining({
              data: { operator: EQUAL_COMPARISON.operator },
            }),
            expect.objectContaining({ data: { action: BUY_ACTION.action } }),
          ]),
        }),
      );
    });

    const emittedGraph = onchange.mock.calls.at(-1)?.[0];
    if (!emittedGraph) throw new Error('editor did not emit its constructed graph');
    const constantNode = emittedGraph.nodes.find((node) => node.type === GRAPH_NODE_TYPE.constant);
    const comparisonNode = emittedGraph.nodes.find(
      (node) => node.type === GRAPH_NODE_TYPE.comparison,
    );
    if (!constantNode || !comparisonNode) {
      throw new Error('editor did not construct connectable nodes');
    }
    const sourceHandle = document.querySelector<HTMLElement>(
      `[data-nodeid="${constantNode.id}"]` +
        `[data-handleid="${NUMBER_CONSTANT.output.handle_id}"]`,
    );
    const targetHandle = document.querySelector<HTMLElement>(
      `[data-nodeid="${comparisonNode.id}"]` +
        `[data-handleid="${EQUAL_COMPARISON.inputs[0].handle_id}"]`,
    );
    if (!sourceHandle || !targetHandle) {
      throw new Error('editor did not render connectable handles');
    }
    Object.defineProperty(document, 'elementFromPoint', {
      configurable: true,
      value: () => targetHandle,
    });
    await fireEvent.mouseDown(sourceHandle, {
      button: 0,
      buttons: 1,
      clientX: 10,
      clientY: 10,
    });
    await fireEvent.mouseMove(document, {
      buttons: 1,
      clientX: 20,
      clientY: 20,
    });
    await fireEvent.mouseUp(document, {
      button: 0,
      buttons: 0,
      clientX: 20,
      clientY: 20,
    });
    await waitFor(() => {
      expect(onchange).toHaveBeenLastCalledWith(
        expect.objectContaining({
          edges: [
            expect.objectContaining({
              source: constantNode.id,
              source_handle: NUMBER_CONSTANT.output.handle_id,
              target: comparisonNode.id,
              target_handle: EQUAL_COMPARISON.inputs[0].handle_id,
            }),
          ],
        }),
      );
    });

    const connectedGraph = onchange.mock.calls.at(-1)?.[0];
    if (!connectedGraph) throw new Error('editor did not emit its connected graph');
    view.unmount();
    render(NodeGraphInput, {
      initialGraph: connectedGraph,
      graphCatalog: TEST_GRAPH_CATALOG,
      onchange: vi.fn(),
      labelledby: 'editor-label',
    });
    expect(screen.getByLabelText(`${BUY_ACTION.display_name} broker action node`)).toBeTruthy();
    expect(screen.getByLabelText(`${EQUAL_COMPARISON.display_name} comparison node`)).toBeTruthy();
    expect(document.querySelector('.graph-summary')?.textContent).toContain('1 connection');
  });

  it('creates and reopens every MVP operation through the actual editor', async () => {
    stubFlowBrowserApis();
    const onchange = vi.fn<(graph: NodeGraph) => void>();
    const view = render(NodeGraphInput, {
      initialGraph: TEST_GRAPH,
      graphCatalog: TEST_GRAPH_CATALOG,
      onchange,
      labelledby: 'editor',
    });
    for (const operation of TEST_GRAPH_CATALOG.operations ?? []) {
      await fireEvent.click(screen.getByRole('button', { name: ADD_NODE_LABEL }));
      await fireEvent.input(screen.getByRole('searchbox'), {
        target: { value: operation.display_name },
      });
      await fireEvent.click(screen.getByRole('button', { name: `Add ${operation.display_name}` }));
      expect(
        screen.getByLabelText(`${operation.display_name} node`, { selector: 'section' }),
      ).toBeTruthy();
    }
    const graph = onchange.mock.calls.at(-1)?.[0];
    if (!graph) throw new Error('Expected graph edit');
    view.unmount();
    render(NodeGraphInput, {
      initialGraph: graph,
      graphCatalog: TEST_GRAPH_CATALOG,
      labelledby: 'reopened',
    });
    for (const operation of TEST_GRAPH_CATALOG.operations ?? [])
      expect(
        screen.getByLabelText(`${operation.display_name} node`, { selector: 'section' }),
      ).toBeTruthy();
  });

  it('removes only an expandable input edge and explains incompatible parameter wiring', async () => {
    stubFlowBrowserApis();
    const graph = parityContract.cases.find(
      (item) => item.name === 'Multiple conditions and cooldown',
    )!.graph as NodeGraph;
    const onchange = vi.fn<(graph: NodeGraph) => void>();
    render(NodeGraphInput, {
      initialGraph: graph,
      graphCatalog: TEST_GRAPH_CATALOG,
      onchange,
      labelledby: 'editor',
    });
    await fireEvent.click(screen.getByRole('button', { name: 'Remove input_2' }));
    await waitFor(() => expect(onchange).toHaveBeenCalled());
    let edited = onchange.mock.calls.at(-1)![0];
    expect(edited.edges).toEqual(
      graph.edges!.filter(
        (edge) => !(edge.target === 'conditions' && edge.target_handle === 'input_2'),
      ),
    );
    const condition = edited.nodes.find((node) => node.id === 'conditions');
    expect(condition?.data).toMatchObject({ input_ids: ['input_1', 'input_3'] });
    await fireEvent.change(screen.getAllByLabelText(GRAPH_FIELD_COPY.PARAMETER_TYPE)[0], {
      target: { value: GRAPH_SCALAR_TYPE.boolean },
    });
    edited = onchange.mock.calls.at(-1)![0];
    expect(edited.parameters![0].data.scalar_type).toBe(GRAPH_SCALAR_TYPE.boolean);
    expect(edited.edges!.some((edge) => edge.source === 'entry')).toBe(false);
    expect(
      screen
        .getAllByRole('status')
        .some((element) => element.textContent?.includes('incompatible connection')),
    ).toBe(true);
  });

  it('collapses sections and operation groups while search reveals matches', async () => {
    stubFlowBrowserApis();
    render(NodeGraphInput, {
      initialGraph: TEST_GRAPH,
      graphCatalog: TEST_GRAPH_CATALOG,
      labelledby: 'editor',
    });
    await fireEvent.click(screen.getByRole('button', { name: ADD_NODE_LABEL }));
    const operations = screen.getByRole('button', { name: 'Operations' });
    const math = screen.getByRole('button', { name: 'Math' });
    expect(operations.getAttribute('aria-expanded')).toBe('true');
    expect(math.getAttribute('aria-expanded')).toBe('false');
    expect(screen.queryByRole('button', { name: 'Add Multiply' })).toBeNull();
    await fireEvent.click(math);
    expect(screen.getByRole('button', { name: 'Add Multiply' })).toBeTruthy();
    await fireEvent.click(operations);
    expect(screen.queryByRole('button', { name: 'Math' })).toBeNull();
    await fireEvent.input(screen.getByRole('searchbox'), { target: { value: 'Multiply' } });
    expect(screen.getByRole('button', { name: 'Add Multiply' })).toBeTruthy();
    await fireEvent.input(screen.getByRole('searchbox'), { target: { value: '' } });
    expect(operations.getAttribute('aria-expanded')).toBe('false');
    expect(screen.queryByRole('button', { name: 'Add Multiply' })).toBeNull();
    const values = screen.getByRole('button', { name: 'Values' });
    await fireEvent.click(values);
    expect(
      screen.getByRole('button', { name: `Add ${NUMBER_CONSTANT.display_name}` }),
    ).toBeTruthy();
  });

  it('renders the same graph as a strictly non-interactive snapshot', async () => {
    stubFlowBrowserApis();
    const onchange = vi.fn<(graph: NodeGraph) => void>();

    render(NodeGraphInput, {
      initialGraph: THRESHOLD_BUY_GRAPH,
      graphCatalog: TEST_GRAPH_CATALOG,
      onchange,
      labelledby: 'snapshot-label',
      readOnly: true,
    });

    expect(
      await screen.findByLabelText(`${BUY_ACTION.display_name} broker action node`),
    ).toBeTruthy();
    expect(onchange).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: ADD_NODE_LABEL })).toBeNull();
    expect(document.querySelector('[data-testid="svelte-flow__controls"]')).toBeNull();
    for (const input of screen.getAllByRole<HTMLInputElement>('textbox', {
      name: GRAPH_FIELD_COPY.VALUE,
    })) {
      expect(input.disabled).toBe(true);
    }
    expect(
      screen.getByRole<HTMLSelectElement>('combobox', {
        name: GRAPH_FIELD_COPY.COMPARISON_OPERATOR,
      }).disabled,
    ).toBe(true);
    expect(document.querySelector('.svelte-flow__node.draggable')).toBeNull();
    expect(document.querySelector('.svelte-flow__node.connectable')).toBeNull();
    expect(document.querySelector('.svelte-flow__node.selectable')).toBeNull();
    expect(document.querySelector('.svelte-flow__node[tabindex="0"]')).toBeNull();
    expect(screen.queryByRole('link', { name: 'Svelte Flow attribution' })).toBeNull();
  });
});

function stubFlowBrowserApis(): void {
  vi.stubGlobal('ResizeObserver', FlowResizeObserver);
  vi.stubGlobal(
    'DOMMatrixReadOnly',
    class {
      readonly m22 = 1;
    },
  );
  vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(100);
  vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(50);
}
