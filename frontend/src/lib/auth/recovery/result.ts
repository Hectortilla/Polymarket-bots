import { HTTP_STATUS } from '$lib/api/http';
import { AUTH_COPY } from '../copy';
import { ACCOUNT_COPY } from './copy';

export function accountActionError(status: number | undefined, rejectionMessage: string = ACCOUNT_COPY.REAUTH_FAILED): string {
  if (status === HTTP_STATUS.TOO_MANY_REQUESTS) return AUTH_COPY.RATE_LIMIT_ERROR;
  if (status === undefined || status >= HTTP_STATUS.INTERNAL_SERVER_ERROR) return AUTH_COPY.SERVICE_ERROR;
  return rejectionMessage;
}
