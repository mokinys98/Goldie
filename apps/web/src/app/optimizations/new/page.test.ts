import { describe, expect, it } from "vitest";
import { optimizationProfiles } from "./profiles";
import { defaultConfigId, getEligibleConfigs, runButtonLabel } from "./selection";
import type { Bot, ConfigVersion } from "@/lib/types";

function profilePeriodDays(fromTo: string): number {
  const [from, to] = fromTo.split(":");
  return (
    new Date(`${to}T00:00:00Z`).getTime() -
    new Date(`${from}T00:00:00Z`).getTime()
  ) / 86400000;
}

function oneMinuteCandles(days: number): number {
  return days * 24 * 60;
}

describe("optimizationProfiles", () => {
  it("keeps fixed profile date ranges within the API limit", () => {
    for (const profile of optimizationProfiles) {
      if (profile.fromTo === "custom") continue;

      expect(profilePeriodDays(profile.fromTo)).toBeLessThanOrEqual(365);
    }
  });

  it("shows the perfect-fill EUR/USD group as a short 100-trial sanity run", () => {
    const profile = optimizationProfiles.find((item) => item.key === "perfect");
    expect(profile).toBeDefined();
    expect(profile?.fromTo).toBe("2025-07-01:2026-06-15");
    expect(profilePeriodDays(profile!.fromTo)).toBe(349);
    expect(oneMinuteCandles(349)).toBe(502560);
    expect(profile?.trials).toBe("100");
    expect(profile?.datasetEstimate).toContain("502,560");
    expect(profile?.runtimeEstimate).toContain("2 minutes or faster");
  });
});

describe("bulk optimization selection", () => {
  const bot = { active_config_version_id: "active" } as Bot;
  const configs = [
    { id: "draft", status: "DRAFT" },
    { id: "validated", status: "VALIDATED" },
    { id: "active", status: "ACTIVE" },
  ] as ConfigVersion[];

  it("uses the active configuration and excludes drafts", () => {
    const eligible = getEligibleConfigs(configs);

    expect(eligible.map((item) => item.id)).toEqual(["validated", "active"]);
    expect(defaultConfigId(bot, eligible)).toBe("active");
  });

  it("shows the queued run count in the bulk action", () => {
    expect(runButtonLabel(1)).toBe("Run optimization");
    expect(runButtonLabel(3)).toBe("Run 3 optimizations");
  });
});
