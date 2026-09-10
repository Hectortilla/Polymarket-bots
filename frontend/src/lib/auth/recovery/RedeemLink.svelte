<script lang="ts">
  import { untrack } from "svelte";
  import type { AccountLinkFlow } from "./flows";
  import { passwordsMatch } from "./validation";
  import { accountSession } from "../session";
  import { LOGIN_PATH } from "../navigation";
  import { AUTH_COPY } from "../copy";
  import { ACCOUNT_COPY } from "./copy";
  import { takeAccountLink } from "./link";
  import { accountActionError } from "./result";
  import RequestLink from "./RequestLink.svelte";
  import NewPassword from "./NewPassword.svelte";
  let { flow }: { flow: AccountLinkFlow } = $props();
  let token = $state(takeAccountLink());
  let password = $state("");
  let confirmation = $state("");
  let busy = $state(false);
  let done = $state(false);
  let error = $state(untrack(() => (token ? "" : ACCOUNT_COPY.INVALID_LINK)));

  async function submit(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (busy) return;
    if (!passwordsMatch(password, confirmation)) {
      error = ACCOUNT_COPY.PASSWORD_MISMATCH;
      return;
    }
    busy = true;
    error = "";
    try {
      const result = await flow.complete({ body: { token, new_password: password } });
      if (result.data) {
        token = "";
        done = true;
        accountSession.credentialsRevoked();
      } else error = accountActionError(result.response?.status, ACCOUNT_COPY.INVALID_LINK);
    } catch {
      error = AUTH_COPY.SERVICE_ERROR;
    } finally {
      password = "";
      confirmation = "";
      busy = false;
    }
  }
</script>

<svelte:head><meta name="referrer" content="no-referrer" /></svelte:head>
{#if done}
  <p role="status">{ACCOUNT_COPY.DONE}</p>
  <a href={LOGIN_PATH}>{AUTH_COPY.SIGN_IN}</a>
{:else}
  {#if token}
    <p>Choose a password to prove mailbox ownership. All browser sessions will be signed out. Paper runs continue.</p>
    <form onsubmit={submit}>
      <NewPassword bind:password bind:confirmation />
      <button type="submit" class="primary" disabled={busy}>{busy ? AUTH_COPY.BUSY : flow.completeLabel}</button>
    </form>
  {/if}
  {#if error}<p role="alert" class="notice error">{error}</p>{/if}
  <details open={!token}><summary>Request a new link</summary><RequestLink {flow} /></details>
{/if}
