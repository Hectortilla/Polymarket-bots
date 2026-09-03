import Ajv, { type AnySchemaObject, type ErrorObject, type ValidateFunction } from 'ajv';

import type {
  BotDefinitionDescriptor,
  BotDefinitionLabel,
  PaperRunConfig,
  SelectionMode
} from '$lib/api/generated';
import {
  readableValidationMessage,
  requestValidationIssues
} from '$lib/api/requestErrors';
import catalogContract from './catalogContract.fixture.json';

const ajv = new Ajv({ allErrors: true });
const REQUEST_INPUTS_FIELD = 'inputs';
const OPENAPI_DISCRIMINATOR_KEY = 'discriminator';
const JSON_SCHEMA_DEFINITIONS_KEY = '$defs';
const JSON_SCHEMA_DEFINITION_REFERENCE_PREFIX = `#/${JSON_SCHEMA_DEFINITIONS_KEY}/`;
export const WIDGET_SCHEMA_KEY = catalogContract.widgetSchemaKey;
ajv.addKeyword(OPENAPI_DISCRIMINATOR_KEY);
ajv.addKeyword(WIDGET_SCHEMA_KEY);

type SelectionModeContract = {
  [Key in keyof typeof catalogContract.selectionMode]: SelectionMode;
};
type BotDefinitionLabelContract = {
  [Key in keyof typeof catalogContract.botDefinitionLabel]: BotDefinitionLabel;
};

export const SELECTION_MODE =
  catalogContract.selectionMode as SelectionModeContract;
export const BOT_DEFINITION_LABEL =
  catalogContract.botDefinitionLabel as BotDefinitionLabelContract;

export type WidgetKind = Lowercase<keyof typeof catalogContract.widgetKind>;

type WidgetKindContract = {
  [Key in keyof typeof catalogContract.widgetKind]: Lowercase<Key>;
};

export const WIDGET_KIND = catalogContract.widgetKind as WidgetKindContract;
export type LaunchInputs = Record<string, unknown>;
export type LaunchValidationIssue = {
  field?: string;
  message: string;
};
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
  if (typeof reference !== 'string' || !reference.startsWith(JSON_SCHEMA_DEFINITION_REFERENCE_PREFIX)) {
    return field;
  }

  const definitions = objectValue(
    (descriptor.input_schema as AnySchemaObject)[JSON_SCHEMA_DEFINITIONS_KEY]
  );
  const definition = definitions[reference.slice(JSON_SCHEMA_DEFINITION_REFERENCE_PREFIX.length)];
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

export function launchInputsFromConfig(
  descriptor: BotDefinitionDescriptor,
  config: PaperRunConfig
): LaunchInputs {
  return Object.fromEntries(
    launchFields(descriptor).map(([name, field]) => {
      const widget = widgetKind(field);
      if (widget === WIDGET_KIND.MARKET_SLUGS) {
        return [name, config.stream_rules.flatMap((rule) => rule.market_slugs ?? [])];
      }
      if (widget === WIDGET_KIND.WALLET_ADDRESSES) {
        return [name, config.stream_rules.flatMap((rule) => rule.wallet_addresses ?? [])];
      }
      return [name, config[name as keyof PaperRunConfig]];
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

export function launchValidationIssues(
  validator: ValidateFunction<LaunchInputs>,
  inputs: LaunchInputs
): LaunchValidationIssue[] {
  if (validator(inputs)) return [];

  const uniqueIssues = new Map<string, LaunchValidationIssue>();
  for (const error of validator.errors ?? []) {
    const issue = launchValidationIssue(error);
    uniqueIssues.set(`${issue.field ?? ''}:${issue.message}`, issue);
  }
  return [...uniqueIssues.values()];
}

export function launchRequestValidationIssues(
  error: unknown
): LaunchValidationIssue[] {
  return requestValidationIssues(error).map((issue) => ({
    field: requestInputField(issue.loc),
    message: readableValidationMessage(issue.msg)
  }));
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
  if (mode === SELECTION_MODE.BOT_MANAGED) {
    return `${subject} selection is managed by this bot.`;
  }
  return `${subject} selection is not used by this bot.`;
}

function selectorIsEditable(
  descriptor: BotDefinitionDescriptor,
  widget: WidgetKind | undefined
): boolean {
  if (widget === WIDGET_KIND.MARKET_SLUGS) {
    return userConfiguresSelection(descriptor.market_selection);
  }
  if (widget === WIDGET_KIND.WALLET_ADDRESSES) {
    return userConfiguresSelection(descriptor.wallet_selection);
  }
  if (widget === WIDGET_KIND.STREAM_RULES) {
    return (
      userConfiguresSelection(descriptor.market_selection) ||
      userConfiguresSelection(descriptor.wallet_selection)
    );
  }
  return true;
}

function userConfiguresSelection(mode: SelectionMode): boolean {
  return mode === SELECTION_MODE.USER_CONFIGURED;
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function launchValidationIssue(error: ErrorObject): LaunchValidationIssue {
  const path = error.instancePath
    .split('/')
    .filter(Boolean)
    .map(decodeJsonPointerSegment);
  const missingProperty =
    error.keyword === 'required' &&
    typeof error.params.missingProperty === 'string'
      ? error.params.missingProperty
      : undefined;
  return {
    field: path[0] ?? missingProperty,
    message: ajvIssueMessage(error)
  };
}

function requestInputField(
  location: Array<string | number>
): string | undefined {
  const inputsIndex = location.lastIndexOf(REQUEST_INPUTS_FIELD);
  if (inputsIndex < 0) return undefined;
  const field = location[inputsIndex + 1];
  return typeof field === 'string' ? field : undefined;
}

function ajvIssueMessage(error: ErrorObject): string {
  const limit = error.params.limit;
  switch (error.keyword) {
    case 'required': {
      const field = error.params.missingProperty;
      return typeof field === 'string'
        ? `${fieldLabel(field, {})} is required.`
        : 'This field is required.';
    }
    case 'minLength':
      return typeof limit === 'number'
        ? `Enter at least ${limit} ${limit === 1 ? 'character' : 'characters'}.`
        : 'Enter a longer value.';
    case 'maxLength':
      return typeof limit === 'number'
        ? `Enter no more than ${limit} characters.`
        : 'Enter a shorter value.';
    case 'minItems':
      return typeof limit === 'number'
        ? `Add at least ${limit} ${limit === 1 ? 'item' : 'items'}.`
        : 'Add another item.';
    case 'minimum':
      return typeof limit === 'number'
        ? `Enter ${limit} or more.`
        : 'Enter a larger value.';
    case 'maximum':
      return typeof limit === 'number'
        ? `Enter ${limit} or less.`
        : 'Enter a smaller value.';
    case 'type':
      return typeof error.params.type === 'string'
        ? `Enter a valid ${friendlyJsonType(error.params.type)}.`
        : 'Enter a valid value.';
    default:
      return readableValidationMessage(error.message ?? 'This value is invalid');
  }
}

function friendlyJsonType(type: string): string {
  if (type === 'array') return 'list';
  if (type === 'integer' || type === 'number') return 'number';
  return type;
}

function decodeJsonPointerSegment(segment: string): string {
  return segment.replaceAll('~1', '/').replaceAll('~0', '~');
}
