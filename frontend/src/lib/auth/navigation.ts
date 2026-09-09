import contract from '$lib/runtimeContract.fixture.json' with { type: 'json' };
import { NAVIGATION_PATH } from '$lib/navigation';

export const LOGIN_PATH = '/login';
export const REGISTER_PATH = '/register';
export const ACCOUNT_UPDATED_QUERY_PARAM = 'accountUpdated';
export const RETURN_TO_QUERY_PARAM = 'returnTo';
const RETURN_PATH_ORIGIN = 'https://polybot.invalid';

export function accountPath(path: typeof LOGIN_PATH | typeof REGISTER_PATH, returnPath: string | null): string {
  return `${path}?${RETURN_TO_QUERY_PARAM}=${encodeURIComponent(safeReturnPath(returnPath))}`;
}

export function safeReturnPath(value: string | null): string {
  if (!value || !value.startsWith('/') || value.startsWith('//') || /[\\\u0000-\u0020]/.test(value)) return NAVIGATION_PATH.HOME;
  // Resolve dot segments before checking the origin and account-route redirect loops.
  const parsed = new URL(value, RETURN_PATH_ORIGIN);
  if (parsed.origin !== RETURN_PATH_ORIGIN || isAccountPath(parsed.pathname)) return NAVIGATION_PATH.HOME;
  return parsed.pathname + parsed.search + parsed.hash;
}

export function isAccountPath(path: string): boolean {
  return [LOGIN_PATH, REGISTER_PATH, contract.accountManagement.forgotPath, contract.accountManagement.resetPath, contract.accountManagement.verifyPath].includes(path);
}
