import type { AnySchemaObject } from "ajv";
import type { SelectionMode } from "$lib/api/generated";
import { SELECTION_MODE, WIDGET_KIND, WIDGET_SCHEMA_KEY, type WidgetKind } from "./contracts";

export function widgetKind(field: AnySchemaObject): WidgetKind | undefined {
  const value = field[WIDGET_SCHEMA_KEY];
  return Object.values(WIDGET_KIND).find((kind) => kind === value);
}

export function userConfiguresSelection(mode: SelectionMode): boolean {
  return mode === SELECTION_MODE.USER_CONFIGURED;
}
