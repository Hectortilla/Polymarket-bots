import {
  requestPasswordReset, completePasswordReset,
  requestEmailVerification, completeEmailVerification,
} from '$lib/api/generated';
import { ACCOUNT_COPY } from './copy';

export type AccountLinkFlow = {
  request: typeof requestPasswordReset;
  complete: typeof completePasswordReset;
  requestLabel: string;
  completeLabel: string;
};

export const PASSWORD_RESET_FLOW: AccountLinkFlow = {
  request: requestPasswordReset,
  complete: completePasswordReset,
  requestLabel: ACCOUNT_COPY.SEND_RESET,
  completeLabel: ACCOUNT_COPY.COMPLETE_RESET,
};

export const EMAIL_VERIFICATION_FLOW: AccountLinkFlow = {
  request: requestEmailVerification,
  complete: completeEmailVerification,
  requestLabel: ACCOUNT_COPY.SEND_VERIFICATION,
  completeLabel: ACCOUNT_COPY.COMPLETE_VERIFICATION,
};
