import { hasOnlyResponseFields } from "$lib/api/responseValidation/fields";
import runtimeContract from "$lib/runtimeContract.fixture.json";
import { isUuid, isNonemptyString, isFiniteDateTime, isOneOf, isRecord, isOptionalNullable } from "$lib/valueGuards";
import { isDecimal } from "$lib/decimalGuards";
import { isPaperConfig } from "./paperConfig";

const RUN_STATUSES = Object.values(runtimeContract.runStatus.values);

const VALUATION_STATUSES = Object.values(runtimeContract.valuationStatus);

export function isRun(value: Record<string, unknown>): boolean {
  return (
    hasOnlyResponseFields(value, "RunRead") &&
    isUuid(value.id) &&
    isUuid(value.bot_id) &&
    (value.bot_deleted === undefined || typeof value.bot_deleted === "boolean") &&
    isNonemptyString(value.definition_id) &&
    isFiniteDateTime(value.created_at) &&
    isOneOf(value.status, RUN_STATUSES) &&
    isRecord(value.config) &&
    isPaperConfig(value.config) &&
    isOptionalNullable(value.started_at, isFiniteDateTime) &&
    isOptionalNullable(value.ended_at, isFiniteDateTime) &&
    isOptionalNullable(value.heartbeat_at, isFiniteDateTime) &&
    isOptionalNullable(value.failure_detail, (detail) => typeof detail === "string") &&
    isOptionalNullable(value.latest_runtime_failure, (detail) => typeof detail === "string") &&
    isOptionalNullable(value.latest_equity, isDecimal) &&
    (value.equity_status === null ||
      value.equity_status === undefined ||
      isOneOf(value.equity_status, VALUATION_STATUSES))
  );
}
