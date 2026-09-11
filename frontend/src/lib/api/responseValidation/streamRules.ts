import runtimeContract from "$lib/runtimeContract.fixture.json";
import { isRecord, isOneOf, isNonemptyString } from "$lib/valueGuards";
import { isWalletAddress } from "$lib/wallets";

const STREAM_RELATIONS = Object.values(runtimeContract.streamRelation);

export function isStreamRule(value: unknown): boolean {
  if (
    !isRecord(value) ||
    !isOneOf(value.relation, STREAM_RELATIONS) ||
    !isOptionalStringArray(value.market_slugs) ||
    !isOptionalWalletArray(value.wallet_addresses)
  )
    return false;
  const selectorGroupCount = Number(hasSelectors(value.market_slugs)) + Number(hasSelectors(value.wallet_addresses));
  const relation = value.relation as keyof typeof runtimeContract.streamRule.minimumSelectorGroups;
  return selectorGroupCount >= runtimeContract.streamRule.minimumSelectorGroups[relation];
}

function isOptionalStringArray(value: unknown): boolean {
  return value === undefined || (Array.isArray(value) && value.every(isNonemptyString));
}

function isOptionalWalletArray(value: unknown): boolean {
  return value === undefined || (Array.isArray(value) && value.every(isWalletAddress));
}

function hasSelectors(value: unknown): boolean {
  return Array.isArray(value) && value.length > 0;
}
