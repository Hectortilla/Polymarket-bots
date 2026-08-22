<script lang="ts">
  import type { RunStatus } from '$lib/api/generated';
  import { RUN_STATUS_PRESENTATION } from './status';

  let { status }: { status: RunStatus } = $props();
  const presentation = $derived(RUN_STATUS_PRESENTATION[status]);
</script>

<span class="status" data-tone={presentation.tone}>{presentation.label}</span>
