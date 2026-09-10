<script lang="ts">
  import { SERVICE_NAME } from '$lib/serviceIdentity';
  import { PASSWORD_RESET_FLOW } from '$lib/auth/recovery/flows';

  import RequestLink from '$lib/auth/recovery/RequestLink.svelte';
  import { LOGIN_PATH } from '$lib/auth/navigation';
  import { AUTH_COPY } from '$lib/auth/copy';
</script>
<svelte:head><title>Reset password | {SERVICE_NAME}</title></svelte:head>
<section class="account-panel"><h1>Reset your password</h1><p>Enter your registered email. You need access to that mailbox to recover your account.</p><RequestLink flow={PASSWORD_RESET_FLOW} /><p><a href={LOGIN_PATH}>{AUTH_COPY.SIGN_IN}</a></p></section>
