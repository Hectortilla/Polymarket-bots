import type { AccountUsage } from "$lib/api/generated";
import runtimeContract from "$lib/runtimeContract.fixture.json";
import { isRecord } from "$lib/valueGuards";

const USAGE_COUNT_FIELDS = [
  "active_runs",
  "queued_runs",
  "saved_bots",
  "retained_runs",
] as const satisfies readonly (keyof AccountUsage)[];

export function isAccountUsage(value: unknown): value is AccountUsage {
  if (!isRecord(value) || !isRecord(value.policy)) return false;
  const policy = value.policy;
  return (
    Object.keys(runtimeContract.resourcePolicy).every(
      (key) => Number.isSafeInteger(policy[key]) && (policy[key] as number) > 0,
    ) && USAGE_COUNT_FIELDS.every((key) => Number.isSafeInteger(value[key]) && (value[key] as number) >= 0)
  );
}

export function resourceLimitDetail(error: unknown): string | undefined {
  if (!isRecord(error)) return undefined;
  if (!Object.values(runtimeContract.resourceLimitCodes).includes(error.code as string)) return undefined;
  return typeof error.detail === "string" && error.detail.trim() ? error.detail.trim() : undefined;
}
