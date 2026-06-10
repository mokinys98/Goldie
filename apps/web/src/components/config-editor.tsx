"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { api } from "@/lib/api";
import { botConfigSchema } from "@/lib/config";
import type { BotConfig, ConfigVersion } from "@/lib/types";
import { StatusPill } from "./status-pill";

export function ConfigEditor({
  botId,
  versions,
  onChanged,
}: {
  botId: string;
  versions: ConfigVersion[];
  onChanged: () => void;
}) {
  const latest = versions[0];
  const form = useForm<BotConfig>({
    resolver: zodResolver(botConfigSchema),
    values: latest?.config,
  });

  async function create(values: BotConfig) {
    await api(`/api/v1/bots/${botId}/config-versions`, {
      method: "POST",
      body: JSON.stringify({ config: values }),
    });
    onChanged();
  }

  async function transition(version: ConfigVersion, action: "validate" | "activate") {
    await api(`/api/v1/config-versions/${version.id}/${action}`, { method: "POST" });
    onChanged();
  }

  if (!latest) return <div className="panel">No configuration found.</div>;

  return (
    <div className="split-layout">
      <form className="panel config-form" onSubmit={form.handleSubmit(create)}>
        <div className="section-title">
          <div>
            <h2>Configuration editor</h2>
            <p>Saving always creates a new immutable draft.</p>
          </div>
          <StatusPill value={latest.status} />
        </div>
        <fieldset>
          <legend>Market and strategy</legend>
          <label>Symbol<input {...form.register("market.symbol")} /></label>
          <label>Timeframe<input {...form.register("market.timeframe")} disabled /></label>
          <label>Lookback candles<input type="number" {...form.register("strategy.lookback_candles")} /></label>
          <label>Momentum points<input type="number" step="0.01" {...form.register("strategy.min_momentum_points")} /></label>
        </fieldset>
        <fieldset>
          <legend>Filters</legend>
          <label>Maximum spread points<input type="number" step="0.01" {...form.register("filters.max_spread_points")} /></label>
          <label>Stale after seconds<input type="number" {...form.register("filters.stale_after_seconds")} /></label>
        </fieldset>
        <fieldset>
          <legend>Session</legend>
          <label>Timezone<input {...form.register("session.timezone")} /></label>
          <label>Start time<input type="time" step="1" {...form.register("session.start_time")} /></label>
          <label>End time<input type="time" step="1" {...form.register("session.end_time")} /></label>
        </fieldset>
        <fieldset>
          <legend>Theoretical levels</legend>
          <label>Stop loss points<input type="number" step="0.01" {...form.register("theoretical_trade.stop_loss_points")} /></label>
          <label>Take profit points<input type="number" step="0.01" {...form.register("theoretical_trade.take_profit_points")} /></label>
        </fieldset>
        {Object.keys(form.formState.errors).length > 0 && (
          <div className="error-box">Configuration contains invalid values.</div>
        )}
        <button className="button button-primary">Save as new draft</button>
      </form>
      <div className="panel">
        <div className="section-title">
          <div>
            <h2>Version history</h2>
            <p>PostgreSQL is the active configuration source.</p>
          </div>
        </div>
        <div className="version-list">
          {versions.map((version) => (
            <div className="version-card" key={version.id}>
              <div>
                <strong>Version {version.version}</strong>
                <span>{new Date(version.created_at).toLocaleString()}</span>
              </div>
              <StatusPill value={version.status} />
              <div className="button-row">
                {version.status === "DRAFT" && (
                  <button className="button button-secondary" onClick={() => transition(version, "validate")}>
                    Validate
                  </button>
                )}
                {version.status === "VALIDATED" && (
                  <button className="button button-primary" onClick={() => transition(version, "activate")}>
                    Activate
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

