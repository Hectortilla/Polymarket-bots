<script lang="ts">
  import { PUBLIC_COPY } from "$lib/public/copy";
  import PublicPage from "$lib/public/PublicPage.svelte";
  import { PUBLIC_INFORMATION_PATH } from "$lib/public/navigation";
</script>

<PublicPage title="Terms of use" intro="Using the service and its limits.">
  <section>
    <h2>Simulated trading</h2>
    <p>{PUBLIC_COPY.TERMS_SCOPE}</p>
  </section>
  <section>
    <h2>Your responsibilities</h2>
    <p>
      Use an email address you control, keep your credentials secure and only submit strategies you have permission to
      use. Do not access other accounts, bypass usage limits or disrupt the service.
    </p>
  </section>
  <section>
    <h2>Availability and stored data</h2>
    <p>
      The service is in beta. Market data and runs may be interrupted. We may pause runs or suspend accounts to address
      incidents or abuse. Usage limits apply, and run history expires. Keep a copy of strategies you need.
    </p>
    <p>The <a href={PUBLIC_INFORMATION_PATH.PRIVACY}>{PUBLIC_COPY.DATA_POLICY}</a> explains retention and deletion.</p>
  </section>
  <p><a href={PUBLIC_INFORMATION_PATH.SUPPORT}>Contact support</a> with questions about these terms.</p>
</PublicPage>
