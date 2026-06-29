import type { Bot, ConfigVersion } from "@/lib/types";

export function getEligibleConfigs(configs: ConfigVersion[]): ConfigVersion[] {
  return configs.filter((item) =>
    ["ACTIVE", "VALIDATED", "SUPERSEDED"].includes(item.status),
  );
}

export function defaultConfigId(bot: Bot, configs: ConfigVersion[]): string {
  return (
    configs.find((item) => item.id === bot.active_config_version_id)?.id ??
    configs[0]?.id ??
    ""
  );
}

export function runButtonLabel(count: number): string {
  return count === 1 ? "Run optimization" : `Run ${count} optimizations`;
}
