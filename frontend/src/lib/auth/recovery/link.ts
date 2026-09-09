import contract from '$lib/runtimeContract.fixture.json';

let pendingToken = '';

export function captureAccountLink(): void {
  if (typeof window === 'undefined') return;
  const { resetPath, verifyPath } = contract.accountManagement;
  if (![resetPath, verifyPath].includes(window.location.pathname)) return;
  const fragment = window.location.hash.slice(1);
  // Remove secrets before account restoration, form rendering or any API request.
  window.history.replaceState(window.history.state, '', window.location.pathname);
  pendingToken = new RegExp(`^${contract.accountManagement.tokenPattern}$`).test(fragment) ? fragment : '';
}

export function takeAccountLink(): string {
  const capturedToken = pendingToken;
  pendingToken = '';
  return capturedToken;
}
