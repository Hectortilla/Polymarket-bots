import type { AnySchemaObject } from "ajv";
import type { BotDefinitionDescriptor, SelectionMode } from "$lib/api/generated";
import { SELECTION_MODE, WIDGET_KIND, WIDGET_SCHEMA_KEY, type WidgetKind } from "./contracts";

const JSON_SCHEMA_DEFINITIONS_KEY = "$defs";

const JSON_SCHEMA_DEFINITION_REFERENCE_PREFIX = `#/${JSON_SCHEMA_DEFINITIONS_KEY}/`;

export function launchFields(descriptor: BotDefinitionDescriptor): Array<[string, AnySchemaObject]> {
  const schema = descriptor.input_schema as AnySchemaObject;
  const properties = objectValue(schema.properties);

  return Object.entries(properties).filter(([, value]) => {
    const field = value as AnySchemaObject;
    return selectorIsEditable(descriptor, widgetKind(field));
  }) as Array<[string, AnySchemaObject]>;
}

export function resolvedFieldSchema(descriptor: BotDefinitionDescriptor, field: AnySchemaObject): AnySchemaObject {
  const reference = field.$ref;
  if (typeof reference !== "string" || !reference.startsWith(JSON_SCHEMA_DEFINITION_REFERENCE_PREFIX)) {
    return field;
  }

  const definitions = objectValue((descriptor.input_schema as AnySchemaObject)[JSON_SCHEMA_DEFINITIONS_KEY]);
  const definition = definitions[reference.slice(JSON_SCHEMA_DEFINITION_REFERENCE_PREFIX.length)];
  return { ...(definition as AnySchemaObject), ...field };
}

export function widgetKind(field: AnySchemaObject): WidgetKind | undefined {
  const value = field[WIDGET_SCHEMA_KEY];
  return Object.values(WIDGET_KIND).find((kind) => kind === value);
}

function selectorIsEditable(descriptor: BotDefinitionDescriptor, widget: WidgetKind | undefined): boolean {
  if (widget === WIDGET_KIND.MARKET_SLUGS) {
    return userConfiguresSelection(descriptor.market_selection);
  }
  if (widget === WIDGET_KIND.WALLET_ADDRESSES) {
    return userConfiguresSelection(descriptor.wallet_selection);
  }
  if (widget === WIDGET_KIND.STREAM_RULES) {
    return userConfiguresSelection(descriptor.market_selection) || userConfiguresSelection(descriptor.wallet_selection);
  }
  return true;
}

export function userConfiguresSelection(mode: SelectionMode): boolean {
  return mode === SELECTION_MODE.USER_CONFIGURED;
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}
