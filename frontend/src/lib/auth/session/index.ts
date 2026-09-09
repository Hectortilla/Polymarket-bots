import { derived, get, writable } from 'svelte/store';
import { AUTH_COPY } from '../copy';
import { ACCOUNT_UPDATED_QUERY_PARAM, accountPath, isAccountPath, LOGIN_PATH, safeReturnPath } from '../navigation';
import { AccountChannel } from './crossTab';
import { ACCOUNT_LOOKUP, lookupCurrentAccount, revokeCurrentSession } from './requests';
import { ACCOUNT_FAILURE, ACCOUNT_SESSION_STATUS, type AccountSessionState } from './state';
import { PrivateStreams } from './streams';

const ACCOUNT_FAILURE_COPY = {
  [ACCOUNT_FAILURE.RESTORE]: AUTH_COPY.RESTORE_ERROR,
  [ACCOUNT_FAILURE.SIGN_OUT]: AUTH_COPY.SIGN_OUT_ERROR,
};

export class AccountSession {
  readonly state = writable<AccountSessionState>({ status: ACCOUNT_SESSION_STATUS.RESTORING });
  readonly account = derived(this.state, state => state.status === ACCOUNT_SESSION_STATUS.AUTHENTICATED ? state.user : null);
  readonly ready = derived(this.state, state => state.status !== ACCOUNT_SESSION_STATUS.RESTORING && state.status !== ACCOUNT_SESSION_STATUS.SIGNING_OUT);
  readonly error = derived(this.state, state => state.status === ACCOUNT_SESSION_STATUS.FAILURE
    ? ACCOUNT_FAILURE_COPY[state.reason]
    : '');
  readonly streams = new PrivateStreams();
  private readonly channel = new AccountChannel();
  private privateSessionGeneration = 0;
  private pendingRestoration: Promise<void> | null = null;

  restore(): Promise<void> {
    if (get(this.state).status === ACCOUNT_SESSION_STATUS.SIGNING_OUT) return Promise.resolve();
    if (this.pendingRestoration) return this.pendingRestoration;
    const pending = this.restoreCurrentUser();
    this.pendingRestoration = pending;
    void pending.finally(() => this.clearRestorationIfCurrent(pending));
    return pending;
  }

  async signOut(): Promise<void> {
    // Hide private views immediately, including when revocation fails.
    this.clear();
    this.state.set({ status: ACCOUNT_SESSION_STATUS.SIGNING_OUT });
    if (await revokeCurrentSession()) {
      this.channel.announce();
      this.expire();
    } else {
      this.state.set({ status: ACCOUNT_SESSION_STATUS.FAILURE, reason: ACCOUNT_FAILURE.SIGN_OUT });
    }
  }

  watchChanges(): () => void {
    return this.channel.watch(() => {
      this.clear();
      window.location.reload();
    });
  }

  acceptLogin(returnPath: string | null): void {
    this.clear();
    this.channel.announce();
    window.location.replace(safeReturnPath(returnPath));
  }

  credentialsRevoked(): void {
    this.clear();
    this.channel.announce();
    window.location.replace(`${LOGIN_PATH}?${ACCOUNT_UPDATED_QUERY_PARAM}=1`);
  }

  expire(): void {
    this.clear();
    if (!isAccountPath(window.location.pathname)) {
      window.location.replace(accountPath(LOGIN_PATH, window.location.pathname + window.location.search));
    }
  }

  clear(): void {
    this.privateSessionGeneration += 1;
    this.pendingRestoration = null;
    this.streams.clear();
    this.state.set({ status: ACCOUNT_SESSION_STATUS.SIGNED_OUT });
  }

  private async restoreCurrentUser(): Promise<void> {
    // Logout/account switching invalidates responses that were already in flight.
    const expectedPrivateSessionGeneration = this.privateSessionGeneration;
    const result = await lookupCurrentAccount();
    if (expectedPrivateSessionGeneration !== this.privateSessionGeneration) return;
    if (result.status === ACCOUNT_LOOKUP.EXPIRED) {
      this.expire();
    } else if (result.status === ACCOUNT_LOOKUP.UNAVAILABLE) {
      this.clear();
      this.state.set({ status: ACCOUNT_SESSION_STATUS.FAILURE, reason: ACCOUNT_FAILURE.RESTORE });
    } else {
      const previous = get(this.account);
      if (previous && previous.id !== result.user.id) this.clear();
      this.state.set({ status: ACCOUNT_SESSION_STATUS.AUTHENTICATED, user: result.user });
    }
  }

  private clearRestorationIfCurrent(pending: Promise<void>): void {
    if (this.pendingRestoration === pending) this.pendingRestoration = null;
  }
}

export const accountSession = new AccountSession();
