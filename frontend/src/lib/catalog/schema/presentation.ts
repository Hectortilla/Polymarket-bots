import type { AnySchemaObject } from "ajv";
import type { SelectionMode } from "$lib/api/generated";
import { SELECTION_MODE, WIDGET_KIND } from "./contracts";
import { userConfiguresSelection, widgetKind } from "./fields";

export function isWideLaunchField(field: AnySchemaObject): boolean {
  const widget = widgetKind(field);
  return widget === WIDGET_KIND.STREAM_RULES || widget === WIDGET_KIND.MARKET_SLUGS;
}

export function fieldLabel(name: string, field: AnySchemaObject): string {
  return typeof field.title === "string"
    ? field.title
    : name.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

export function selectionExplanation(subject: "Market" | "Wallet", mode: SelectionMode): string {
  if (userConfiguresSelection(mode)) {
    return `${subject} selection is configured below.`;
  }
  if (mode === SELECTION_MODE.BOT_MANAGED) {
    return `${subject} selection is managed by this bot.`;
  }
  return `${subject} selection is not used by this bot.`;
}
