<script lang="ts">
  import runtimeContract from "$lib/runtimeContract.fixture.json";
  import { onMount, untrack } from "svelte";
  import { page } from "$app/state";
  import { accountSession } from "$lib/auth/session";
  import { configureAccountBoundary } from "$lib/auth/session/clientBoundary";
  import { AUTH_COPY } from "$lib/auth/copy";

  import { isAccountPath } from "$lib/auth/navigation";
  import "$lib/auth/account.css";
  import { captureAccountLink } from "$lib/auth/recovery/link";
  import { ACCOUNT_COPY } from "$lib/auth/recovery/copy";
  import { configureApiResponseValidation } from "$lib/api/responseValidation/index";
  import {
    isPublicInformationPath,
    PUBLIC_INFORMATION_PATH,
    PUBLIC_INFORMATION_LABEL,
    PUBLIC_PRELOAD_DATA_POLICY,
  } from "$lib/public/navigation";
  import { SERVICE_IDENTITY } from "$lib/public/identity";
  import { LOGIN_PATH } from "$lib/auth/navigation";
  import { NAVIGATION_PATH } from "$lib/navigation";
  import "@fontsource-variable/geist";
  import "@fontsource-variable/geist-mono";
  import "../app.css";

  let { children } = $props();
  const { account, ready: accountReady, error: accountError } = accountSession;

  captureAccountLink();
  configureApiResponseValidation();
  configureAccountBoundary();
  onMount(() => {
    // Restore once on direct public visits so the copy also fits returning users.
    if (isPublicInformationPath(page.url.pathname)) void accountSession.restore();
    const unwatch = accountSession.watchChanges();
    const interval = setInterval(() => {
      if ($account && !isPublicInformationPath(page.url.pathname)) void accountSession.restore();
    }, runtimeContract.auth.sessionRecheckMs);
    return () => {
      clearInterval(interval);
      unwatch();
    };
  });

  // Restore on route changes only; session-store reads must not retrigger this effect.
  // Public-to-public navigation reuses the session without fetching bots, runs or usage.
  $effect(() => {
    if (!isPublicInformationPath(page.url.pathname))
      untrack(() => {
        void accountSession.restore();
      });
  });
</script>

<svelte:head>
  <title>{SERVICE_IDENTITY.name}</title>
  <meta name="description" content="Build trading bots and test them with simulated funds." />
</svelte:head>

<a class="skip-link" href="#main-content">Skip to content</a>

<!-- Header links share the public no-preload boundary, including Sign in. -->
<header class="site-header" data-sveltekit-preload-data={PUBLIC_PRELOAD_DATA_POLICY}>
  <div class="site-header-inner">
    <a class="brand" href={NAVIGATION_PATH.HOME} aria-label={SERVICE_IDENTITY.name}>
      <span class="brand-mark" aria-hidden="true"></span>
      <span>{SERVICE_IDENTITY.name}</span>
    </a>
    <span class="environment-label">paper trading</span>
    <nav class="account-controls" aria-label="Account navigation">
      {#if $account}<span>{$account.email}</span>{/if}
      <a href={PUBLIC_INFORMATION_PATH.HELP}>{PUBLIC_INFORMATION_LABEL[PUBLIC_INFORMATION_PATH.HELP]}</a>
      {#if $account}
        <a href={runtimeContract.accountManagement.accountPath}>{ACCOUNT_COPY.SETTINGS}</a>
        <button class="secondary" onclick={() => void accountSession.signOut()}>{AUTH_COPY.SIGN_OUT}</button>
      {:else}
        <a href={LOGIN_PATH}>{AUTH_COPY.SIGN_IN}</a>
      {/if}
    </nav>
  </div>
</header>

<main id="main-content">
  {#if $accountError}
    <p role="alert" class="notice error">{$accountError}</p>
    <button onclick={() => void accountSession.restore()}>Retry session</button>
    <button class="secondary" onclick={() => void accountSession.signOut()}>Retry sign out</button>
  {/if}
  {#if isPublicInformationPath(page.url.pathname)}
    {@render children()}
  {:else if !$accountError}
    {#if !$accountReady}
      <p role="status">Restoring your session…</p>
    {:else if $account || isAccountPath(page.url.pathname)}
      {#key $account?.id ?? "signed-out"}{@render children()}{/key}
    {/if}
  {/if}
</main>
