import { login, register, type CredentialsWritable } from "$lib/api/generated";
import { HTTP_STATUS } from "$lib/api/http";

export const ACCOUNT_ACTION = { LOGIN: "login", REGISTER: "register" } as const;
export const CREDENTIAL_OUTCOME = {
  AUTHENTICATED: "authenticated",
  REJECTED: "rejected",
  RATE_LIMITED: "rate-limited",
  UNAVAILABLE: "unavailable",
} as const;
export type AccountAction = (typeof ACCOUNT_ACTION)[keyof typeof ACCOUNT_ACTION];
export type CredentialOutcome = (typeof CREDENTIAL_OUTCOME)[keyof typeof CREDENTIAL_OUTCOME];

export async function submitCredentials(
  action: AccountAction,
  credentials: CredentialsWritable,
): Promise<CredentialOutcome> {
  try {
    const result = await (action === ACCOUNT_ACTION.REGISTER ? register : login)({ body: credentials });
    if (result.data) return CREDENTIAL_OUTCOME.AUTHENTICATED;
    if (result.response?.status === HTTP_STATUS.TOO_MANY_REQUESTS) return CREDENTIAL_OUTCOME.RATE_LIMITED;
    if (!result.response || result.response.status >= HTTP_STATUS.INTERNAL_SERVER_ERROR)
      return CREDENTIAL_OUTCOME.UNAVAILABLE;
    return CREDENTIAL_OUTCOME.REJECTED;
  } catch {
    return CREDENTIAL_OUTCOME.UNAVAILABLE;
  }
}
