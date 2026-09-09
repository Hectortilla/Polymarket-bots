<script lang="ts">
  import contract from '$lib/runtimeContract.fixture.json';
  import { ACCOUNT_COPY } from './copy';
  let { password = $bindable(''), confirmation = $bindable('') }: { password?: string; confirmation?: string } = $props();
</script>
<label>{ACCOUNT_COPY.NEW_PASSWORD}<input type="password" autocomplete="new-password" minlength={contract.auth.passwordMinLength} maxlength={contract.auth.passwordMaxLength} bind:value={password} required /></label>
<label>{ACCOUNT_COPY.CONFIRM_PASSWORD}<input type="password" autocomplete="new-password" minlength={contract.auth.passwordMinLength} maxlength={contract.auth.passwordMaxLength} bind:value={confirmation} required /></label>
