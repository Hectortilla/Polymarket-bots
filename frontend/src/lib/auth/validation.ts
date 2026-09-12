import { isRecord, isUuid } from "$lib/valueGuards";
import type { CurrentUser, LogoutResponse } from "$lib/api/generated";

const CURRENT_USER_RESPONSE_KEYS = ["id", "email"] as const satisfies readonly (keyof CurrentUser)[];
const LOGOUT_RESPONSE_KEYS = ["logged_out"] as const satisfies readonly (keyof LogoutResponse)[];

export function isCurrentUser(value: unknown): value is CurrentUser {
  return (
    isRecord(value) &&
    Object.keys(value).length === CURRENT_USER_RESPONSE_KEYS.length &&
    isUuid(value.id) &&
    typeof value.email === "string" &&
    value.email.includes("@")
  );
}

export function isLogoutResponse(value: unknown): value is LogoutResponse {
  return isRecord(value) && Object.keys(value).length === LOGOUT_RESPONSE_KEYS.length && value.logged_out === true;
}

export function passwordsMatch(password: string, confirmation: string): boolean {
  return password === confirmation;
}
