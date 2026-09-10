import { PUBLIC_COPY } from "./copy";
import { cleanup, render, screen } from "@testing-library/svelte";
import { afterEach, expect, it } from "vitest";
import { SERVICE_IDENTITY, SUPPORT_PENDING } from "./identity";
import SupportContact from "./SupportContact.svelte";

const originalContact = SERVICE_IDENTITY.supportEmail;
afterEach(() => {
  cleanup();
  SERVICE_IDENTITY.supportEmail = originalContact;
});
it("states missing contact honestly without presenting a sending control", () => {
  SERVICE_IDENTITY.supportEmail = null;
  render(SupportContact);
  expect(screen.getByRole("status")).toHaveTextContent(SUPPORT_PENDING);
  expect(screen.queryByRole("link")).toBeNull();
});
it("shows a configured mailbox and removes the placeholder state", () => {
  SERVICE_IDENTITY.supportEmail = "support@example.test";
  render(SupportContact);
  expect(screen.getByRole("link", { name: SERVICE_IDENTITY.supportEmail })).toHaveAttribute(
    "href",
    `mailto:${SERVICE_IDENTITY.supportEmail}`,
  );
  expect(screen.queryByText(SUPPORT_PENDING)).toBeNull();
  expect(screen.queryByText(PUBLIC_COPY.SUPPORT_PLACEHOLDER)).toBeNull();
});
