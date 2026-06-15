import { describe, expect, it } from "vitest";

import { performanceRange, vilniusMidnightUtc } from "@/lib/performance-dates";

describe("Vilnius performance date boundaries", () => {
  it("uses a 23-hour day when daylight saving time starts", () => {
    expect(performanceRange("2026-03-29", 1)).toEqual({
      from: "2026-03-28T22:00:00.000Z",
      to: "2026-03-29T21:00:00.000Z",
    });
  });

  it("uses a 25-hour day when daylight saving time ends", () => {
    expect(performanceRange("2026-10-25", 1)).toEqual({
      from: "2026-10-24T21:00:00.000Z",
      to: "2026-10-25T22:00:00.000Z",
    });
  });

  it("converts ordinary Vilnius midnight to UTC", () => {
    expect(vilniusMidnightUtc("2026-06-15")).toBe("2026-06-14T21:00:00.000Z");
  });
});
