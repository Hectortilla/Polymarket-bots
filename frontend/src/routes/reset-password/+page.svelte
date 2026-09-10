<script lang="ts">
  import { SERVICE_NAME } from '$lib/serviceIdentity';
  import { PASSWORD_RESET_FLOW } from '$lib/auth/recovery/flows';
import RedeemLink from '$lib/auth/recovery/RedeemLink.svelte';</script>
<svelte:head><title>Choose a password | {SERVICE_NAME}</title></svelte:head>
<section class="account-panel"><h1>Choose a new password</h1><RedeemLink flow={PASSWORD_RESET_FLOW} /></section>
