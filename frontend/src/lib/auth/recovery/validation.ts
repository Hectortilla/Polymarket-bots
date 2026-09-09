import type { AccountActionResponse, AccountStatus } from '$lib/api/generated';
import { isRecord } from '$lib/valueGuards';

export function isAccountAction(value: unknown): value is AccountActionResponse {
  return isRecord(value) && Object.keys(value).length === 1 && value.accepted === true;
}

export function isAccountStatus(value: unknown): value is AccountStatus {
  return isRecord(value) && Object.keys(value).length === 2 && typeof value.email_verified === 'boolean' && typeof value.verification_required === 'boolean';
}

export function passwordsMatch(password: string, confirmation: string): boolean {
  return password === confirmation;
}
