<script lang="ts">
  import { ACCOUNT_COPY } from "$lib/auth/recovery/copy";
  import { PUBLIC_COPY } from "$lib/public/copy";
  import PublicPage from "$lib/public/PublicPage.svelte";
  import { PUBLIC_INFORMATION_PATH } from "$lib/public/navigation";
  import contract from "$lib/runtimeContract.fixture.json";
</script>

<PublicPage title="Privacy" intro="What we store, why we store it and how to delete it.">
  <section>
    <h2>Account, bots and runs</h2>
    <p>{PUBLIC_COPY.ACCOUNT_DATA}</p>
  </section>
  <section>
    <h2>Service data and email</h2>
    <p>
      We keep request counts, service logs and audit records to enforce limits, prevent abuse and resolve problems. A
      configured email provider sends verification and password-reset messages. Paper trading does not require wallet
      keys or payment details.
    </p>
  </section>
  <section>
    <h2>How long data stays</h2>
    <p>{PUBLIC_COPY.HISTORY_RETENTION}</p>
  </section>
  <section>
    <h2>Deleting your account</h2>
    <p>{PUBLIC_COPY.DELETION_RETENTION}</p>
    <p>{PUBLIC_COPY.RESTORE_QUARANTINE}</p>
    <p><a href={contract.accountManagement.accountPath}>{ACCOUNT_COPY.SETTINGS}</a></p>
  </section>
  <p>For questions about your data, <a href={PUBLIC_INFORMATION_PATH.SUPPORT}>contact support</a>.</p>
</PublicPage>
