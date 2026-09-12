import { isWalletSuggestion, isWalletSearchResults } from "./wallets";
import { isAccountAction, isAccountStatus } from "$lib/auth/recovery/validation";
import { isCurrentUser, isLogoutResponse } from "$lib/auth/validation";
import { client } from "$lib/api/generated/client.gen";

import { isAccountUsage } from "$lib/limits/validation";
import { isRecord } from "$lib/valueGuards";

import { validateOperationResponse } from "$lib/api/responseValidation/operations";

import { isBot } from "./bots";
import { isDefinition } from "./catalog";
import { isHealthResponse } from "./health";
import { isMarketSearchResults } from "./markets";
import { isMarketSuggestion } from "./markets";
import { isRun } from "./runs";

import { isEventPage, isRunEvent } from "$lib/api/responseValidation/events";

import { isGraphPreviewResponse } from "$lib/api/responseValidation/graph";

let responseInterceptorConfigured = false;

export function configureApiResponseValidation(): void {
  if (!responseInterceptorConfigured) {
    client.interceptors.response.use(validateOperationResponse);
    responseInterceptorConfigured = true;
  }
  client.setConfig({ responseValidator: validateControlPlaneResponse });
}

export async function validateControlPlaneResponse(data: unknown): Promise<void> {
  const valid = Array.isArray(data) ? data.every(isListItem) : isRecord(data) && isObjectResponse(data);
  if (!valid) throw new Error("Control-plane response failed runtime validation");
}

function isListItem(value: unknown): boolean {
  return isRecord(value) && (isDefinition(value) || isBot(value) || isRun(value) || isMarketSuggestion(value) || isWalletSuggestion(value));
}

function isObjectResponse(value: Record<string, unknown>): boolean {
  return (
    isAccountAction(value) ||
    isAccountStatus(value) ||
    isAccountUsage(value) ||
    isCurrentUser(value) ||
    isLogoutResponse(value) ||
    isDefinition(value) ||
    isRun(value) ||
    isBot(value) ||
    isEventPage(value) ||
    isRunEvent(value) ||
    isHealthResponse(value) ||
    isMarketSearchResults(value) ||
    isWalletSearchResults(value) ||
    isGraphPreviewResponse(value)
  );
}
