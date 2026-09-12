import type { AnySchemaObject, ValidateFunction } from "ajv";
import type { BotDefinitionDescriptor, PaperRunConfig } from "$lib/api/generated";
import { WIDGET_KIND, type LaunchInputs, type WidgetKind } from "./contracts";
import { launchSchemaEngine } from "./engine";
import { userConfiguresSelection, widgetKind } from "./fields";

const JSON_SCHEMA_DEFINITIONS_KEY = "$defs";
const JSON_SCHEMA_DEFINITION_REFERENCE_PREFIX = `#/${JSON_SCHEMA_DEFINITIONS_KEY}/`;

export class LaunchFormSchema {
  constructor(readonly descriptor: BotDefinitionDescriptor) {}

  fields(): Array<[string, AnySchemaObject]> {
    const properties = objectValue((this.descriptor.input_schema as AnySchemaObject).properties);
    return Object.entries(properties).filter(([, value]) =>
      this.selectorIsEditable(widgetKind(value as AnySchemaObject)),
    ) as Array<[string, AnySchemaObject]>;
  }

  resolveFieldSchema(field: AnySchemaObject): AnySchemaObject {
    const reference = field.$ref;
    if (typeof reference !== "string" || !reference.startsWith(JSON_SCHEMA_DEFINITION_REFERENCE_PREFIX)) return field;
    const definitions = objectValue((this.descriptor.input_schema as AnySchemaObject)[JSON_SCHEMA_DEFINITIONS_KEY]);
    const definition = definitions[reference.slice(JSON_SCHEMA_DEFINITION_REFERENCE_PREFIX.length)];
    return { ...(definition as AnySchemaObject), ...field };
  }

  initialInputs(): LaunchInputs {
    return Object.fromEntries(
      this.fields().map(([name, field]) => {
        const schema = this.resolveFieldSchema(field);
        if (field.default !== undefined) return [name, field.default];
        if (schema.default !== undefined) return [name, schema.default];
        if (schema.type === "array") return [name, []];
        if (schema.type === "boolean") return [name, false];
        return [name, ""];
      }),
    );
  }

  inputsFromConfig(config: PaperRunConfig): LaunchInputs {
    return Object.fromEntries(
      this.fields().map(([name, field]) => {
        const widget = widgetKind(field);
        if (widget === WIDGET_KIND.MARKET_SLUGS)
          return [name, [...new Set(config.stream_rules.flatMap((rule) => rule.market_slugs ?? []))]];
        if (widget === WIDGET_KIND.WALLET_ADDRESSES)
          return [name, [...new Set(config.stream_rules.flatMap((rule) => rule.wallet_addresses ?? []))]];
        return [name, config[name as keyof PaperRunConfig]];
      }),
    );
  }

  isRequired(name: string): boolean {
    return this.requiredFieldNames().includes(name);
  }

  validator(): ValidateFunction<LaunchInputs> {
    const schema = this.descriptor.input_schema as AnySchemaObject;
    return launchSchemaEngine.compile<LaunchInputs>({
      ...schema,
      properties: Object.fromEntries(this.fields()),
      required: this.requiredFieldNames(),
    });
  }

  private requiredFieldNames(): string[] {
    const required = this.descriptor.input_schema.required;
    const editableNames = new Set(this.fields().map(([name]) => name));
    return Array.isArray(required)
      ? required.filter((name): name is string => typeof name === "string" && editableNames.has(name))
      : [];
  }

  private selectorIsEditable(widget: WidgetKind | undefined): boolean {
    if (widget === WIDGET_KIND.MARKET_SLUGS) return userConfiguresSelection(this.descriptor.market_selection);
    if (widget === WIDGET_KIND.WALLET_ADDRESSES) return userConfiguresSelection(this.descriptor.wallet_selection);
    if (widget === WIDGET_KIND.STREAM_RULES)
      return (
        userConfiguresSelection(this.descriptor.market_selection) ||
        userConfiguresSelection(this.descriptor.wallet_selection)
      );
    return true;
  }
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}
