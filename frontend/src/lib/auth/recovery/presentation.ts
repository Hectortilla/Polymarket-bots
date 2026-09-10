import type { AccountStatus, SessionRevocation } from "$lib/api/generated";
import runtimeContract from "$lib/runtimeContract.fixture.json";
import { ACCOUNT_COPY } from "./copy";

type RevocationContract = {
  [Key in keyof typeof runtimeContract.accountManagement.sessionRevocation]: Extract<SessionRevocation, Lowercase<Key>>;
};
export const SESSION_REVOCATION = runtimeContract.accountManagement.sessionRevocation as RevocationContract;

export function accountStatusMessage(status: AccountStatus): string {
  if (status.email_verified) return ACCOUNT_COPY.VERIFIED;
  if (status.verification_required) return ACCOUNT_COPY.VERIFICATION_REQUIRED;
  return ACCOUNT_COPY.LEGACY_ACCOUNT;
}
