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

type OptimizationProfileKey = "perfect" | "realistic" | "stress" | "other";

type OptimizationProfile = {
  key: OptimizationProfileKey;
  title: string;
  subtitle: string;
  fromTo: string;
  trials: string;
  initialCapital: string;
  feeMaker: string;
  feeTaker: string;
  takerSlippage: string;
  slippageSmall: string;
  slippageMedium: string;
  modelSqrtLimit: string;
  fill: "perfect" | "simulated" | "custom";
  limitFillTimeout: string;
  minQtyThreshold: string;
  minQtyCheck: boolean;
};

const optimizationProfiles: OptimizationProfile[] = [
  {
    key: "perfect",
    title: "1. Perfect-fill",
    subtitle: "Comparison only, no fees or slippage.",
    fromTo: "2023-01-01:2025-01-01",
    trials: "100",
    initialCapital: "10000",
    feeMaker: "0",
    feeTaker: "0",
    takerSlippage: "0",
    slippageSmall: "0",
    slippageMedium: "0",
    modelSqrtLimit: "1.0",
    fill: "perfect",
    limitFillTimeout: "1",
    minQtyThreshold: "0",
    minQtyCheck: false,
  },
  {
    key: "realistic",
    title: "2. Realistic",
    subtitle: "Baseline optimizer assumptions.",
    fromTo: "2023-01-01:2025-01-01",
    trials: "500",
    initialCapital: "10000",
    feeMaker: "0.0002",
    feeTaker: "0.0006",
    takerSlippage: "0.0005",
    slippageSmall: "0.0002",
    slippageMedium: "0.001",
    modelSqrtLimit: "1.0",
    fill: "simulated",
    limitFillTimeout: "5",
    minQtyThreshold: "0.01",
    minQtyCheck: true,
  },
  {
    key: "stress",
    title: "3. Stress",
    subtitle: "Conservative robustness check.",
    fromTo: "2023-01-01:2025-01-01",
    trials: "500",
    initialCapital: "10000",
    feeMaker: "0.0005",
    feeTaker: "0.0010",
    takerSlippage: "0.0015",
    slippageSmall: "0.0008",
    slippageMedium: "0.003",
    modelSqrtLimit: "0.7",
    fill: "simulated",
    limitFillTimeout: "10",
    minQtyThreshold: "0.02",
    minQtyCheck: true,
  },
  {
    key: "other",
    title: "4. Other",
    subtitle: "Open all fields and enter custom values.",
    fromTo: "custom",
    trials: "25",
    initialCapital: "10000",
    feeMaker: "0.001",
    feeTaker: "0.001",
    takerSlippage: "not supported",
    slippageSmall: "0.0005",
    slippageMedium: "0.001",
    modelSqrtLimit: "not supported",
    fill: "custom",
    limitFillTimeout: "30",
    minQtyThreshold: "not supported",
    minQtyCheck: true,
  },
];

function inputDate(daysAgo: number): string {
  const value = new Date(Date.now() - daysAgo * 86400000);
  value.setSeconds(0, 0);
  return value.toISOString().slice(0, 16);
}

function profileDate(value: string): string {
  return `${value}T00:00`;
}

export default function NewOptimizationPage() {
  const router = useRouter();
  const [profileKey, setProfileKey] = useState<OptimizationProfileKey>("realistic");
  const [botId, setBotId] = useState("");
  const [configId, setConfigId] = useState("");
  const [dateFrom, setDateFrom] = useState(profileDate("2023-01-01"));
  const [dateTo, setDateTo] = useState(profileDate("2025-01-01"));
  const [trialCount, setTrialCount] = useState("500");
  const [initialCapital, setInitialCapital] = useState("10000");
  const [feeMaker, setFeeMaker] = useState("0.0002");
  const [feeTaker, setFeeTaker] = useState("0.0006");
  const [slippageSmall, setSlippageSmall] = useState("0.0002");
  const [slippageMedium, setSlippageMedium] = useState("0.001");
  const [impactModel, setImpactModel] = useState("sqrt");
  const [limitFillTimeout, setLimitFillTimeout] = useState("5");
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
    setFeeMaker(selectedProfile.feeMaker);
    setFeeTaker(selectedProfile.feeTaker);
    setSlippageSmall(selectedProfile.slippageSmall);
    setSlippageMedium(selectedProfile.slippageMedium);
    setImpactModel("sqrt");
    setLimitFillTimeout(selectedProfile.limitFillTimeout);
    setMinQtyCheck(selectedProfile.minQtyCheck);
  }, [selectedProfile]);

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
                  setFeeMaker(profile.feeMaker);
                  setFeeTaker(profile.feeTaker);
                  setSlippageSmall(profile.slippageSmall);
                  setSlippageMedium(profile.slippageMedium);
                  setImpactModel("sqrt");
                  setLimitFillTimeout(profile.limitFillTimeout);
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
            <strong>Fill status:</strong> `fill` is not a backend field in this app yet.
            This page maps the profile to the supported optimizer fields and shows
            unsupported assumptions for reference only.
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
              <div><dt>takerSlippage</dt><dd>{selectedProfile.takerSlippage} (not sent)</dd></div>
              <div><dt>smallSlippage</dt><dd>{selectedProfile.slippageSmall}</dd></div>
              <div><dt>mediumImpact</dt><dd>{selectedProfile.slippageMedium}</dd></div>
              <div><dt>modelsqrtLimit</dt><dd>{selectedProfile.modelSqrtLimit} (not sent)</dd></div>
              <div><dt>fill</dt><dd>{selectedProfile.fill} (not sent)</dd></div>
              <div><dt>timeout_s</dt><dd>{selectedProfile.limitFillTimeout}</dd></div>
              <div><dt>Min_qty_check</dt><dd>{selectedProfile.minQtyThreshold} (not sent)</dd></div>
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
