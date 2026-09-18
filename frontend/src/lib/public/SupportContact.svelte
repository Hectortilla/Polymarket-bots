<script lang="ts">
  import { PUBLIC_COPY } from "$lib/public/copy";
  import { SERVICE_IDENTITY, SUPPORT_PENDING } from "./identity";
</script>

<div class="support-contact">
  {#if SERVICE_IDENTITY.supportEmail}
    <p><a href={`mailto:${SERVICE_IDENTITY.supportEmail}`}>{SERVICE_IDENTITY.supportEmail}</a></p>
  {:else}
    <p role="status">{SUPPORT_PENDING}</p>
    <p>{PUBLIC_COPY.SUPPORT_PLACEHOLDER}</p>
  {/if}
</div>

<style>
  .support-contact {
    padding: 16px 18px;
    border: 1px solid var(--line-strong);
    border-radius: var(--radius-control);
    background: var(--surface);
  }
  .support-contact p {
    font-size: 0.8125rem;
  }
  .support-contact p[role="status"] {
    color: var(--text);
    font-weight: 550;
  }
  .support-contact p:last-child {
    margin-bottom: 0;
  }
</style>
