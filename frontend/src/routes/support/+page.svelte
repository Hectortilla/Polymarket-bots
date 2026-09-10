<script lang="ts">
  import { ACCOUNT_COPY } from "$lib/auth/recovery/copy";
  import { PUBLIC_COPY } from "$lib/public/copy";
  import SupportContact from "$lib/public/SupportContact.svelte";
  import PublicPage from "$lib/public/PublicPage.svelte";
  import { SERVICE_IDENTITY } from "$lib/public/identity";
  import { PUBLIC_INFORMATION_PATH } from "$lib/public/navigation";
  import contract from "$lib/runtimeContract.fixture.json";
</script>

<PublicPage title={PUBLIC_COPY.SUPPORT} intro="Recover access, understand a run or report a problem with the preview.">
  <section>
    <h2>Contact readiness</h2>
    <p>{PUBLIC_COPY.RESPONSIBLE_OPERATOR} {SERVICE_IDENTITY.operator}.</p>
    <SupportContact />
  </section>
  <section>
    <h2>Available self-service</h2>
    <p>
      <a href={contract.accountManagement.forgotPath}>{PUBLIC_COPY.RECOVER}</a>, or consult
      <a href={PUBLIC_INFORMATION_PATH.HELP}>the run and account guide</a>. While signed in, {ACCOUNT_COPY.SETTINGS} let you
      change your password, revoke sessions and request deletion.
    </p>
  </section>
  <section>
    <h2>When reporting a problem</h2>
    <p>
      Once the contact is configured, include the time, visible error and relevant run identifier, plus steps to
      reproduce. Never send passwords, session cookies, recovery links, wallet keys or private strategy details that are
      not needed. There is no promised response time during the preview.
    </p>
  </section>
</PublicPage>
