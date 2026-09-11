import { AUTH_COPY } from "./copy";
import { CREDENTIAL_OUTCOME, type CredentialOutcome } from "./credentials";

export function credentialFailureMessage(outcome: CredentialOutcome, rejectionMessage: string): string | undefined {
  if (outcome === CREDENTIAL_OUTCOME.AUTHENTICATED) return undefined;
  if (outcome === CREDENTIAL_OUTCOME.RATE_LIMITED) return AUTH_COPY.RATE_LIMIT_ERROR;
  if (outcome === CREDENTIAL_OUTCOME.UNAVAILABLE) return AUTH_COPY.SERVICE_ERROR;
  return rejectionMessage;
}
