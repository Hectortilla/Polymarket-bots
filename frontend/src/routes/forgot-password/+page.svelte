<script lang="ts">
  import { ACCOUNT_COPY } from "$lib/auth/recovery/copy";
  import { SERVICE_NAME } from "$lib/serviceIdentity";
  import { PASSWORD_RESET_FLOW } from "$lib/auth/recovery/flows";

  import RequestLink from "$lib/auth/recovery/RequestLink.svelte";
  import { LOGIN_PATH } from "$lib/auth/navigation";
  import { AUTH_COPY } from "$lib/auth/copy";
</script>

<svelte:head><title>Reset password | {SERVICE_NAME}</title></svelte:head>
<section class="account-panel">
  <h1>{ACCOUNT_COPY.RESET_TITLE}</h1>
  <p>Enter your account email to request a reset link.</p>
  <RequestLink flow={PASSWORD_RESET_FLOW} />
  <p><a href={LOGIN_PATH}>{AUTH_COPY.SIGN_IN}</a></p>
</section>
