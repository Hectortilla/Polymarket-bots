import { hasOnlyResponseFields } from "$lib/api/responseValidation/fields";
import { isUuid, isNonemptyString, isFiniteDateTime, isRecord } from "$lib/valueGuards";
import { isPaperConfig } from "./paperConfig";

export function isBot(value: Record<string, unknown>): boolean {
  return (
    hasOnlyResponseFields(value, "BotRead") &&
    isUuid(value.id) &&
    isNonemptyString(value.definition_id) &&
    isFiniteDateTime(value.created_at) &&
    isFiniteDateTime(value.updated_at) &&
    isRecord(value.config) &&
    isPaperConfig(value.config)
  );
}
