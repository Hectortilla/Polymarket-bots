import Ajv, { type AnySchemaObject, type ErrorObject, type ValidateFunction } from 'ajv';

import type { BotDefinitionDescriptor, SelectionMode } from '$lib/api/generated';

const ajv = new Ajv({ allErrors: true });
export const WIDGET_SCHEMA_KEY = 'x-widget';
ajv.addKeyword(WIDGET_SCHEMA_KEY);

export const SELECTION_MODE = {
  userConfigured: 'user_configured',
  botManaged: 'bot_managed',
  absent: 'absent'
} as const satisfies Record<string, SelectionMode>;

export const WIDGET_KIND = {
  decimal: 'decimal',
  marketSlugs: 'market_slugs',
  walletAddresses: 'wallet_addresses',
  streamRules: 'stream_rules'
} as const;

export type WidgetKind = (typeof WIDGET_KIND)[keyof typeof WIDGET_KIND];
export type LaunchInputs = Record<string, unknown>;

export function launchFields(
  descriptor: BotDefinitionDescriptor
): Array<[string, AnySchemaObject]> {
  const schema = descriptor.input_schema as AnySchemaObject;
  const properties = objectValue(schema.properties);

  return Object.entries(properties).filter(([, value]) => {
    const field = value as AnySchemaObject;
    return selectorIsEditable(descriptor, widgetKind(field));
  }) as Array<[string, AnySchemaObject]>;
}

export function resolvedFieldSchema(
  descriptor: BotDefinitionDescriptor,
  field: AnySchemaObject
): AnySchemaObject {
  const reference = field.$ref;
  if (typeof reference !== 'string' || !reference.startsWith('#/$defs/')) {
    return field;
  }

  const definitions = objectValue(
    (descriptor.input_schema as AnySchemaObject).$defs
  );
  const definition = definitions[reference.slice('#/$defs/'.length)];
  return { ...(definition as AnySchemaObject), ...field };
}

export function initialLaunchInputs(
  descriptor: BotDefinitionDescriptor
): LaunchInputs {
  return Object.fromEntries(
    launchFields(descriptor).map(([name, field]) => {
      const schema = resolvedFieldSchema(descriptor, field);
      if (field.default !== undefined) return [name, field.default];
      if (schema.default !== undefined) return [name, schema.default];
      if (schema.type === 'array') return [name, []];
      if (schema.type === 'boolean') return [name, false];
      return [name, ''];
    })
  );
}

export function launchValidator(
  descriptor: BotDefinitionDescriptor
): ValidateFunction<LaunchInputs> {
  const schema = descriptor.input_schema as AnySchemaObject;
  const fields = launchFields(descriptor);
  const fieldNames = new Set(fields.map(([name]) => name));
  const required = Array.isArray(schema.required)
    ? schema.required.filter((name): name is string =>
        typeof name === 'string' && fieldNames.has(name)
      )
    : [];

  return ajv.compile<LaunchInputs>({
    ...schema,
    properties: Object.fromEntries(fields),
    required
  });
}

export function validationMessages(
  validator: ValidateFunction<LaunchInputs>,
  inputs: LaunchInputs
): string[] {
  return validator(inputs) ? [] : (validator.errors ?? []).map(errorMessage);
}

export function widgetKind(field: AnySchemaObject): WidgetKind | undefined {
  const value = field[WIDGET_SCHEMA_KEY];
  return Object.values(WIDGET_KIND).find((kind) => kind === value);
}

export function fieldLabel(name: string, field: AnySchemaObject): string {
  return typeof field.title === 'string'
    ? field.title
    : name.replaceAll('_', ' ').replace(/^./, (letter) => letter.toUpperCase());
}

export function selectionExplanation(
  subject: 'Market' | 'Wallet',
  mode: SelectionMode
): string {
  if (userConfiguresSelection(mode)) {
    return `${subject} selection is configured below.`;
  }
  if (mode === SELECTION_MODE.botManaged) {
    return `${subject} selection is managed by this bot.`;
  }
  return `${subject} selection is not used by this bot.`;
}

function selectorIsEditable(
  descriptor: BotDefinitionDescriptor,
  widget: WidgetKind | undefined
): boolean {
  if (widget === WIDGET_KIND.marketSlugs) {
    return userConfiguresSelection(descriptor.market_selection);
  }
  if (widget === WIDGET_KIND.walletAddresses) {
    return userConfiguresSelection(descriptor.wallet_selection);
  }
  if (widget === WIDGET_KIND.streamRules) {
    return (
      userConfiguresSelection(descriptor.market_selection) ||
      userConfiguresSelection(descriptor.wallet_selection)
    );
  }
  return true;
}

function userConfiguresSelection(mode: SelectionMode): boolean {
  return mode === SELECTION_MODE.userConfigured;
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function errorMessage(error: ErrorObject): string {
  const field = error.instancePath.replace('/', '').replaceAll('/', ' → ');
  return `${field || 'Form'} ${error.message ?? 'is invalid'}`;
}
