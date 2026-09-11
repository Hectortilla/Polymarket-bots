import type { BotDefinitionLabel, SelectionMode } from "$lib/api/generated";
import catalogContract from "../catalogContract.fixture.json";

export const WIDGET_SCHEMA_KEY = catalogContract.widgetSchemaKey;

type SelectionModeContract = {
  [Key in keyof typeof catalogContract.selectionMode]: SelectionMode;
};

type BotDefinitionLabelContract = {
  [Key in keyof typeof catalogContract.botDefinitionLabel]: BotDefinitionLabel;
};

export const SELECTION_MODE = catalogContract.selectionMode as SelectionModeContract;

export const BOT_DEFINITION_LABEL = catalogContract.botDefinitionLabel as BotDefinitionLabelContract;

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
