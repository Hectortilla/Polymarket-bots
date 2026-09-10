<script lang="ts">
  import { requestAccountDeletion } from "$lib/api/generated";
  import contract from "$lib/runtimeContract.fixture.json";
  import { accountSession } from "$lib/auth/session";
  import { ACCOUNT_DELETION_QUERY_PARAM } from "$lib/auth/navigation";
  import { accountActionError } from "$lib/auth/recovery/result";
  import { AUTH_COPY } from "$lib/auth/copy";
  import { LIFECYCLE_COPY } from "./copy";

  let password = $state("");
  let confirmed = $state(false);
  let busy = $state(false);
  let error = $state("");

  async function submit(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (busy || !confirmed) return;
    busy = true;
    error = "";
    try {
      const result = await requestAccountDeletion({ body: { current_password: password } });
      if (result.data) accountSession.credentialsRevoked(ACCOUNT_DELETION_QUERY_PARAM);
      else error = accountActionError(result.response?.status);
    } catch {
      error = LIFECYCLE_COPY.AMBIGUOUS_RESPONSE;
    } finally {
      password = "";
      busy = false;
    }
  }
</script>

<section aria-labelledby="delete-account-heading">
  <h2 id="delete-account-heading">{LIFECYCLE_COPY.DELETE_HEADING}</h2>
  <p>{LIFECYCLE_COPY.HISTORY}</p>
  <p>
    This immediately signs out every session and stops queued and active paper runs. Eligible account details, bots,
    graphs and run history are removed within {contract.dataLifecycle.deletionTargetHours} hours. You cannot undo the request.
  </p>
  <p>
    Encrypted backups expire within {contract.dataLifecycle.backupRetentionDays} days. Minimal deletion and operator receipts
    remain for {contract.dataLifecycle.auditRetentionDays} days. Export any graphs you need before continuing.
  </p>
  <form onsubmit={submit}>
    <label
      >{LIFECYCLE_COPY.PASSWORD}<input
        type="password"
        autocomplete="current-password"
        minlength={contract.auth.existingPasswordMinLength}
        maxlength={contract.auth.passwordMaxLength}
        bind:value={password}
        required
      /></label
    >
    <label><input type="checkbox" bind:checked={confirmed} required /> {LIFECYCLE_COPY.CONFIRM}</label>
    <button type="submit" disabled={busy || !confirmed}>{busy ? AUTH_COPY.BUSY : LIFECYCLE_COPY.DELETE}</button>
    {#if error}<p role="alert">{error}</p>{/if}
  </form>
</section>
