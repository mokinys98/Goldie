"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  Bot,
  ConfigVersion,
  MarketFeed,
  OptimizationRun,
  StrategyMetadata,
} from "@/lib/types";

function inputDate(daysAgo: number): string {
  const value = new Date(Date.now() - daysAgo * 86400000);
  value.setSeconds(0, 0);
  return value.toISOString().slice(0, 16);
}

export default function NewOptimizationPage() {
  const router = useRouter();
  const [botId, setBotId] = useState("");
  const [configId, setConfigId] = useState("");
  const [dateFrom, setDateFrom] = useState(inputDate(30));
  const [dateTo, setDateTo] = useState(inputDate(0));
  const [trialCount, setTrialCount] = useState("25");
  const [initialCapital, setInitialCapital] = useState("10000");
  const [feeMaker, setFeeMaker] = useState("0.001");
  const [feeTaker, setFeeTaker] = useState("0.001");
  const [slippageSmall, setSlippageSmall] = useState("0.0005");
  const [slippageMedium, setSlippageMedium] = useState("0.001");
  const [impactModel, setImpactModel] = useState("sqrt");
  const [limitFillTimeout, setLimitFillTimeout] = useState("30");
  const [minQtyCheck, setMinQtyCheck] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const bots = useQuery({ queryKey: ["bots"], queryFn: () => api<Bot[]>("/api/v1/bots") });
  const feeds = useQuery({
    queryKey: ["market-feeds"],
    queryFn: () => api<MarketFeed[]>("/api/v1/market-feeds"),
  });
  const strategies = useQuery({
    queryKey: ["strategies"],
    queryFn: () => api<StrategyMetadata[]>("/api/v1/strategies"),
  });
  const configs = useQuery({
    queryKey: ["bot-configs", botId],
    queryFn: () => api<ConfigVersion[]>(`/api/v1/bots/${botId}/config-versions`),
    enabled: Boolean(botId),
  });
  const selectedBot = bots.data?.find((bot) => bot.id === botId);
  const selectedFeed = feeds.data?.find((feed) => feed.id === selectedBot?.market_feed_id);
  const eligibleConfigs = (configs.data ?? []).filter((item) =>
    ["ACTIVE", "VALIDATED", "SUPERSEDED"].includes(item.status),
  );
  const selectedConfig = eligibleConfigs.find((item) => item.id === configId);
  const selectedStrategy = strategies.data?.find(
    (item) => item.name === selectedConfig?.config.strategy.name,
  );
  const parameterNames = useMemo(
    () => Object.keys(selectedStrategy?.parameters ?? {}),
    [selectedStrategy],
  );

  useEffect(() => {
    if (!botId && bots.data?.length) setBotId(bots.data[0].id);
  }, [botId, bots.data]);
  useEffect(() => {
    setConfigId(eligibleConfigs[0]?.id ?? "");
  }, [botId, configs.data]); // eslint-disable-line react-hooks/exhaustive-deps

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!selectedBot?.market_feed_id) {
      setError("Selected bot has no market feed.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const run = await api<OptimizationRun>("/api/v1/optimizations", {
        method: "POST",
        body: JSON.stringify({
          bot_id: botId,
          config_version_id: configId,
          market_feed_id: selectedBot.market_feed_id,
          date_from: new Date(dateFrom).toISOString(),
          date_to: new Date(dateTo).toISOString(),
          n_trials: Number(trialCount),
          objective: "BALANCED",
          initial_capital: initialCapital,
          fee_maker: feeMaker,
          fee_taker: feeTaker,
          slippage_small: slippageSmall,
          slippage_medium: slippageMedium,
          impact_model: impactModel,
          limit_fill_timeout_s: Number(limitFillTimeout),
          min_qty_check: minQtyCheck,
        }),
      });
      router.push(`/optimizations/${run.id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not create optimization");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="narrow-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">NEW SEARCH</span>
          <h1>Run optimization</h1>
          <p>
            Only strategy parameters are searched. Filters, session, trade
            model, and costs stay fixed.
          </p>
        </div>
      </header>
      <form className="panel form-grid" onSubmit={submit}>
        <label>
          Bot
          <select required value={botId} onChange={(event) => setBotId(event.target.value)}>
            <option value="">Select bot</option>
            {(bots.data ?? []).map((bot) => (
              <option key={bot.id} value={bot.id}>{bot.name}</option>
            ))}
          </select>
        </label>
        <label>
          Configuration version
          <select required value={configId} onChange={(event) => setConfigId(event.target.value)}>
            <option value="">Select validated configuration</option>
            {eligibleConfigs.map((item) => (
              <option key={item.id} value={item.id}>Version {item.version} - {item.status}</option>
            ))}
          </select>
        </label>
        <label>
          Market feed
          <input disabled value={selectedFeed?.provider_symbol ?? "No feed"} />
        </label>
        <label>Objective<input disabled value="BALANCED" /></label>
        <div className="compact-form form-grid">
          <label>
            From
            <input
              required
              type="datetime-local"
              value={dateFrom}
              onChange={(event) => setDateFrom(event.target.value)}
            />
          </label>
          <label>
            To
            <input
              required
              type="datetime-local"
              value={dateTo}
              onChange={(event) => setDateTo(event.target.value)}
            />
          </label>
          <label>
            Trials
            <input
              required
              type="number"
              min="1"
              max="500"
              step="1"
              value={trialCount}
              onChange={(event) => setTrialCount(event.target.value)}
            />
          </label>
          <label>
            Initial capital
            <input
              required
              type="number"
              min="1"
              step="0.01"
              value={initialCapital}
              onChange={(event) => setInitialCapital(event.target.value)}
            />
          </label>
          <label>
            Fee maker
            <input
              required
              type="number"
              min="0"
              step="0.0001"
              value={feeMaker}
              onChange={(event) => setFeeMaker(event.target.value)}
            />
          </label>
          <label>
            Fee taker
            <input
              required
              type="number"
              min="0"
              step="0.0001"
              value={feeTaker}
              onChange={(event) => setFeeTaker(event.target.value)}
            />
          </label>
          <label>
            Slippage small
            <input
              required
              type="number"
              min="0"
              step="0.0001"
              value={slippageSmall}
              onChange={(event) => setSlippageSmall(event.target.value)}
            />
          </label>
          <label>
            Slippage medium
            <input
              required
              type="number"
              min="0"
              step="0.0001"
              value={slippageMedium}
              onChange={(event) => setSlippageMedium(event.target.value)}
            />
          </label>
          <label>
            Impact model
            <select value={impactModel} onChange={(event) => setImpactModel(event.target.value)}>
              <option value="sqrt">sqrt</option>
            </select>
          </label>
          <label>
            Limit fill timeout (s)
            <input
              required
              type="number"
              min="0"
              step="1"
              value={limitFillTimeout}
              onChange={(event) => setLimitFillTimeout(event.target.value)}
            />
          </label>
          <label className="checkbox-field">
            Min qty check
            <input
              type="checkbox"
              checked={minQtyCheck}
              onChange={(event) => setMinQtyCheck(event.target.checked)}
            />
          </label>
        </div>
        <div className="panel">
          <h2>Search scope</h2>
          <p className="muted">Strategy parameters included in this optimization run.</p>
          {!parameterNames.length ? (
            <p className="muted">
              Choose a validated strategy configuration to preview searchable
              parameters.
            </p>
          ) : (
            <div className="key-values">
              {parameterNames.map((name) => (
                <div key={name}>
                  <dt>{name}</dt>
                  <dd>{String(selectedConfig?.config.strategy.parameters[name] ?? "--")}</dd>
                </div>
              ))}
            </div>
          )}
        </div>
        {error && <div className="error-box">{error}</div>}
        <div className="button-row">
          <button
            type="button"
            className="button button-secondary"
            onClick={() => router.back()}
          >
            Cancel
          </button>
          <button className="button button-primary" disabled={busy || !configId}>
            {busy ? "Queueing..." : "Run optimization"}
          </button>
        </div>
      </form>
    </section>
  );
}
