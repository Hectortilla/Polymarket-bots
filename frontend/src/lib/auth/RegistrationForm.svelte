<script lang="ts">
  import { SERVICE_NAME } from "$lib/serviceIdentity";
  import runtimeContract from "$lib/runtimeContract.fixture.json";
  import type { CredentialsWritable } from "$lib/api/generated";
  import { page } from "$app/state";
  import { AUTH_COPY } from "./copy";
  import { credentialFailureMessage } from "./credentialPresentation";
  import { ACCOUNT_ACTION, CREDENTIAL_OUTCOME, submitCredentials } from "./credentials";
  import { accountSession } from "./session";
  import { LOGIN_PATH, accountPath, RETURN_TO_QUERY_PARAM } from "./navigation";
  import CredentialForm from "./CredentialForm.svelte";
  import "./account.css";

  async function submit(credentials: CredentialsWritable): Promise<string | undefined> {
    const outcome = await submitCredentials(ACCOUNT_ACTION.REGISTER, credentials);
    if (outcome === CREDENTIAL_OUTCOME.AUTHENTICATED) {
      accountSession.acceptLogin(runtimeContract.accountManagement.accountPath);
    }
    return credentialFailureMessage(outcome, AUTH_COPY.REGISTER_ERROR);
  }
</script>

<svelte:head><title>Create your account | {SERVICE_NAME}</title></svelte:head>
<section class="account-panel">
  <p class="eyebrow">{AUTH_COPY.WORKSPACE_TAGLINE}</p>
  <h1>Create your account</h1>
  <p>
    Save your bots and follow your paper runs in one place. Registration signs you in immediately. Verify your email in
    Account settings before launching a run.
  </p>
  <CredentialForm
    onsubmit={submit}
    submitLabel={AUTH_COPY.REGISTER}
    passwordAutocomplete="new-password"
    passwordMinimumLength={runtimeContract.auth.passwordMinLength}
  >
    {#snippet passwordHelp()}
      <p class="field-help">
        Use {runtimeContract.auth.passwordMinLength}-{runtimeContract.auth.passwordMaxLength} characters.
      </p>
    {/snippet}
  </CredentialForm>
  <p>
    Already have an account? <a href={accountPath(LOGIN_PATH, page.url.searchParams.get(RETURN_TO_QUERY_PARAM))}
      >{AUTH_COPY.SIGN_IN}</a
    >
  </p>
</section>
