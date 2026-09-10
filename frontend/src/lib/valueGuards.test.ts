import { describe, expect, it } from "vitest";
import { isFiniteDateTime } from "./valueGuards";

describe("aware datetime ingress", () => {
  it.each(["2026-09-08T12:34:56Z", "2024-02-29T01:02:03.123456+02:00", "2026-09-08T01:02:03-05:30"])(
    "accepts an aware timestamp: %s",
    (value) => {
      expect(isFiniteDateTime(value)).toBe(true);
    },
  );
  it.each([
    null,
    123,
    "2026-09-08",
    "2026-09-08T12:34:56",
    "September 8, 2026",
    "2026-02-29T01:02:03Z",
    "2026-02-30T01:02:03Z",
    "2026-13-01T01:02:03Z",
    "2026-09-08T24:00:00Z",
    "2026-09-08T00:00:00+24:00",
    "0000-01-01T00:00:00Z",
  ])("rejects malformed, naive or impossible timestamps: %s", (value) => {
    expect(isFiniteDateTime(value)).toBe(false);
  });
});
