<script lang="ts">
  import type { Snippet } from "svelte";
  import type { CredentialsWritable } from "$lib/api/generated";
  import runtimeContract from "$lib/runtimeContract.fixture.json";
  import { AUTH_COPY } from "./copy";

  let {
    onsubmit,
    submitLabel,
    passwordAutocomplete,
    passwordMinimumLength,
    passwordHelp,
  }: {
    onsubmit: (credentials: CredentialsWritable) => Promise<string | undefined>;
    submitLabel: string;
    passwordAutocomplete: "new-password" | "current-password";
    passwordMinimumLength: number;
    passwordHelp?: Snippet;
  } = $props();
  let email = $state("");
  let password = $state("");
  let busy = $state(false);
  let error = $state<string | undefined>();

  async function submit(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (busy) return;
    busy = true;
    error = undefined;
    try {
      error = await onsubmit({ email, password });
    } finally {
      password = "";
      busy = false;
    }
  }
</script>

<form onsubmit={submit}>
  <label for="account-email">{AUTH_COPY.EMAIL}</label>
  <input
    id="account-email"
    type="email"
    autocomplete="username"
    maxlength={runtimeContract.auth.emailMaxLength}
    bind:value={email}
    required
  />
  <label for="account-password">{AUTH_COPY.PASSWORD}</label>
  <input
    id="account-password"
    type="password"
    autocomplete={passwordAutocomplete}
    minlength={passwordMinimumLength}
    maxlength={runtimeContract.auth.passwordMaxLength}
    bind:value={password}
    required
  />
  {@render passwordHelp?.()}
  {#if error}<p role="alert" class="notice error">{error}</p>{/if}
  <button class="primary" type="submit" disabled={busy}>{busy ? AUTH_COPY.BUSY : submitLabel}</button>
</form>
