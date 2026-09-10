import type { CurrentUser } from "$lib/api/generated";

export const ACCOUNT_SESSION_STATUS = {
  RESTORING: "restoring",
  AUTHENTICATED: "authenticated",
  SIGNED_OUT: "signed-out",
  SIGNING_OUT: "signing-out",
  FAILURE: "failure",
} as const;

export const ACCOUNT_FAILURE = { RESTORE: "restore", SIGN_OUT: "sign-out" } as const;

export type AccountSessionState =
  | { status: typeof ACCOUNT_SESSION_STATUS.AUTHENTICATED; user: CurrentUser }
  | { status: typeof ACCOUNT_SESSION_STATUS.FAILURE; reason: (typeof ACCOUNT_FAILURE)[keyof typeof ACCOUNT_FAILURE] }
  | {
      status:
        | typeof ACCOUNT_SESSION_STATUS.RESTORING
        | typeof ACCOUNT_SESSION_STATUS.SIGNED_OUT
        | typeof ACCOUNT_SESSION_STATUS.SIGNING_OUT;
    };
