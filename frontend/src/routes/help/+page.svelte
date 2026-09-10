<script lang="ts">
  import { ACCOUNT_COPY } from "$lib/auth/recovery/copy";
  import { PUBLIC_COPY } from "$lib/public/copy";
  import PublicPage from "$lib/public/PublicPage.svelte";
  import BetaLimits from "$lib/public/BetaLimits.svelte";
  import { PUBLIC_INFORMATION_PATH } from "$lib/public/navigation";
  import { REGISTER_PATH, LOGIN_PATH } from "$lib/auth/navigation";
  import contract from "$lib/runtimeContract.fixture.json";
</script>

<PublicPage
  title="Your first paper run"
  intro="A saved strategy, an explicit launch and a clear record of what the simulation did."
>
  <section>
    <h2>Start with an example</h2>
    <ol>
      <li>
        <a href={REGISTER_PATH}>Create an account</a> inside the approved beta access boundary. Verify your email from {ACCOUNT_COPY.SETTINGS}
        before launching. Verification requires access to your mailbox and asks you to set your password.
      </li>
      <li>
        Choose guided setup from your empty bot list or {ACCOUNT_COPY.SETTINGS}. Read the example's conditions, choose
        available markets and set paper cash, order limits and latency.
      </li>
      <li>{PUBLIC_COPY.SAVE_BEFORE_RUN}</li>
      <li>
        Read the run guide, status, simulated balances and loaded orders/fills. Press Stop when finished. Reload to view
        retained history.
      </li>
    </ol>
  </section>
  <section>
    <h2>When a run is quiet</h2>
    <p>
      A running bot may be waiting for its condition. Check the latest book-health report and recorded progress.
      Unavailable or stale input, reconnection and failed or interrupted execution have different messages. Loaded
      history counts may cover only part of a longer run; load older events when available. Paper execution does not
      guarantee a fill.
    </p>
  </section>
  <section>
    <h2>Recover without guessing</h2>
    <p>
      If search fails, retry while keeping your selected markets. Capacity feedback explains whether to wait, stop an
      active run or reduce configuration. If a launch response is lost, retry on the saved bot page to recover its
      existing attempt. If that attempt has expired, the page asks for a new explicit Run.
    </p>
    <p>
      If a save result is unknown, return to your bots and inspect them before creating another copy. The current draft
      blocks blind resends; reloading starts a new blank form.
    </p>
  </section>
  <section>
    <h2>Account access and deletion</h2>
    <p>
      <a href={contract.accountManagement.forgotPath}>{PUBLIC_COPY.RESET}</a> using your registered mailbox. {PUBLIC_COPY.LINK_LIFETIME}
      Password reset revokes existing sessions. Signed-in {ACCOUNT_COPY.SETTINGS} support password changes, session revocation
      and password-confirmed account deletion.
    </p>
    <p>
      Deletion immediately revokes access and stops further execution; eligible stored account data is removed within {contract
        .dataLifecycle.deletionTargetHours} hours when maintenance is healthy. Read the
      <a href={PUBLIC_INFORMATION_PATH.PRIVACY}>{PUBLIC_COPY.DATA_POLICY}</a> for history, backups and audit retention.
    </p>
  </section>
  <BetaLimits />
  <p>
    <a href={LOGIN_PATH}>Sign in to your account</a> ·
    <a href={PUBLIC_INFORMATION_PATH.SUPPORT}>{PUBLIC_COPY.SUPPORT}</a>
  </p>
</PublicPage>
