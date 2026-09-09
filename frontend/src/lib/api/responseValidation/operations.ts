import { isAccountAction, isAccountStatus } from '$lib/auth/recovery/validation';
import { CONTENT_TYPE_HEADER, JSON_CONTENT_TYPE } from '$lib/api/http';
import { isAccountUsage } from '$lib/limits/validation';
import { isCurrentUser, isLogoutResponse } from '$lib/auth/validation';
import { isArrayOf } from '$lib/valueGuards';

import runtimeContract from '$lib/runtimeContract.fixture.json';

import { isRecord } from '$lib/valueGuards';

import { isGraphPreviewResponse } from '$lib/api/responseValidation/graph';

import {
  isBot,
  isDefinition,
  isGraphRevision,
  isGraphTemplate,
  isHealthResponse,
  isMarketSearchResults,
  isMarketSuggestion,
  isRun,
} from '$lib/api/responseValidation/resources';

import { isEventPage } from '$lib/api/responseValidation/events';

export async function validateOperationResponse(
  response: Response,
  _request: Request,
  options: {
    url: string;
    method?: string;
    path?: Record<string, unknown>;
  },
): Promise<Response> {
  if (!response.ok || options.url === runtimeContract.apiPaths.runEventsStream) {
    return response;
  }
  const contentType = response.headers.get(CONTENT_TYPE_HEADER) ?? '';
  if (!contentType.toLowerCase().includes(JSON_CONTENT_TYPE)) {
    throw new Error(`Control-plane response must use ${JSON_CONTENT_TYPE}`);
  }
  const body = await response.clone().text();
  if (!body) throw new Error('Control-plane response body must not be empty');
  const data: unknown = JSON.parse(body);
  if (!isExpectedOperationResponse(options.url, options.method, options.path, data)) {
    throw new Error('Control-plane response failed operation validation');
  }
  return response;
}

function isExpectedOperationResponse(
  url: string,
  method: string | undefined,
  path: Record<string, unknown> | undefined,
  data: unknown,
): boolean {
  const paths = runtimeContract.apiPaths;
  if (url === paths.accountStatus) return isAccountStatus(data);
  if ([paths.requestPasswordReset, paths.completePasswordReset, paths.requestEmailVerification, paths.completeEmailVerification, paths.changePassword, paths.revokeSessions].includes(url)) return isAccountAction(data);
  if (url === paths.usage) return isAccountUsage(data);
  if (url === paths.logout) return isLogoutResponse(data);
  if ([paths.currentUser, paths.login, paths.register].includes(url)) return isCurrentUser(data);
  if (url === paths.graphPreview) return isRecord(data) && isGraphPreviewResponse(data);
  if (url === paths.marketSearch) return isRecord(data) && isMarketSearchResults(data);
  if (url === paths.marketLookup) return isArrayOf(data, isMarketSuggestion);
  if (url === paths.botDefinitions) return isArrayOf(data, isDefinition);
  if (url === paths.bots) {
    return method === 'GET' ? isArrayOf(data, isBot) : isRecord(data) && isBot(data);
  }
  if (url === paths.botGraphRevisions) return isRecord(data) && isBot(data);
  if (url === paths.botGraphRevision) {
    return isRecord(data) && isGraphRevision(data);
  }
  if (url === paths.bot) return isRecord(data) && isBot(data);
  if (url === paths.botRuns) return isRecord(data) && isRun(data);
  if (url === paths.graphTemplates) {
    return method === 'GET'
      ? isArrayOf(data, isGraphTemplate)
      : isRecord(data) && isGraphTemplate(data);
  }
  if (url === paths.graphTemplate) {
    return isRecord(data) && isGraphTemplate(data);
  }
  if (url === paths.health) return isRecord(data) && isHealthResponse(data);
  if (url === paths.runs) return isArrayOf(data, isRun);
  if (url === paths.run || url === paths.runStop) {
    return isRecord(data) && isRun(data);
  }
  if (url === paths.runEvents) {
    const runId = path?.run_id;
    return typeof runId === 'string' && isRecord(data) && isEventPage(data, runId);
  }
  return false;
}
