import runtimeContract from '$lib/runtimeContract.fixture.json';

import { isInteger, isNonemptyString, isOneOf } from '$lib/valueGuards';
import { isPositiveDecimal } from '$lib/decimalGuards';

import { INITIAL_RUN_STATUS, isRunStatus } from '$lib/runs/status';

const ACTIVITY_SEVERITIES = Object.values(runtimeContract.activitySeverity);

const BOOTSTRAP_PHASES = Object.values(runtimeContract.bootstrapPhase);

export function isLifecyclePayload(payload: Record<string, unknown>): boolean {
  const hasStartedFields =
    payload.name !== undefined ||
    payload.mode !== undefined ||
    payload.initial_cash_usdc !== undefined;
  if (!hasStartedFields) return isRunStatus(payload.status);
  return (
    (payload.status === undefined || payload.status === INITIAL_RUN_STATUS) &&
    isNonemptyString(payload.name) &&
    isOneOf(payload.mode, Object.values(runtimeContract.botMode)) &&
    isPositiveDecimal(payload.initial_cash_usdc)
  );
}

export function isBootstrapPayload(payload: Record<string, unknown>): boolean {
  if (
    !isOneOf(payload.phase, BOOTSTRAP_PHASES) ||
    !isInteger(payload.completed) ||
    !isInteger(payload.total)
  )
    return false;
  const policy = runtimeContract.bootstrapProgress;
  return (
    payload.completed >= policy.minimum &&
    payload.total >= policy.minimum &&
    (policy.completedMayExceedTotal || payload.completed <= payload.total)
  );
}

export function isActivityPayload(payload: Record<string, unknown>): boolean {
  return isNonemptyString(payload.message) && isOneOf(payload.severity, ACTIVITY_SEVERITIES);
}
