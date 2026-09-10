<script lang="ts">
  import { SERVICE_NAME } from '$lib/serviceIdentity';
  import { ONBOARDING_COPY } from '$lib/onboarding/copy';
  import { NAVIGATION_PATH } from '$lib/navigation';
  import { onMount } from 'svelte';
  import AccountDeletion from '$lib/lifecycle/AccountDeletion.svelte';
  import { accountStatus, changePassword, revokeSessions as revokeSessionsRequest, type AccountStatus, type SessionRevocation } from '$lib/api/generated';
  import contract from '$lib/runtimeContract.fixture.json';
  import { accountSession } from '$lib/auth/session';
  import { AUTH_COPY } from '$lib/auth/copy';
  import { ACCOUNT_COPY } from '$lib/auth/recovery/copy';
  import { EMAIL_VERIFICATION_FLOW } from '$lib/auth/recovery/flows';
  import { passwordsMatch } from '$lib/auth/recovery/validation';
  import { accountStatusMessage, SESSION_REVOCATION } from '$lib/auth/recovery/presentation';
  import { accountActionError } from '$lib/auth/recovery/result';
  import RequestLink from '$lib/auth/recovery/RequestLink.svelte';
  import NewPassword from '$lib/auth/recovery/NewPassword.svelte';
  const { account } = accountSession;
  let status = $state<AccountStatus | null>(null);
  let currentPassword = $state('');
  let password = $state('');
  let confirmation = $state('');
  let busy = $state(false);
  let error = $state('');
  let message = $state('');
  onMount(() => { void load(); });

  async function load(): Promise<void> {
    error = '';
    try {
      const result = await accountStatus();
      if (result.data) status = result.data;
      else error = AUTH_COPY.SERVICE_ERROR;
    } catch { error = AUTH_COPY.SERVICE_ERROR; }
  }

  async function submitPasswordChange(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (busy) return;
    if (!passwordsMatch(password, confirmation)) { error = ACCOUNT_COPY.PASSWORD_MISMATCH; return; }
    busy = true; error = ''; message = '';
    try {
      const result = await changePassword({ body: { current_password: currentPassword, new_password: password } });
      if (result.data) accountSession.credentialsRevoked();
      else error = accountActionError(result.response?.status);
    } catch { error = AUTH_COPY.SERVICE_ERROR; }
    finally { clearPasswords(); busy = false; }
  }

  async function revokeSessions(scope: SessionRevocation): Promise<void> {
    if (busy) return;
    busy = true; error = ''; message = '';
    try {
      const result = await revokeSessionsRequest({ body: { current_password: currentPassword, scope } });
      if (result.data) {
        if (contract.accountManagement.revokesCurrentSession[scope]) accountSession.credentialsRevoked();
        else message = ACCOUNT_COPY.OTHERS_DONE;
      } else error = accountActionError(result.response?.status);
    } catch { error = AUTH_COPY.SERVICE_ERROR; }
    finally { clearPasswords(); busy = false; }
  }

  function clearPasswords(): void { currentPassword = ''; password = ''; confirmation = ''; }
</script>
<svelte:head><title>Account settings | {SERVICE_NAME}</title></svelte:head>
<section class="account-panel">
  <h1>{ACCOUNT_COPY.SETTINGS}</h1>
  <p><a href={NAVIGATION_PATH.START}>{ONBOARDING_COPY.START}</a></p>
  {#if status}
    <p>{accountStatusMessage(status)}</p>
    {#if !status.email_verified}<RequestLink flow={EMAIL_VERIFICATION_FLOW} initialEmail={$account?.email ?? ''} />{/if}
  {:else}<button onclick={() => void load()}>Reload account status</button>{/if}
  <h2>Password and sessions</h2>
  <p>Enter your current password again to make changes. Changing your password or signing out all sessions requires a new sign-in. Already-authorized paper runs continue.</p>
  <form onsubmit={submitPasswordChange}>
    <label>{ACCOUNT_COPY.CURRENT_PASSWORD}<input type="password" autocomplete="current-password" minlength={contract.auth.passwordMinLength} maxlength={contract.auth.passwordMaxLength} bind:value={currentPassword} required /></label>
    <NewPassword bind:password bind:confirmation />
    <button type="submit" disabled={busy}>{busy ? AUTH_COPY.BUSY : ACCOUNT_COPY.CHANGE_PASSWORD}</button>
    <button type="button" disabled={busy || !currentPassword} onclick={() => void revokeSessions(SESSION_REVOCATION.OTHER)}>{ACCOUNT_COPY.REVOKE_OTHER}</button>
    <button type="button" disabled={busy || !currentPassword} onclick={() => void revokeSessions(SESSION_REVOCATION.ALL)}>{ACCOUNT_COPY.REVOKE_ALL}</button>
  </form>
  {#if error}<p role="alert" class="notice error">{error}</p>{/if}
  {#if message}<p role="status">{message}</p>{/if}
  <p>Recovery requires access to your registered mailbox. Email changes, identity transfers and support recovery overrides are unavailable.</p>
  <AccountDeletion />
</section>
