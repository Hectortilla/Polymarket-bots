<script lang="ts">
  import { untrack } from 'svelte';
  import contract from '$lib/runtimeContract.fixture.json';
  import type { AccountLinkFlow } from './flows';
  import { AUTH_COPY } from '../copy';
  import { ACCOUNT_COPY } from './copy';
  import { HTTP_STATUS } from '$lib/api/http';
  let { flow, initialEmail = '' }: { flow: AccountLinkFlow; initialEmail?: string } = $props();
  let email = $state(untrack(() => initialEmail));
  let busy = $state(false);
  let message = $state('');
  let error = $state('');

  async function submit(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (busy) return;
    busy = true; error = ''; message = '';
    try {
      const result = await flow.request({ body: { email } });
      if (result.data) message = ACCOUNT_COPY.SENT;
      else error = result.response?.status === HTTP_STATUS.TOO_MANY_REQUESTS ? AUTH_COPY.RATE_LIMIT_ERROR : ACCOUNT_COPY.DELIVERY_FAILED;
    } catch { error = ACCOUNT_COPY.DELIVERY_FAILED; }
    finally { busy = false; }
  }
</script>
<form onsubmit={submit}>
  <label>{AUTH_COPY.EMAIL}<input type="email" autocomplete="email" maxlength={contract.auth.emailMaxLength} bind:value={email} required /></label>
  <button type="submit" class="primary" disabled={busy}>{busy ? AUTH_COPY.BUSY : flow.requestLabel}</button>
  {#if message}<p role="status">{message}</p>{/if}
  {#if error}<p role="alert" class="notice error">{error}</p>{/if}
</form>
