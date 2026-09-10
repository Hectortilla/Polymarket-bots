import { LIFECYCLE_COPY } from "$lib/lifecycle/copy";
import { ALLOWANCE_COPY } from "./copy";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, expect, it, vi } from "vitest";
import runtimeContract from "$lib/runtimeContract.fixture.json";
import { isAccountUsage } from "./validation";

const mocks = vi.hoisted(() => ({ read: vi.fn() }));
vi.mock("$lib/api/generated", () => ({ readUsage: mocks.read }));
import AccountUsage from "./AccountUsage.svelte";

const usage = {
  policy: runtimeContract.resourcePolicy,
  active_runs: 1,
  queued_runs: 2,
  saved_bots: 3,
  retained_runs: 5,
};
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

it("shows private usage and refreshes after capacity changes", async () => {
  mocks.read.mockResolvedValueOnce({ data: usage }).mockResolvedValueOnce({ data: { ...usage, queued_runs: 0 } });
  render(AccountUsage);
  expect(await screen.findByText(new RegExp(`${usage.queued_runs}/${usage.policy.queued_runs} queued`))).toBeTruthy();
  expect(screen.queryByText(/saved templates/i)).toBeNull();
  expect(usage.policy).not.toHaveProperty("saved_templates");
  expect(usage.policy).not.toHaveProperty("revisions_per_bot");
  await fireEvent.click(screen.getByRole("button", { name: ALLOWANCE_COPY.REFRESH }));
  await waitFor(() => expect(screen.getByText(new RegExp(`0/${usage.policy.queued_runs} queued`))).toBeTruthy());
});

it("shows unavailable usage instead of inventing free capacity", async () => {
  mocks.read.mockRejectedValue(new Error("unavailable"));
  render(AccountUsage);
  expect(await screen.findByText(ALLOWANCE_COPY.UNAVAILABLE)).toBeTruthy();
});

it("reveals the allowance details on hover and dismisses them after leaving", async () => {
  mocks.read.mockResolvedValue({ data: usage });
  render(AccountUsage);
  const trigger = await screen.findByRole("button", { name: ALLOWANCE_COPY.DETAILS });
  expect(screen.queryByRole("tooltip")).toBeNull();

  const hover = new Event("pointerenter");
  Object.assign(hover, { pointerType: "mouse" });
  await fireEvent(trigger, hover);
  expect(screen.getByRole("tooltip")).toHaveTextContent(LIFECYCLE_COPY.HISTORY);
  expect(trigger).toHaveAttribute("aria-expanded", "true");
  await fireEvent.pointerLeave(trigger.parentElement!);
  expect(screen.queryByRole("tooltip")).toBeNull();
});

it("supports focus, Escape, tap toggling and outside dismissal for allowance details", async () => {
  mocks.read.mockResolvedValue({ data: usage });
  render(AccountUsage);
  const trigger = await screen.findByRole("button", { name: ALLOWANCE_COPY.DETAILS });

  await fireEvent.focus(trigger);
  expect(screen.getByRole("tooltip")).toBeVisible();
  await fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("tooltip")).toBeNull();
  expect(trigger).toHaveAttribute("aria-expanded", "false");

  await fireEvent.click(trigger);
  await fireEvent.pointerLeave(trigger.parentElement!);
  expect(screen.getByRole("tooltip")).toBeVisible();
  await fireEvent.click(trigger);
  expect(screen.queryByRole("tooltip")).toBeNull();

  await fireEvent.click(trigger);
  await fireEvent.pointerDown(document.body);
  expect(screen.queryByRole("tooltip")).toBeNull();
});

it("rejects missing or malformed policy and usage at the client boundary", () => {
  expect(isAccountUsage(usage)).toBe(true);
  expect(isAccountUsage({ ...usage, policy: {} })).toBe(false);
  expect(isAccountUsage({ ...usage, active_runs: -1 })).toBe(false);
  expect(isAccountUsage({ ...usage, queued_runs: "0" })).toBe(false);
});
