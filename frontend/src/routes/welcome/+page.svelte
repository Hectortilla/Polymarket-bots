<script lang="ts">
  import { PUBLIC_COPY } from '$lib/public/copy';
  import PublicPage from '$lib/public/PublicPage.svelte';
  import BetaLimits from '$lib/public/BetaLimits.svelte';
  import { PUBLIC_INFORMATION_PATH } from '$lib/public/navigation';
  import SupportContact from '$lib/public/SupportContact.svelte';
  import { REGISTER_PATH, LOGIN_PATH } from '$lib/auth/navigation';
  import { AUTH_COPY } from '$lib/auth/copy';
</script>
<PublicPage title="Build a strategy. Observe a paper run." intro="Compose visual trading logic, save a private bot and see how it behaves with simulated execution.">
  <SupportContact />
  <section><h2>From an example to your own strategy</h2><p>Choose a catalog example in guided setup, select available markets and review paper cash, order limits and simulated latency. Save your private copy, then press Run when you are ready. The full node editor lets you connect event triggers, conditions and actions.</p></section>
  <section><h2>See what happened</h2><p>Read run status, simulated cash and equity, orders, fills and recorded progress. Waiting for a condition can be a valid result. Missing or stale data is shown as unavailable; it is not a zero balance or a prediction. Stop a run and revisit its retained history.</p></section>
  <section><h2>Simulation has limits</h2><p>{PUBLIC_COPY.SIMULATION}</p></section>
  <BetaLimits />
  <p><a href={PUBLIC_INFORMATION_PATH.HELP}>Read the getting-started guide</a> · <a href={LOGIN_PATH}>{AUTH_COPY.SIGN_IN}</a> · <a href={REGISTER_PATH}>{AUTH_COPY.REGISTER}</a></p>
</PublicPage>
