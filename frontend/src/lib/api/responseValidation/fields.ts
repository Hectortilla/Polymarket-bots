import type { PersistedDurableEvent, LiveRunEvent } from "$lib/api/generated";
import runtimeContract from "$lib/runtimeContract.fixture.json";

export function hasOnlyResponseFields(
  value: Record<string, unknown>,
  model: keyof typeof runtimeContract.strictResponseFields.models,
): boolean {
  const fields: readonly string[] = runtimeContract.strictResponseFields.models[model];
  return Object.keys(value).every((field) => fields.includes(field));
}

export function hasOnlyEventFields(
  value: Record<string, unknown>,
  ...[kind, delivery]:
    [NonNullable<PersistedDurableEvent["kind"]>, "durable"] | [NonNullable<LiveRunEvent["kind"]>, "live"]
): boolean {
  const models = runtimeContract.strictResponseFields[delivery] as Record<string, readonly string[]>;
  const fields = models[kind];
  return fields !== undefined && Object.keys(value).every((field) => fields.includes(field));
}
