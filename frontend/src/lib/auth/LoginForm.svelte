<script lang="ts">
  import { SERVICE_NAME } from "$lib/serviceIdentity";
  import runtimeContract from "$lib/runtimeContract.fixture.json";
  import type { CredentialsWritable } from "$lib/api/generated";
  import { page } from "$app/state";
  import { AUTH_COPY } from "./copy";
  import { credentialFailureMessage } from "./credentialPresentation";
  import { ACCOUNT_ACTION, CREDENTIAL_OUTCOME, submitCredentials } from "./credentials";
  import { accountSession } from "./session";
  import {
    REGISTER_PATH,
    accountPath,
    RETURN_TO_QUERY_PARAM,
    ACCOUNT_UPDATED_QUERY_PARAM,
    ACCOUNT_DELETION_QUERY_PARAM,
  } from "./navigation";
  import { LIFECYCLE_COPY } from "$lib/lifecycle/copy";
  import CredentialForm from "./CredentialForm.svelte";
  import "./account.css";
  import { ACCOUNT_COPY } from "./recovery/copy";

  async function submit(credentials: CredentialsWritable): Promise<string | undefined> {
    const outcome = await submitCredentials(ACCOUNT_ACTION.LOGIN, credentials);
    if (outcome === CREDENTIAL_OUTCOME.AUTHENTICATED) {
      accountSession.acceptLogin(page.url.searchParams.get(RETURN_TO_QUERY_PARAM));
    }
    return credentialFailureMessage(outcome, AUTH_COPY.LOGIN_ERROR);
  }
</script>

<svelte:head><title>Welcome back | {SERVICE_NAME}</title></svelte:head>
<section class="account-panel">
  <p class="eyebrow">Your private workspace</p>
  <h1>Welcome back</h1>
  <p>Sign in to your bots, graphs, and run history.</p>
  {#if page.url.searchParams.has(ACCOUNT_UPDATED_QUERY_PARAM)}<p role="status">{ACCOUNT_COPY.DONE}</p>{/if}
  {#if page.url.searchParams.has(ACCOUNT_DELETION_QUERY_PARAM)}<p role="status">{LIFECYCLE_COPY.REQUESTED}</p>{/if}
  <CredentialForm
    onsubmit={submit}
    submitLabel={AUTH_COPY.SIGN_IN}
    passwordAutocomplete="current-password"
    passwordMinimumLength={runtimeContract.auth.existingPasswordMinLength}
  ></CredentialForm>
  <p><a href={runtimeContract.accountManagement.forgotPath}>{ACCOUNT_COPY.FORGOT}</a></p>
  <p>
    New to {SERVICE_NAME}?
    <a href={accountPath(REGISTER_PATH, page.url.searchParams.get(RETURN_TO_QUERY_PARAM))}>{AUTH_COPY.REGISTER}</a>
  </p>
</section>
