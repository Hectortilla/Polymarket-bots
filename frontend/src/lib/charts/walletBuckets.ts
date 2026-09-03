import Decimal from 'decimal.js';

import runtimeContract from '$lib/runtimeContract.fixture.json';

// This browser implementation is contract-driven and locked to the canonical
// Python semantics by contracts/dashboard-wallet-bucket-parity.json.
export function walletBucketIndex(
  timestampMs: number,
  startMs: number,
  endMs: number,
  columns: number
): number {
  const scaled = (timestampMs - startMs) * columns / (endMs - startMs);
  const bucket = roundBucket(scaled);
  return runtimeContract.dashboard.walletBucketPolicy.clampToLastColumn
    ? Math.min(columns - 1, bucket)
    : bucket;
}

export function walletNotionalTier(
  notional: Decimal,
  maximumNotional: Decimal
): number {
  if (maximumNotional.lte(
    runtimeContract.dashboard.nonpositiveMaxNotionalThreshold
  )) return runtimeContract.dashboard.firstWalletNotionalTier;
  const weightedNotional = notional.times(
    runtimeContract.dashboard.walletNotionalTierDenominator
  );
  const boundaryIndex =
    runtimeContract.dashboard.walletNotionalTierUpperNumerators.findIndex(
      (upperNumerator) => {
        const boundary = maximumNotional.times(upperNumerator);
        return runtimeContract.dashboard.walletNotionalTierUpperBoundInclusive
          ? weightedNotional.lte(boundary)
          : weightedNotional.lt(boundary);
      }
    );
  return boundaryIndex < 0
    ? runtimeContract.dashboard.walletNotionalTierCount
    : boundaryIndex + runtimeContract.dashboard.firstWalletNotionalTier;
}

function roundBucket(value: number): number {
  switch (runtimeContract.dashboard.walletBucketPolicy.rounding) {
    case runtimeContract.dashboard.walletBucketRounding.FLOOR:
      return Math.floor(value);
  }
  throw new Error('Unsupported wallet bucket rounding policy');
}
