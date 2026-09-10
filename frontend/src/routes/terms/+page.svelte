<script lang="ts">
  import { PUBLIC_COPY } from "$lib/public/copy";
  import PublicPage from "$lib/public/PublicPage.svelte";
  import { SERVICE_IDENTITY } from "$lib/public/identity";
  import { PUBLIC_INFORMATION_PATH } from "$lib/public/navigation";
</script>

<PublicPage title="Preview terms" intro="Scope and acceptable use of the paper-trading preview.">
  <p>
    Operator: {SERVICE_IDENTITY.operator}. These preview terms and contact details must be finalized by the operator
    before public opening.
  </p>
  <section>
    <h2>Paper execution only</h2>
    <p>{PUBLIC_COPY.TERMS_SCOPE}</p>
  </section>
  <section>
    <h2>Your account and content</h2>
    <p>
      Use an email account you control, protect your credentials and only submit strategy content you are authorized to
      use. Do not attempt to access another account's resources, bypass allowances, interfere with the service or
      automate abuse of signup and recovery. Private strategies are not published to a marketplace.
    </p>
  </section>
  <section>
    <h2>Beta availability and limits</h2>
    <p>
      Availability and market inputs may be interrupted. Operators can pause admission, stop runs or suspend accounts to
      handle incidents or abuse. Runs and requests have bounded allowances; history expires under the <a
        href={PUBLIC_INFORMATION_PATH.PRIVACY}>{PUBLIC_COPY.DATA_POLICY}</a
      >. Keep your own strategy records where needed. Changes to these preview terms must be made visible before the
      operator opens the service.
    </p>
  </section>
  <p>
    Read <a href={PUBLIC_INFORMATION_PATH.HELP}>help and current limits</a> or
    <a href={PUBLIC_INFORMATION_PATH.SUPPORT}>support readiness</a>.
  </p>
</PublicPage>
