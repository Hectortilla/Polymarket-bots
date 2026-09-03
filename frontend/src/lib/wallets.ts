import runtimeContract from '$lib/runtimeContract.fixture.json';

const WALLET_ADDRESS_PATTERN = new RegExp(runtimeContract.walletAddressPattern);

export function isWalletAddress(value: unknown): value is string {
  return typeof value === 'string' && WALLET_ADDRESS_PATTERN.test(value);
}
