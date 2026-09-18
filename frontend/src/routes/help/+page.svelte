<script lang="ts">
  import { ACCOUNT_COPY } from "$lib/auth/recovery/copy";
  import { PUBLIC_COPY } from "$lib/public/copy";
  import PublicPage from "$lib/public/PublicPage.svelte";
  import { PUBLIC_INFORMATION_PATH } from "$lib/public/navigation";
  import { REGISTER_PATH, LOGIN_PATH } from "$lib/auth/navigation";
  import { NAVIGATION_PATH } from "$lib/navigation";
  import { accountSession } from "$lib/auth/session";
  import contract from "$lib/runtimeContract.fixture.json";
  const { account } = accountSession;
</script>

<PublicPage
  title="Help"
  intro={$account
    ? "Create a bot, troubleshoot a run or manage your account."
    : "How to get started and recover account access."}
>
  <section>
    <h2>{$account ? "Start a run" : "Get started"}</h2>
    <ol>
      {#if !$account}
        <li>
          <a href={REGISTER_PATH}>Create an account</a> or <a href={LOGIN_PATH}>sign in</a>. New accounts need email
          verification before running a bot.
        </li>
      {/if}
      <li>
        {#if $account}<a href={NAVIGATION_PATH.START}>Choose an example</a> or
          <a href={NAVIGATION_PATH.NEW_BOT}>use the editor</a>.
        {:else}Choose an example or build a strategy in the visual editor.{/if}
        Select markets and set your simulated balance and order settings.
      </li>
      <li>{PUBLIC_COPY.SAVE_BEFORE_RUN}</li>
      <li>Follow orders, fills and balances on the run page. Select Stop to end the run.</li>
    </ol>
  </section>
  <section>
    <h2>No orders or fills?</h2>
    <p>
      A running bot may be waiting for its conditions to be met. Check the run’s status and event history for missing or
      stale market data, skipped orders or errors. An order does not guarantee a fill.
    </p>
  </section>
  <section>
    <h2>A save or launch failed?</h2>
    <p>
      Follow the message next to the action. If a save could not be confirmed, check your bot list before creating
      another copy. If a launch could not be confirmed, retry from the saved bot page to check the original attempt.
    </p>
    <p>For capacity limits, check Account usage on your bot list or setup page.</p>
  </section>
  <section>
    <h2>{$account ? "Manage your account" : "Trouble signing in?"}</h2>
    {#if $account}
      <p>
        Open <a href={contract.accountManagement.accountPath}>{ACCOUNT_COPY.SETTINGS}</a> to verify your email, change your
        password, sign out other devices or delete your account.
      </p>
    {:else}
      <p>
        <a href={contract.accountManagement.forgotPath}>{ACCOUNT_COPY.RESET_TITLE}</a> using your account email. You need
        access to that inbox. Resetting your password signs you out on all devices.
      </p>
      <p>{PUBLIC_COPY.LINK_LIFETIME}</p>
    {/if}
    <p><a href={PUBLIC_INFORMATION_PATH.PRIVACY}>Data retention and deletion</a></p>
  </section>
  <p><a href={PUBLIC_INFORMATION_PATH.SUPPORT}>Contact support</a></p>
</PublicPage>
