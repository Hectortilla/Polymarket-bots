import { currentUser, logout, type CurrentUser } from "$lib/api/generated";
import { HTTP_STATUS } from "$lib/api/http";

export const ACCOUNT_LOOKUP = { FOUND: "found", EXPIRED: "expired", UNAVAILABLE: "unavailable" } as const;

export type AccountLookup =
  | { status: typeof ACCOUNT_LOOKUP.FOUND; user: CurrentUser }
  | { status: typeof ACCOUNT_LOOKUP.EXPIRED }
  | { status: typeof ACCOUNT_LOOKUP.UNAVAILABLE };

export async function lookupCurrentAccount(): Promise<AccountLookup> {
  try {
    const result = await currentUser();
    if (result.data) return { status: ACCOUNT_LOOKUP.FOUND, user: result.data };
    return {
      status:
        result.response?.status === HTTP_STATUS.UNAUTHORIZED ? ACCOUNT_LOOKUP.EXPIRED : ACCOUNT_LOOKUP.UNAVAILABLE,
    };
  } catch {
    return { status: ACCOUNT_LOOKUP.UNAVAILABLE };
  }
}

export async function revokeCurrentSession(): Promise<boolean> {
  try {
    await logout({ throwOnError: true });
    return true;
  } catch {
    return false;
  }
}
