import { page } from "$app/state";
import { RETURN_TO_QUERY_PARAM, ACCOUNT_UPDATED_QUERY_PARAM, ACCOUNT_DELETION_QUERY_PARAM } from "./navigation";
import { ACCOUNT_COPY } from "./recovery/copy";
import { LIFECYCLE_COPY } from "$lib/lifecycle/copy";
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import runtimeContract from "$lib/runtimeContract.fixture.json";
import LoginForm from "./LoginForm.svelte";
import RegistrationForm from "./RegistrationForm.svelte";
import { AUTH_COPY } from "./copy";
import { HTTP_STATUS } from "$lib/api/http";
import { accountSession } from "./session";

const mocks = vi.hoisted(() => ({ login: vi.fn(), register: vi.fn() }));
vi.mock("$lib/api/generated", () => mocks);
vi.mock("$app/state", async () => {
  // Vitest hoists this factory before static imports initialize.
  const { LOGIN_PATH } = await import("./navigation");
  return { page: { url: new URL(LOGIN_PATH, "http://localhost") } };
});

afterEach(() => {
  page.url.search = "";
  cleanup();
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

describe("credential failure presentation", () => {
  it.each([
    [ACCOUNT_UPDATED_QUERY_PARAM, ACCOUNT_COPY.DONE],
    [ACCOUNT_DELETION_QUERY_PARAM, LIFECYCLE_COPY.REQUESTED],
  ])("shows the %s redirect notice only in login", (query, message) => {
    page.url.searchParams.set(query, "1");
    const login = render(LoginForm);
    expect(screen.getByRole("status")).toHaveTextContent(message);
    login.unmount();
    render(RegistrationForm);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it.each([LoginForm, RegistrationForm])("keeps each workflow's successful destination", async (component) => {
    const destination = "/runs/example";
    page.url.searchParams.set(RETURN_TO_QUERY_PARAM, destination);
    const registering = component === RegistrationForm;
    (registering ? mocks.register : mocks.login).mockResolvedValue({ data: { id: "account", email: "a@a.a" } });
    const accept = vi.spyOn(accountSession, "acceptLogin").mockImplementation(() => {});
    render(component);
    await fillCredentials();
    await fireEvent.click(screen.getByRole("button", { name: registering ? AUTH_COPY.REGISTER : AUTH_COPY.SIGN_IN }));
    await waitFor(() =>
      expect(accept).toHaveBeenCalledWith(registering ? runtimeContract.accountManagement.accountPath : destination),
    );
  });

  it.each([false, true])("applies password creation rules only when registering=%s", (registering) => {
    render(registering ? RegistrationForm : LoginForm);
    expect(screen.getByLabelText(AUTH_COPY.PASSWORD)).toHaveAttribute(
      "minlength",
      String(registering ? runtimeContract.auth.passwordMinLength : runtimeContract.auth.existingPasswordMinLength),
    );
  });

  it("submits a one-character existing password", async () => {
    mocks.login.mockResolvedValue({ data: { id: "account", email: "a@a.a" } });
    const accept = vi.spyOn(accountSession, "acceptLogin").mockImplementation(() => {});
    render(LoginForm);
    await fireEvent.input(screen.getByLabelText(AUTH_COPY.EMAIL), { target: { value: "a@a.a" } });
    await fireEvent.input(screen.getByLabelText(AUTH_COPY.PASSWORD), { target: { value: "a" } });
    await fireEvent.click(screen.getByRole("button", { name: AUTH_COPY.SIGN_IN }));
    await waitFor(() => expect(accept).toHaveBeenCalledWith(null));
    expect(mocks.login).toHaveBeenCalledWith({ body: { email: "a@a.a", password: "a" } });
  });

  it.each([
    { registering: true, status: HTTP_STATUS.CONFLICT, message: AUTH_COPY.REGISTER_ERROR },
    { registering: false, status: HTTP_STATUS.TOO_MANY_REQUESTS, message: AUTH_COPY.RATE_LIMIT_ERROR },
    { registering: true, status: HTTP_STATUS.SERVICE_UNAVAILABLE, message: AUTH_COPY.SERVICE_ERROR },
  ])("handles a $status outcome and clears the password", async ({ registering, status, message }) => {
    const submit = registering ? mocks.register : mocks.login;
    submit.mockResolvedValue({ response: { status } });
    render(registering ? RegistrationForm : LoginForm);
    await fillCredentials();
    await fireEvent.click(screen.getByRole("button", { name: registering ? AUTH_COPY.REGISTER : AUTH_COPY.SIGN_IN }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(message));
    expect(screen.getByLabelText(AUTH_COPY.PASSWORD)).toHaveValue("");
    expect(screen.getByRole("button")).toBeEnabled();
  });

  it("shows transport failure without leaving submission disabled", async () => {
    mocks.login.mockRejectedValue(new Error("offline"));
    render(LoginForm);
    await fillCredentials();
    await fireEvent.click(screen.getByRole("button", { name: AUTH_COPY.SIGN_IN }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(AUTH_COPY.SERVICE_ERROR));
    expect(screen.getByLabelText(AUTH_COPY.PASSWORD)).toHaveValue("");
    expect(screen.getByRole("button")).toBeEnabled();
  });

  it("handles a resolved failure with no HTTP response", async () => {
    mocks.login.mockResolvedValue({ response: undefined });
    render(LoginForm);
    await fillCredentials();
    await fireEvent.click(screen.getByRole("button", { name: AUTH_COPY.SIGN_IN }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(AUTH_COPY.SERVICE_ERROR));
    expect(screen.getByLabelText(AUTH_COPY.PASSWORD)).toHaveValue("");
    expect(screen.getByRole("button")).toBeEnabled();
  });

  it("accepts a successful account response through the session lifecycle", async () => {
    mocks.login.mockResolvedValue({ data: { id: "account", email: "first@example.com" } });
    const accept = vi.spyOn(accountSession, "acceptLogin").mockImplementation(() => {});
    render(LoginForm);
    await fillCredentials();
    await fireEvent.click(screen.getByRole("button", { name: AUTH_COPY.SIGN_IN }));
    await waitFor(() => expect(accept).toHaveBeenCalledWith(null));
  });
});

async function fillCredentials(): Promise<void> {
  await fireEvent.input(screen.getByLabelText(AUTH_COPY.EMAIL), { target: { value: "first@example.com" } });
  await fireEvent.input(screen.getByLabelText(AUTH_COPY.PASSWORD), {
    target: { value: "correct password for testing" },
  });
}
