<script lang="ts">
  import { PUBLIC_COPY } from "$lib/public/copy";
  import { SERVICE_IDENTITY, SUPPORT_PENDING } from "./identity";
</script>

{#if SERVICE_IDENTITY.supportEmail}
  <p><a href={`mailto:${SERVICE_IDENTITY.supportEmail}`}>{SERVICE_IDENTITY.supportEmail}</a></p>
{:else}
  <p role="status">{SUPPORT_PENDING}</p>
  <p>{PUBLIC_COPY.SUPPORT_PLACEHOLDER}</p>
{/if}
