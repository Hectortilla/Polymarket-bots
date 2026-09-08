<script lang="ts">
  import runtimeContract from '$lib/runtimeContract.fixture.json';
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { accountSession } from '$lib/auth/session';
  import { configureAccountBoundary } from '$lib/auth/session/clientBoundary';
  import { AUTH_COPY } from '$lib/auth/copy';

  import { isAccountPath } from '$lib/auth/navigation';
  import '$lib/auth/account.css';
  import { configureApiResponseValidation } from '$lib/api/responseValidation/index';
  import { NAVIGATION_PATH } from '$lib/navigation';
  import '@fontsource-variable/geist';
  import '@fontsource-variable/geist-mono';
  import '../app.css';

  const { account, ready: accountReady, error: accountError } = accountSession;
  configureApiResponseValidation();
  configureAccountBoundary();
  onMount(() => {
    void accountSession.restore();
    const unwatch = accountSession.watchChanges();
    const interval = setInterval(() => { if ($account) void accountSession.restore(); }, runtimeContract.auth.sessionRecheckMs);
    return () => { clearInterval(interval); unwatch(); };
  });

  let { children } = $props();
</script>

<svelte:head>
  <title>Polybot control plane</title>
  <meta name="description" content="Private launch and run interface for Polybot paper trading." />
</svelte:head>

<a class="skip-link" href="#main-content">Skip to content</a>

<header class="site-header">
  <div class="site-header-inner">
    <a class="brand" href={NAVIGATION_PATH.HOME} aria-label="Polybot bots">
      <span class="brand-mark" aria-hidden="true"></span>
      <span>Polybot</span>
    </a>
    <span class="environment-label">paper trading</span>
    {#if $account}
      <div class="account-controls"><span>{$account.email}</span><button onclick={() => void accountSession.signOut()}>{AUTH_COPY.SIGN_OUT}</button></div>
    {/if}
  </div>
</header>

<main id="main-content">
  {#if $accountError}
    <p role="alert" class="notice error">{$accountError}</p>
    <button onclick={() => void accountSession.restore()}>Retry session</button>
    <button onclick={() => void accountSession.signOut()}>Retry sign out</button>
  {:else if !$accountReady}
    <p role="status">Restoring your session…</p>
  {:else if $account || isAccountPath(page.url.pathname)}
    {#key $account?.id ?? 'signed-out'}{@render children()}{/key}
  {/if}
</main>
