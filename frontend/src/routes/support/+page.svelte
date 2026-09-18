<script lang="ts">
  import { ACCOUNT_COPY } from "$lib/auth/recovery/copy";
  import { PUBLIC_COPY } from "$lib/public/copy";
  import SupportContact from "$lib/public/SupportContact.svelte";
  import PublicPage from "$lib/public/PublicPage.svelte";
  import { PUBLIC_INFORMATION_PATH } from "$lib/public/navigation";
  import { accountSession } from "$lib/auth/session";
  import contract from "$lib/runtimeContract.fixture.json";
  const { account } = accountSession;
</script>

<PublicPage title={PUBLIC_COPY.SUPPORT} intro="Report a problem or send feedback.">
  <section>
    <h2>Email</h2>
    <SupportContact />
    <p>
      Include what happened, the error message and the run ID if relevant. Never send passwords, recovery links or
      wallet keys.
    </p>
  </section>
  <section>
    <h2>Common questions</h2>
    <p><a href={PUBLIC_INFORMATION_PATH.HELP}>Bot setup and run troubleshooting</a></p>
    {#if $account}
      <p>
        <a href={contract.accountManagement.accountPath}>{ACCOUNT_COPY.SETTINGS}</a> — email verification, password, sessions
        and deletion.
      </p>
    {:else}
      <p><a href={contract.accountManagement.forgotPath}>{PUBLIC_COPY.RECOVER}</a></p>
    {/if}
  </section>
</PublicPage>
