<script lang="ts">
  import { PUBLIC_COPY } from "$lib/public/copy";
  import PublicPage from "$lib/public/PublicPage.svelte";
  import { PUBLIC_INFORMATION_PATH } from "$lib/public/navigation";
  import { REGISTER_PATH, LOGIN_PATH } from "$lib/auth/navigation";
  import { AUTH_COPY } from "$lib/auth/copy";
  import { accountSession } from "$lib/auth/session";
  import { NAVIGATION_PATH } from "$lib/navigation";
  const { account } = accountSession;
</script>

<PublicPage
  title={$account ? "Overview" : "Test trading strategies with simulated funds"}
  intro={$account
    ? "Build a bot, run it and review its results."
    : "Build bots for Polymarket with a visual editor, then see how they behave in a paper run."}
>
  <div class="welcome-actions">
    {#if $account}
      <a class="primary-link" href={NAVIGATION_PATH.HOME}>Your bots</a>
      <a href={NAVIGATION_PATH.START}>Create from an example</a>
    {:else}
      <a class="primary-link" href={REGISTER_PATH}>{AUTH_COPY.REGISTER}</a>
      <a href={LOGIN_PATH}>{AUTH_COPY.SIGN_IN}</a>
    {/if}
  </div>
  <section>
    <h2>{$account ? "Create or edit a bot" : "Define when your bot should trade"}</h2>
    <p>
      Start from an example or connect triggers, conditions and actions in the visual editor. Choose markets and order
      settings, then save your bot. You decide when to start each run.
    </p>
  </section>
  <section>
    <h2>Review each run</h2>
    <p>
      Follow orders, fills and simulated balances. Check the event history to understand what the bot did, stop a run
      when needed, or return to recent results from your bot page.
    </p>
  </section>
  <section>
    <h2>Paper trading only</h2>
    <p>{PUBLIC_COPY.SIMULATION}</p>
  </section>
  <p><a href={PUBLIC_INFORMATION_PATH.HELP}>{$account ? "Run and account help" : "How to get started"}</a></p>
</PublicPage>

<style>
  .welcome-actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 20px;
    margin-bottom: 24px;
    font-size: 0.8125rem;
  }
  .welcome-actions .primary-link {
    font-size: 0.8125rem;
    text-decoration: none;
  }
</style>
