<script lang="ts">
  let { id, detail }: { id: string; detail: string } = $props();
</script>

<span class="failure-detail-tooltip" {id} role="tooltip">
  <span class="failure-detail-tooltip-label">Failure details</span>
  <span>{detail}</span>
</span>
