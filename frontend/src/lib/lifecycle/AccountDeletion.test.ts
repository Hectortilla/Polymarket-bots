import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { HTTP_STATUS } from "$lib/api/http";
import { ACCOUNT_COPY } from "$lib/auth/recovery/copy";
import { AUTH_COPY } from "$lib/auth/copy";
import AccountDeletion from "./AccountDeletion.svelte";
import { LIFECYCLE_COPY } from "./copy";

const { request, revoked } = vi.hoisted(() => ({ request: vi.fn(), revoked: vi.fn() }));
vi.mock("$lib/api/generated", () => ({ requestAccountDeletion: request }));
vi.mock("$lib/auth/session", () => ({ accountSession: { credentialsRevoked: revoked } }));
afterEach(cleanup);
beforeEach(() => {
  request.mockReset();
  revoked.mockReset();
});

async function confirmedForm() {
  render(AccountDeletion);
  await fireEvent.input(screen.getByLabelText(LIFECYCLE_COPY.PASSWORD), {
    target: { value: "deletion fixture password" },
  });
  await fireEvent.click(screen.getByLabelText(LIFECYCLE_COPY.CONFIRM));
  return screen.getByRole("button", { name: LIFECYCLE_COPY.DELETE }).closest("form")!;
}

it("keeps access on password rejection and clears the entered password", async () => {
  request.mockResolvedValue({ response: { status: HTTP_STATUS.FORBIDDEN } });
  await fireEvent.submit(await confirmedForm());
  expect(await screen.findByRole("alert")).toHaveTextContent(ACCOUNT_COPY.REAUTH_FAILED);
  expect(revoked).not.toHaveBeenCalled();
  expect(screen.getByLabelText(LIFECYCLE_COPY.PASSWORD)).toHaveValue("");
});

it("explains an ambiguous response without claiming deletion succeeded", async () => {
  request.mockRejectedValue(new TypeError("response lost"));
  await fireEvent.submit(await confirmedForm());
  expect(await screen.findByRole("alert")).toHaveTextContent(LIFECYCLE_COPY.AMBIGUOUS_RESPONSE);
  expect(revoked).not.toHaveBeenCalled();
});

it("allows only one pending deletion submission and recovers controls after rejection", async () => {
  let finish!: (result: unknown) => void;
  request.mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const form = await confirmedForm();
  await fireEvent.submit(form);
  await fireEvent.submit(form);
  expect(request).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("button", { name: AUTH_COPY.BUSY })).toBeDisabled();
  finish({ response: { status: HTTP_STATUS.FORBIDDEN } });
  await waitFor(() => expect(screen.getByRole("button", { name: LIFECYCLE_COPY.DELETE })).not.toBeDisabled());
});
