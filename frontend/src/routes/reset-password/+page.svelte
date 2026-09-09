<script lang="ts">
  import { PASSWORD_RESET_FLOW } from '$lib/auth/recovery/flows';
import RedeemLink from '$lib/auth/recovery/RedeemLink.svelte';</script>
<svelte:head><title>Choose a password | Polybot</title></svelte:head>
<section class="account-panel"><h1>Choose a new password</h1><RedeemLink flow={PASSWORD_RESET_FLOW} /></section>
