import { describe, expect, it } from "vitest";
import { optimizationProfiles } from "./profiles";

function profilePeriodDays(fromTo: string): number {
  const [from, to] = fromTo.split(":");
  return (
    new Date(`${to}T00:00:00Z`).getTime() -
    new Date(`${from}T00:00:00Z`).getTime()
  ) / 86400000;
}

describe("optimizationProfiles", () => {
  it("keeps fixed profile date ranges within the API limit", () => {
    for (const profile of optimizationProfiles) {
      if (profile.fromTo === "custom") continue;

      expect(profilePeriodDays(profile.fromTo)).toBeLessThanOrEqual(365);
    }
  });
});
