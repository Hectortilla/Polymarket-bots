<script lang="ts">
  import { PUBLIC_COPY } from "$lib/public/copy";
  import contract from "$lib/runtimeContract.fixture.json";
  const policy = contract.resourcePolicy;
</script>

<section>
  <h2>Beta allowances</h2>
  <p>{PUBLIC_COPY.ACCOUNT_LIMITS}</p>
  <p>
    The service admits up to {policy.global_active_runs} active and {policy.global_queued_runs} queued runs across accounts.
    Queue order, shared capacity, request limits and incident pauses can delay or reject a launch. Your signed-in account
    shows current usage and actionable capacity feedback.
  </p>
  <p>{PUBLIC_COPY.HISTORY_RETENTION}</p>
</section>
