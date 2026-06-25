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
import { optimizationProfiles, type OptimizationProfileKey } from "./profiles";

function inputDate(daysAgo: number): string {
  const value = new Date(Date.now() - daysAgo * 86400000);
  value.setSeconds(0, 0);
  return value.toISOString().slice(0, 16);
}

function profileDate(value: string): string {
  return `${value}T00:00`;
}

function optimizationPeriodDays(from: string, to: string): number {
  return (new Date(to).getTime() - new Date(from).getTime()) / 86400000;
}

export default function NewOptimizationPage() {
  const router = useRouter();
  const [profileKey, setProfileKey] = useState<OptimizationProfileKey>("realistic");
  const [botId, setBotId] = useState("");
  const [configId, setConfigId] = useState("");
  const [dateFrom, setDateFrom] = useState(profileDate("2023-01-01"));
  const [dateTo, setDateTo] = useState(profileDate("2025-01-01"));
  const [trialCount, setTrialCount] = useState("100");
  const [initialCapital, setInitialCapital] = useState("10000");
  const [fillMode, setFillMode] = useState<"perfect" | "simulated">("simulated");
  const [feeMaker, setFeeMaker] = useState("0.0002");
  const [feeTaker, setFeeTaker] = useState("0.0006");
  const [takerSlippage, setTakerSlippage] = useState("0.0005");
  const [slippageSmall, setSlippageSmall] = useState("0.0002");
  const [slippageMedium, setSlippageMedium] = useState("0.001");
  const [impactModel, setImpactModel] = useState("sqrt");
  const [modelSqrtLimit, setModelSqrtLimit] = useState("1.0");
  const [limitFillTimeout, setLimitFillTimeout] = useState("5");
  const [minQtyThreshold, setMinQtyThreshold] = useState("0.01");
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
  const selectedProfile = optimizationProfiles.find((item) => item.key === profileKey);
  const customProfile = profileKey === "other";

  useEffect(() => {
    if (!botId && bots.data?.length) setBotId(bots.data[0].id);
  }, [botId, bots.data]);
  useEffect(() => {
    setConfigId(eligibleConfigs[0]?.id ?? "");
  }, [botId, configs.data]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!selectedProfile || selectedProfile.key === "other") return;
    const [from, to] = selectedProfile.fromTo.split(":");
    setDateFrom(profileDate(from));
    setDateTo(profileDate(to));
    setTrialCount(selectedProfile.trials);
    setInitialCapital(selectedProfile.initialCapital);
    setFillMode(selectedProfile.fill === "perfect" ? "perfect" : "simulated");
    setFeeMaker(selectedProfile.feeMaker);
    setFeeTaker(selectedProfile.feeTaker);
    setTakerSlippage(selectedProfile.takerSlippage);
    setSlippageSmall(selectedProfile.slippageSmall);
    setSlippageMedium(selectedProfile.slippageMedium);
    setImpactModel("sqrt");
    setModelSqrtLimit(selectedProfile.modelSqrtLimit);
    setLimitFillTimeout(selectedProfile.limitFillTimeout);
    setMinQtyThreshold(selectedProfile.minQtyThreshold);
    setMinQtyCheck(selectedProfile.minQtyCheck);
  }, [selectedProfile]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!selectedBot?.market_feed_id) {
      setError("Selected bot has no market feed.");
      return;
    }
    if (optimizationPeriodDays(dateFrom, dateTo) > 365) {
      setError("Optimization period cannot exceed 365 days.");
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
          fill_mode: fillMode,
          fee_maker: feeMaker,
          fee_taker: feeTaker,
          taker_slippage: takerSlippage,
          slippage_small: slippageSmall,
          slippage_medium: slippageMedium,
          medium_impact: slippageMedium,
          impact_model: impactModel,
          model_sqrt_limit: modelSqrtLimit,
          limit_fill_timeout_s: Number(limitFillTimeout),
          min_qty_threshold: minQtyThreshold,
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
            Choose an optimization profile. Only strategy parameters are searched;
            filters, session, trade model, and costs stay fixed.
          </p>
        </div>
      </header>
      <form className="panel form-grid" onSubmit={submit}>
        <div className="profile-picker">
          {optimizationProfiles.map((profile) => (
            <button
              key={profile.key}
              type="button"
              className={`profile-option${profile.key === profileKey ? " selected" : ""}`}
              onClick={() => {
                setProfileKey(profile.key);
                if (profile.key === "other") {
                  setDateFrom(inputDate(30));
                  setDateTo(inputDate(0));
                  setTrialCount(profile.trials);
                  setInitialCapital(profile.initialCapital);
                  setFillMode("simulated");
                  setFeeMaker(profile.feeMaker);
                  setFeeTaker(profile.feeTaker);
                  setTakerSlippage("0");
                  setSlippageSmall(profile.slippageSmall);
                  setSlippageMedium(profile.slippageMedium);
                  setImpactModel("sqrt");
                  setModelSqrtLimit("1.0");
                  setLimitFillTimeout(profile.limitFillTimeout);
                  setMinQtyThreshold("0");
                  setMinQtyCheck(profile.minQtyCheck);
                }
              }}
            >
              <strong>{profile.title}</strong>
              <span>{profile.subtitle}</span>
            </button>
          ))}
        </div>
        {selectedProfile && (
          <div className="info-box">
            <strong>Fill status:</strong> This profile is saved as a run-level
            execution model. Optuna trials optimize strategy parameters only.
          </div>
        )}
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
        {selectedProfile && !customProfile && (
          <div className="panel">
            <h2>{selectedProfile.title} profile</h2>
            <div className="key-values">
              <div><dt>FromTo</dt><dd>{selectedProfile.fromTo}</dd></div>
              <div><dt>Trials</dt><dd>{selectedProfile.trials}</dd></div>
              <div><dt>Initial capital</dt><dd>{selectedProfile.initialCapital}</dd></div>
              <div><dt>makerFee</dt><dd>{selectedProfile.feeMaker}</dd></div>
              <div><dt>takerFee</dt><dd>{selectedProfile.feeTaker}</dd></div>
              <div><dt>takerSlippage</dt><dd>{selectedProfile.takerSlippage}</dd></div>
              <div><dt>smallSlippage</dt><dd>{selectedProfile.slippageSmall}</dd></div>
              <div><dt>mediumImpact</dt><dd>{selectedProfile.slippageMedium}</dd></div>
              <div><dt>modelsqrtLimit</dt><dd>{selectedProfile.modelSqrtLimit}</dd></div>
              <div><dt>fill</dt><dd>{selectedProfile.fill}</dd></div>
              <div><dt>timeout_s</dt><dd>{selectedProfile.limitFillTimeout}</dd></div>
              <div><dt>Min_qty_check</dt><dd>{selectedProfile.minQtyThreshold}</dd></div>
              <div><dt>check</dt><dd>{String(selectedProfile.minQtyCheck)}</dd></div>
            </div>
          </div>
        )}
        {customProfile && <div className="compact-form form-grid">
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
            Fill
            <select value={fillMode} onChange={(event) => setFillMode(event.target.value as "perfect" | "simulated")}>
              <option value="perfect">perfect</option>
              <option value="simulated">simulated</option>
            </select>
          </label>
          <label>
            Taker slippage
            <input
              required
              type="number"
              min="0"
              step="0.0001"
              value={takerSlippage}
              onChange={(event) => setTakerSlippage(event.target.value)}
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
            Medium impact
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
            Model sqrt limit
            <input
              required
              type="number"
              min="0"
              step="0.1"
              value={modelSqrtLimit}
              onChange={(event) => setModelSqrtLimit(event.target.value)}
            />
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
          <label>
            Min qty threshold
            <input
              required
              type="number"
              min="0"
              step="0.01"
              value={minQtyThreshold}
              onChange={(event) => setMinQtyThreshold(event.target.value)}
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
        </div>}
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
