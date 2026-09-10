import { PUBLIC_INFORMATION_PATH } from "$lib/public/navigation";
import { ACCOUNT_SESSION_STATUS } from "./session/state";
import { runPath } from "$lib/navigation";
import { LOGIN_PATH } from "./navigation";
import { afterEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";

const mocks = vi.hoisted(() => ({ currentUser: vi.fn(), logout: vi.fn() }));
vi.mock("$lib/api/generated", () => mocks);

import { AccountSession } from "./session";
import { AUTH_COPY } from "./copy";
import { HTTP_STATUS } from "$lib/api/http";

let session = new AccountSession();

const first = { id: "11111111-1111-4111-8111-111111111111", email: "first@example.com" };
const second = { id: "22222222-2222-4222-8222-222222222222", email: "second@example.com" };

afterEach(() => {
  session.clear();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
  session = new AccountSession();
});

describe("private account lifetime", () => {
  it("restores a current user after reload", async () => {
    mocks.currentUser.mockResolvedValue({ data: first });
    await session.restore();
    expect(get(session.account)).toEqual(first);
  });
  it("closes every stream when clearing the user", () => {
    session.state.set({ status: ACCOUNT_SESSION_STATUS.AUTHENTICATED, user: first });
    const close = vi.fn();
    session.streams.track(close);
    session.clear();
    expect(close).toHaveBeenCalledOnce();
    expect(get(session.account)).toBeNull();
  });
  it("closes old streams when the browser cookie switches accounts", async () => {
    session.state.set({ status: ACCOUNT_SESSION_STATUS.AUTHENTICATED, user: first });
    const close = vi.fn();
    session.streams.track(close);
    mocks.currentUser.mockResolvedValue({ data: second });
    await session.restore();
    expect(close).toHaveBeenCalledOnce();
    expect(get(session.account)).toEqual(second);
  });
  it("discards a restoration that completes after logout", async () => {
    let resolve!: (value: unknown) => void;
    mocks.currentUser.mockReturnValue(
      new Promise((done) => {
        resolve = done;
      }),
    );
    const pending = session.restore();
    session.clear();
    resolve({ data: first });
    await pending;
    expect(get(session.account)).toBeNull();
  });
  it("removes private state when account infrastructure fails", async () => {
    session.state.set({ status: ACCOUNT_SESSION_STATUS.AUTHENTICATED, user: first });
    mocks.currentUser.mockRejectedValue(new Error("offline"));
    await session.restore();
    expect(get(session.account)).toBeNull();
  });
});

describe("account failure and race boundaries", () => {
  it("shows a resolved service failure without treating it as expired credentials", async () => {
    const replace = vi.fn();
    vi.stubGlobal("window", { location: { pathname: runPath("example"), search: "", replace } });
    session.state.set({ status: ACCOUNT_SESSION_STATUS.AUTHENTICATED, user: first });
    mocks.currentUser.mockResolvedValue({ response: { status: HTTP_STATUS.SERVICE_UNAVAILABLE } });
    await session.restore();
    expect(get(session.account)).toBeNull();
    expect(get(session.ready)).toBe(true);
    expect(get(session.error)).toBe(AUTH_COPY.RESTORE_ERROR);
    expect(replace).not.toHaveBeenCalled();
  });

  it("does not restore private data while revocation is pending", async () => {
    let revoke!: () => void;
    mocks.logout.mockReturnValue(
      new Promise<void>((resolve) => {
        revoke = resolve;
      }),
    );
    vi.stubGlobal("window", { location: { pathname: LOGIN_PATH } });
    session.state.set({ status: ACCOUNT_SESSION_STATUS.AUTHENTICATED, user: first });
    const signingOut = session.signOut();
    await session.restore();
    expect(mocks.currentUser).not.toHaveBeenCalled();
    expect(get(session.account)).toBeNull();
    expect(get(session.ready)).toBe(false);
    revoke();
    await signingOut;
    expect(get(session.ready)).toBe(true);
  });

  it("clears private data and offers retry when logout fails", async () => {
    session.state.set({ status: ACCOUNT_SESSION_STATUS.AUTHENTICATED, user: first });
    const close = vi.fn();
    session.streams.track(close);
    mocks.logout.mockRejectedValue(new Error("offline"));
    await session.signOut();
    expect(close).toHaveBeenCalledOnce();
    expect(get(session.account)).toBeNull();
    expect(get(session.ready)).toBe(true);
    expect(get(session.error)).toBe(AUTH_COPY.SIGN_OUT_ERROR);
  });

  it("coalesces simultaneous account checks", async () => {
    mocks.currentUser.mockResolvedValue({ data: first });
    await Promise.all([session.restore(), session.restore()]);
    expect(mocks.currentUser).toHaveBeenCalledOnce();
  });

  it("does not let stale restoration end an in-progress logout", async () => {
    let restore!: (value: unknown) => void;
    let revoke!: () => void;
    mocks.currentUser.mockReturnValue(
      new Promise((resolve) => {
        restore = resolve;
      }),
    );
    mocks.logout.mockReturnValue(
      new Promise<void>((resolve) => {
        revoke = resolve;
      }),
    );
    const replace = vi.fn();
    vi.stubGlobal("window", { location: { pathname: runPath("example"), search: "", replace } });
    const pendingRestore = session.restore();
    const pendingLogout = session.signOut();
    restore({ data: first });
    await pendingRestore;
    expect(get(session.account)).toBeNull();
    expect(get(session.ready)).toBe(false);
    revoke();
    await pendingLogout;
    expect(replace).toHaveBeenCalledOnce();
  });

  it("validates cross-tab messages and closes streams before reloading", () => {
    class FakeChannel {
      static current: FakeChannel;
      onmessage: ((event: MessageEvent<unknown>) => void) | null = null;
      close = vi.fn();
      postMessage = vi.fn();
      constructor(readonly name: string) {
        FakeChannel.current = this;
      }
    }
    const reload = vi.fn();
    vi.stubGlobal("BroadcastChannel", FakeChannel);
    vi.stubGlobal("window", { location: { reload, replace: vi.fn() } });
    session.state.set({ status: ACCOUNT_SESSION_STATUS.AUTHENTICATED, user: first });
    const close = vi.fn();
    session.streams.track(close);
    const unwatch = session.watchChanges();
    const channel = FakeChannel.current;
    channel.onmessage?.(new MessageEvent("message", { data: { unexpected: true } }));
    expect(get(session.account)).toEqual(first);
    expect(reload).not.toHaveBeenCalled();
    // Use the actual sender to produce the finite channel contract.
    session.acceptLogin(null);
    channel.onmessage?.(new MessageEvent("message", { data: channel.postMessage.mock.calls[0][0] }));
    expect(close).toHaveBeenCalledOnce();
    expect(get(session.account)).toBeNull();
    expect(reload).toHaveBeenCalledOnce();
    unwatch();
    expect(channel.close).toHaveBeenCalledOnce();
  });
});

it("clears private streams and redirects after a confirmed 401", async () => {
  const replace = vi.fn();
  vi.stubGlobal("window", { location: { pathname: runPath("example"), search: "", replace } });
  session.state.set({ status: ACCOUNT_SESSION_STATUS.AUTHENTICATED, user: first });
  const close = vi.fn();
  session.streams.track(close);
  mocks.currentUser.mockResolvedValue({ response: { status: HTTP_STATUS.UNAUTHORIZED } });
  await session.restore();
  expect(get(session.account)).toBeNull();
  expect(close).toHaveBeenCalledOnce();
  expect(replace).toHaveBeenCalledOnce();
});

it.each(Object.values(PUBLIC_INFORMATION_PATH))(
  "clears expired private data without redirecting the public page %s",
  (path) => {
    const replace = vi.fn();
    vi.stubGlobal("window", { location: { pathname: path, search: "", replace } });
    session.state.set({ status: ACCOUNT_SESSION_STATUS.AUTHENTICATED, user: first });
    const close = vi.fn();
    session.streams.track(close);
    session.expire();
    expect(get(session.account)).toBeNull();
    expect(close).toHaveBeenCalledOnce();
    expect(replace).not.toHaveBeenCalled();
  },
);
