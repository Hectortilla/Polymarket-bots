import { isLaunchInputSchema } from "$lib/catalog/schema/validation";
import catalogContract from "$lib/catalog/catalogContract.fixture.json";
import { isNonemptyString, isOneOf, isRecord, isArrayOf } from "$lib/valueGuards";
import { isGraphCatalog, isNodeGraph } from "./graph";

const SELECTION_MODES = Object.values(catalogContract.selectionMode);

const DEFINITION_LABELS = Object.values(catalogContract.botDefinitionLabel);

export function isDefinition(value: Record<string, unknown>): boolean {
  return (
    isNonemptyString(value.definition_id) &&
    isNonemptyString(value.display_name) &&
    isNonemptyString(value.description) &&
    isOneOf(value.label, DEFINITION_LABELS) &&
    isRecord(value.input_schema) &&
    isLaunchInputSchema(value.input_schema) &&
    isOneOf(value.market_selection, SELECTION_MODES) &&
    isOneOf(value.wallet_selection, SELECTION_MODES) &&
    (value.graph_catalog === undefined || value.graph_catalog === null || isGraphCatalog(value.graph_catalog)) &&
    (value.graph_examples === undefined ||
      isArrayOf(
        value.graph_examples,
        (example) =>
          isNonemptyString(example.name) && isNonemptyString(example.description) && isNodeGraph(example.graph),
      )) &&
    (value.starter_graph === undefined || value.starter_graph === null || isNodeGraph(value.starter_graph))
  );
}
