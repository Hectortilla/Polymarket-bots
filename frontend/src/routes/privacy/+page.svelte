<script lang="ts">
  import { ACCOUNT_COPY } from "$lib/auth/recovery/copy";
  import { PUBLIC_COPY } from "$lib/public/copy";
  import PublicPage from "$lib/public/PublicPage.svelte";
  import { SERVICE_IDENTITY } from "$lib/public/identity";
  import { PUBLIC_INFORMATION_PATH } from "$lib/public/navigation";
</script>

<PublicPage
  title="Privacy and data handling"
  intro="The data this paper-trading preview stores, why it is needed and how removal works."
>
  <p>
    Operator: {SERVICE_IDENTITY.operator}. This notice describes the implemented preview. Operator identity and a
    working contact must be supplied before public access opens.
  </p>
  <section>
    <h2>Account and strategy data</h2>
    <p>{PUBLIC_COPY.ACCOUNT_DATA}</p>
  </section>
  <section>
    <h2>Service operations and email</h2>
    <p>
      Request and authentication counters, run health, bounded operational logs and minimal operator audit records
      support resource limits, abuse prevention, incident handling and recovery. Recovery and verification emails are
      sent through the operator's configured SMTP provider; delivery depends on that provider and your mailbox. The
      application does not ask for a wallet key or payment details to use paper trading.
    </p>
  </section>
  <section>
    <h2>Retention and deletion</h2>
    <p>{PUBLIC_COPY.HISTORY_RETENTION}</p>
    <p>{PUBLIC_COPY.DELETION_RETENTION}</p>
    <p>{PUBLIC_COPY.RESTORE_QUARANTINE}</p>
  </section>
  <section>
    <h2>Access and questions</h2>
    <p>
      Review your saved bots and retained runs while signed in. Use {ACCOUNT_COPY.SETTINGS} for password, session and deletion
      controls. See <a href={PUBLIC_INFORMATION_PATH.SUPPORT}>{PUBLIC_COPY.SUPPORT}</a> for contact readiness and
      <a href={PUBLIC_INFORMATION_PATH.HELP}>help</a> for account recovery. This page does not promise indefinite storage
      of history.
    </p>
  </section>
</PublicPage>
