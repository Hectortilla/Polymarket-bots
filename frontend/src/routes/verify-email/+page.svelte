<script lang="ts">
  import { SERVICE_NAME } from '$lib/serviceIdentity';
  import { EMAIL_VERIFICATION_FLOW } from '$lib/auth/recovery/flows';
import RedeemLink from '$lib/auth/recovery/RedeemLink.svelte';</script>
<svelte:head><title>Verify email | {SERVICE_NAME}</title></svelte:head>
<section class="account-panel"><h1>Verify your email</h1><RedeemLink flow={EMAIL_VERIFICATION_FLOW} /></section>
