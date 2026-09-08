<script lang="ts">
  import runtimeContract from '$lib/runtimeContract.fixture.json';
  import { page } from '$app/state';
  import { AUTH_COPY } from './copy';
  import { ACCOUNT_ACTION, CREDENTIAL_OUTCOME, submitCredentials } from './credentials';
  import { accountSession } from './session';
  import { LOGIN_PATH, REGISTER_PATH, accountPath, RETURN_TO_QUERY_PARAM } from './navigation';
  import './account.css';

  let { registering = false }: { registering?: boolean } = $props();
  let email = $state('');
  let password = $state('');
  let busy = $state(false);
  let error = $state('');
  const title = $derived(registering ? 'Create your account' : 'Welcome back');

  async function submit(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (busy) return;
    busy = true;
    error = '';
    try {
      const outcome = await submitCredentials(registering ? ACCOUNT_ACTION.REGISTER : ACCOUNT_ACTION.LOGIN, { email, password });
      if (outcome === CREDENTIAL_OUTCOME.AUTHENTICATED) {
        accountSession.acceptLogin(page.url.searchParams.get(RETURN_TO_QUERY_PARAM));
      } else if (outcome === CREDENTIAL_OUTCOME.RATE_LIMITED) {
        error = AUTH_COPY.RATE_LIMIT_ERROR;
      } else if (outcome === CREDENTIAL_OUTCOME.UNAVAILABLE) {
        error = AUTH_COPY.SERVICE_ERROR;
      } else {
        error = registering ? AUTH_COPY.REGISTER_ERROR : AUTH_COPY.LOGIN_ERROR;
      }
    } finally {
      password = '';
      busy = false;
    }
  }
</script>

<svelte:head><title>{title} | Polybot</title></svelte:head>
<section class="account-panel">
  <p class="eyebrow">Your private workspace</p>
  <h1>{title}</h1>
  <p>{registering ? 'Save your bots and follow your paper runs in one place. Registration signs you in immediately; no verification email is sent.' : 'Sign in to your bots, graphs, and run history.'}</p>
  <form onsubmit={submit}>
    <label for="account-email">{AUTH_COPY.EMAIL}</label>
    <input id="account-email" type="email" autocomplete="username" maxlength={runtimeContract.auth.emailMaxLength} bind:value={email} required />
    <label for="account-password">{AUTH_COPY.PASSWORD}</label>
    <input id="account-password" type="password" autocomplete={registering ? 'new-password' : 'current-password'} minlength={runtimeContract.auth.passwordMinLength} maxlength={runtimeContract.auth.passwordMaxLength} bind:value={password} required />
    <p class="field-help">Use {runtimeContract.auth.passwordMinLength}–{runtimeContract.auth.passwordMaxLength} characters. Password recovery is not available.</p>
    {#if error}<p role="alert" class="notice error">{error}</p>{/if}
    <button class="primary" type="submit" disabled={busy}>{busy ? AUTH_COPY.BUSY : registering ? AUTH_COPY.REGISTER : AUTH_COPY.SIGN_IN}</button>
  </form>
  <p>{registering ? 'Already have an account?' : 'New to Polybot?'} <a href={accountPath(registering ? LOGIN_PATH : REGISTER_PATH, page.url.searchParams.get(RETURN_TO_QUERY_PARAM))}>{registering ? AUTH_COPY.SIGN_IN : AUTH_COPY.REGISTER}</a></p>
</section>
