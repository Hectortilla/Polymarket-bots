import { describe, expect, it } from "vitest";
import { safeReturnPath, accountPath, LOGIN_PATH } from "./navigation";

describe("account return paths", () => {
  it("preserves a local resource path and its query", () => {
    expect(safeReturnPath("/runs/123?tab=events")).toBe("/runs/123?tab=events");
    expect(accountPath(LOGIN_PATH, "/bots/new")).toContain(encodeURIComponent("/bots/new"));
  });
  it.each([
    "https://foreign.example/",
    "//foreign.example/",
    "/\\foreign.example",
    "/login",
    "/register",
    "/\n/foreign.example",
    "javascript:alert(1)",
  ])("rejects unsafe or cyclic return path %s", (value) => {
    expect(safeReturnPath(value)).toBe("/");
  });
});
